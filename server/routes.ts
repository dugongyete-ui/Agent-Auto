import { createServer, type Server } from "node:http";
import { spawn } from "node:child_process";
import * as https from "node:https";
import * as net from "node:net";
import * as fs from "node:fs";
import * as path from "node:path";
import { randomUUID } from "node:crypto";
import multer from "multer";

// ─── File Download Store ─────────────────────────────────────────────────────
const DZECK_FILES_DIR = "/tmp/dzeck_files";
const DZECK_UPLOADS_DIR = "/tmp/dzeck_files/uploads";
if (!fs.existsSync(DZECK_FILES_DIR)) {
  fs.mkdirSync(DZECK_FILES_DIR, { recursive: true });
}
if (!fs.existsSync(DZECK_UPLOADS_DIR)) {
  fs.mkdirSync(DZECK_UPLOADS_DIR, { recursive: true });
}

// ─── Multer Upload Config ─────────────────────────────────────────────────────
const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, DZECK_UPLOADS_DIR),
    filename: (_req, file, cb) => {
      const ext = path.extname(file.originalname);
      cb(null, `${Date.now()}-${randomUUID().slice(0,8)}${ext}`);
    },
  }),
  limits: { fileSize: 50 * 1024 * 1024 },
});

// ─── E2B Cloud Sandbox (replaces VNC) ────────────────────────────────────────
const E2B_ENABLED = !!process.env.E2B_API_KEY;

if (E2B_ENABLED) {
  console.log("[E2B] Cloud sandbox mode enabled. Browser/shell tools run in isolated E2B environment.");
} else {
  console.warn("[E2B] E2B_API_KEY not set. Using local fallback for browser/shell tools.");
}

function getCFConfig() {
  const accountId = process.env.CF_ACCOUNT_ID || "";
  const gatewayName = process.env.CF_GATEWAY_NAME || "";
  const model = process.env.CF_MODEL || "@cf/qwen/qwen3-30b-a3b-fp8";
  const agentModel = process.env.CF_AGENT_MODEL || "@cf/meta/llama-4-scout-17b-16e-instruct";
  const apiKey = process.env.CF_API_KEY || "";
  const cfPath = `/v1/${accountId}/${gatewayName}/workers-ai/run/${model}`;
  return { cfPath, apiKey, model, agentModel };
}

function setupSSEHeaders(res: any) {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  res.flushHeaders();
}

export async function registerRoutes(app: any): Promise<Server> {
  const startupCfg = getCFConfig();
  if (!startupCfg.apiKey) {
    console.warn("[WARNING] CF_API_KEY is not set. AI features will not work.");
  }

  app.get("/status", (_req: any, res: any) => {
    res.json({ status: "ok", timestamp: new Date().toISOString() });
  });

  app.get("/api/status", (_req: any, res: any) => {
    res.json({ status: "ok", timestamp: new Date().toISOString(), e2bEnabled: E2B_ENABLED });
  });

  // ─── Chat endpoint ─────────────────────────────────────────────────────────
  app.post("/api/chat", async (req: any, res: any) => {
    const { messages } = req.body;
    if (!messages || !Array.isArray(messages)) {
      return res.status(400).json({ error: "messages array is required" });
    }

    const { cfPath, apiKey } = getCFConfig();
    const requestBody = JSON.stringify({ messages, stream: false, max_tokens: 4096 });
    const options: https.RequestOptions = {
      hostname: "gateway.ai.cloudflare.com",
      port: 443,
      path: cfPath,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
        "Content-Length": Buffer.byteLength(requestBody),
      },
    };

    let retryCount = 0;
    const maxRetries = 4;
    const attemptRequest = () => {
      const apiReq = https.request(options, (apiRes) => {
        if (apiRes.statusCode === 429 || (apiRes.statusCode && apiRes.statusCode >= 500)) {
          const wait = Math.pow(2, retryCount) * 1000;
          apiRes.resume();
          if (retryCount < maxRetries) { retryCount++; setTimeout(attemptRequest, wait); }
          else res.status(503).json({ error: "AI service rate limited, please try again" });
          return;
        }
        let buffer = "";
        apiRes.on("data", (chunk: Buffer) => { buffer += chunk.toString(); });
        apiRes.on("end", () => {
          try {
            const parsed = JSON.parse(buffer);
            const content = parsed.response ?? parsed.choices?.[0]?.message?.content ?? parsed.result?.response ?? "";
            if (!content) return res.status(500).json({ error: "Empty response from AI" });
            res.json({ type: "message", content, timestamp: new Date().toISOString() });
          } catch { res.status(500).json({ error: "Failed to parse AI response" }); }
        });
        apiRes.on("error", () => res.status(500).json({ error: "AI service error" }));
      });
      apiReq.on("error", () => res.status(500).json({ error: "AI service connection error" }));
      apiReq.write(requestBody);
      apiReq.end();
    };
    attemptRequest();
  });

  // ─── Agent endpoint with SSE ───────────────────────────────────────────────
  app.post("/api/agent", (req: any, res: any) => {
    const { message, messages, attachments, session_id, resume_from_session } = req.body;
    if (!message && (!messages || !Array.isArray(messages))) {
      return res.status(400).json({ error: "message or messages array is required" });
    }

    setupSSEHeaders(res);

    const { apiKey, agentModel } = getCFConfig();
    const sid = session_id || randomUUID();

    const proc = spawn("python3", ["-u", "-m", "server.agent.agent_flow"], {
      stdio: ["pipe", "pipe", "pipe"],
      cwd: process.cwd(),
      env: {
        ...process.env,
        CF_API_KEY: apiKey,
        CF_AGENT_MODEL: agentModel,
        PYTHONPATH: process.cwd(),
        PYTHONUNBUFFERED: "1",
      },
    });

    proc.stdin.write(JSON.stringify({
      message: message || "",
      messages: messages || [],
      model: agentModel,
      attachments: attachments || [],
      session_id: sid,
      resume_from_session: resume_from_session || null,
    }));
    proc.stdin.end();

    let buf = "";
    let doneSent = false;
    let stderrBuffer = "";

    res.write(`data: ${JSON.stringify({ type: "session", session_id: sid, e2b_enabled: E2B_ENABLED })}\n\n`);

    proc.stdout.on("data", (data: Buffer) => {
      buf += data.toString();
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const parsed = JSON.parse(line);
          if (parsed.type === "done") { doneSent = true; res.write("data: [DONE]\n\n"); }
          else res.write(`data: ${JSON.stringify(parsed)}\n\n`);
        } catch {}
      }
    });

    proc.stderr.on("data", (data: Buffer) => {
      stderrBuffer += data.toString();
      console.error("[Agent stderr]:", data.toString());
    });

    proc.on("close", (code: number | null) => {
      // Only send a user-facing error if process failed AND stderr has real (non-benign) content
      if (code !== 0 && stderrBuffer && !doneSent && !res.writableEnded) {
        const BENIGN = [/redis/i, /mongodb/i, /motor/i, /DNS/i, /Name or service not known/i,
          /ConnectionRefusedError/i, /\[CacheStore\]/i, /\[SessionStore\]/i, /\[SessionService\]/i,
          /WARNING:/i, /DeprecationWarning/i, /connection failed/i, /Traceback/i,
          /aioredis/i, /pymongo/i, /socket\.gaierror/i, /\[agent\]/i];
        const hasRealError = !BENIGN.some(p => p.test(stderrBuffer));
        if (hasRealError) {
          // Send a clean, user-friendly error — not raw Python traceback
          res.write(`data: ${JSON.stringify({ type: "error", error: "Agen mengalami kesalahan internal. Silakan coba lagi." })}\n\n`);
        }
      }
      if (!doneSent && !res.writableEnded) res.write("data: [DONE]\n\n");
      res.end();
      if (code !== 0) console.error(`Agent process exited with code ${code}. Stderr: ${stderrBuffer.slice(-500)}`);
    });

    res.on("close", () => { proc.kill(); });
  });

  app.get("/api/test", (_req: any, res: any) => {
    res.json({
      message: "API is working",
      timestamp: new Date().toISOString(),
      cloudflareConfigured: !!startupCfg.apiKey,
      e2bEnabled: E2B_ENABLED,
    });
  });

  // ─── File Download endpoint ─────────────────────────────────────────────────
  // Serves files created by the AI agent (file_write, shell_exec output, etc.)
  // Supports all file types: zip, pdf, py, js, mp4, mp3, docx, xlsx, etc.
  app.get("/api/files/download", (req: any, res: any) => {
    const rawPath = req.query.path as string;
    const rawName = req.query.name as string;

    if (!rawPath) {
      return res.status(400).json({ error: "path is required" });
    }

    // Decode path
    let filePath: string;
    try {
      filePath = decodeURIComponent(rawPath);
    } catch {
      return res.status(400).json({ error: "invalid path encoding" });
    }

    // Security: only allow files in /tmp/, /home/, or project workspace
    const allowed = ["/tmp/", "/home/", process.cwd()];
    const isAllowed = allowed.some(prefix => filePath.startsWith(prefix));
    if (!isAllowed) {
      return res.status(403).json({ error: "access denied: path not allowed" });
    }

    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: `File not found: ${filePath}` });
    }

    const stat = fs.statSync(filePath);
    if (!stat.isFile()) {
      return res.status(400).json({ error: "path is not a file" });
    }

    const fileName = rawName ? decodeURIComponent(rawName) : path.basename(filePath);
    const ext = path.extname(fileName).toLowerCase().slice(1);

    // MIME type map for common file types
    const MIME: Record<string, string> = {
      // Archives
      zip: "application/zip", rar: "application/x-rar-compressed",
      "7z": "application/x-7z-compressed", tar: "application/x-tar",
      gz: "application/gzip", bz2: "application/x-bzip2", xz: "application/x-xz",
      iso: "application/x-iso9660-image",
      // Documents
      pdf: "application/pdf",
      doc: "application/msword",
      docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      xls: "application/vnd.ms-excel",
      xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      odt: "application/vnd.oasis.opendocument.text",
      ods: "application/vnd.oasis.opendocument.spreadsheet",
      txt: "text/plain", md: "text/markdown", rtf: "application/rtf",
      csv: "text/csv", tsv: "text/tab-separated-values",
      // Data
      json: "application/json", xml: "application/xml",
      yaml: "application/x-yaml", yml: "application/x-yaml",
      toml: "application/toml", ini: "text/plain",
      sql: "application/sql", db: "application/x-sqlite3",
      sqlite: "application/x-sqlite3", sqlite3: "application/x-sqlite3",
      // Images
      jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png",
      gif: "image/gif", bmp: "image/bmp", webp: "image/webp",
      svg: "image/svg+xml", ico: "image/x-icon",
      // Video
      mp4: "video/mp4", mkv: "video/x-matroska", avi: "video/x-msvideo",
      mov: "video/quicktime", webm: "video/webm", flv: "video/x-flv",
      // Audio
      mp3: "audio/mpeg", wav: "audio/wav", ogg: "audio/ogg",
      aac: "audio/aac", flac: "audio/flac", m4a: "audio/mp4",
      // Code
      py: "text/x-python", js: "text/javascript", ts: "text/typescript",
      tsx: "text/typescript", jsx: "text/javascript", html: "text/html",
      htm: "text/html", css: "text/css", sh: "text/x-shellscript",
      bash: "text/x-shellscript", java: "text/x-java-source",
      cpp: "text/x-c", c: "text/x-c", go: "text/x-go",
      rs: "text/x-rust", rb: "text/x-ruby", php: "text/x-php",
      // Binary
      exe: "application/x-msdownload", msi: "application/x-msinstaller",
      apk: "application/vnd.android.package-archive",
      deb: "application/x-debian-package", rpm: "application/x-rpm",
      wasm: "application/wasm",
    };

    const mimeType = MIME[ext] || "application/octet-stream";
    const fileSize = stat.size;

    res.setHeader("Content-Type", mimeType);
    res.setHeader("Content-Disposition", `attachment; filename="${fileName}"`);
    res.setHeader("Content-Length", fileSize);
    res.setHeader("Cache-Control", "no-cache");

    const stream = fs.createReadStream(filePath);
    stream.on("error", (err) => {
      console.error("[FileDownload] Stream error:", err);
      if (!res.headersSent) res.status(500).json({ error: "Failed to stream file" });
    });
    stream.pipe(res);
  });

  // ─── File Upload endpoint ────────────────────────────────────────────────────
  app.post("/api/upload", (req: any, res: any, next: any) => {
    upload.array("files", 10)(req, res, (multerErr: any) => {
      if (multerErr) {
        const msg = multerErr.code === "LIMIT_FILE_SIZE"
          ? "File terlalu besar (max 50MB)"
          : multerErr.message || "Upload gagal";
        return res.status(400).json({ error: msg });
      }
      try {
        const files = (req.files as any[]) || [];
        if (files.length === 0) {
          return res.status(400).json({ error: "Tidak ada file yang diunggah" });
        }
        if (!fs.existsSync(DZECK_UPLOADS_DIR)) {
          fs.mkdirSync(DZECK_UPLOADS_DIR, { recursive: true });
        }
        const result = files.map((f: any) => {
          const filePath = f.path;
          const fileName = f.originalname;
          const mime = f.mimetype || "application/octet-stream";
          const size = f.size;
          const isImage = mime.startsWith("image/");
          const isText = mime.startsWith("text/") || /\.(txt|md|py|js|ts|json|csv|xml|html|css|sh|yaml|yml|toml|ini|log)$/i.test(fileName);
          let preview: string | null = null;
          if (isText && size < 500 * 1024) {
            try { preview = fs.readFileSync(filePath, "utf-8"); } catch {}
          }
          return {
            filename: fileName,
            path: filePath,
            mime,
            size,
            is_image: isImage,
            is_text: isText,
            preview,
            download_url: `/api/files/download?path=${encodeURIComponent(filePath)}&name=${encodeURIComponent(fileName)}`,
          };
        });
        res.json({ files: result });
      } catch (err: any) {
        res.status(500).json({ error: "Upload gagal: " + err.message });
      }
    });
  });

  // ─── File list endpoint (files created by AI) ───────────────────────────────
  app.get("/api/files/list", (_req: any, res: any) => {
    try {
      if (!fs.existsSync(DZECK_FILES_DIR)) {
        return res.json({ files: [] });
      }
      const files = fs.readdirSync(DZECK_FILES_DIR).map(name => {
        const full = path.join(DZECK_FILES_DIR, name);
        const stat = fs.statSync(full);
        return {
          name,
          size: stat.size,
          created: stat.birthtime,
          download_url: `/api/files/download?path=${encodeURIComponent(full)}&name=${encodeURIComponent(name)}`,
        };
      });
      res.json({ files });
    } catch (e) {
      res.json({ files: [] });
    }
  });

  // ─── VNC start/manage (managed by Node.js server) ───────────────────────
  const _vncProcs: any[] = [];
  let _vncStarted = false;
  let _vncStarting = false;

  async function ensureVncRunning(): Promise<boolean> {
    if (_vncStarted) {
      const allAlive = _vncProcs.every((p: any) => p.exitCode === null);
      if (allAlive) return true;
      _vncStarted = false;
      _vncProcs.length = 0;
    }
    if (_vncStarting) {
      return new Promise(resolve => setTimeout(() => resolve(_vncStarted), 5000));
    }
    _vncStarting = true;

    try {
      const { spawn: spawnProc } = require("node:child_process");
      const findBin = (name: string): string => {
        const { execSync } = require("node:child_process");
        try { return execSync(`which ${name}`, { encoding: "utf-8" }).trim(); } catch {}
        try {
          const result = execSync(`find /nix/store -name ${name} -type f 2>/dev/null | head -1`, { encoding: "utf-8" }).trim();
          return result || name;
        } catch { return name; }
      };

      const xvfb = findBin("Xvfb");
      const x11vnc = findBin("x11vnc");
      const DISPLAY = ":10";
      const VNC_PORT = "5910";
      const WS_PORT = "6081";

      // 1. Start Xvfb
      const xvfbProc = spawnProc(xvfb, [DISPLAY, "-screen", "0", "1280x720x24", "-ac"], {
        detached: false, stdio: "ignore",
        env: { ...process.env },
      });
      _vncProcs.push(xvfbProc);
      await new Promise(r => setTimeout(r, 1500));

      if (xvfbProc.exitCode !== null) {
        console.error("[VNC] Xvfb failed to start");
        _vncStarting = false; return false;
      }

      // 2. Start x11vnc
      const x11vncProc = spawnProc(x11vnc, [
        "-display", DISPLAY, "-forever", "-shared", "-nopw",
        "-rfbport", VNC_PORT, "-noxdamage", "-noxfixes", "-quiet",
      ], {
        detached: false, stdio: "ignore",
        env: { ...process.env, DISPLAY },
      });
      _vncProcs.push(x11vncProc);
      await new Promise(r => setTimeout(r, 1500));

      if (x11vncProc.exitCode !== null) {
        console.error("[VNC] x11vnc failed to start");
        _vncStarting = false; return false;
      }

      // 3. Start websockify
      const wsProc = spawnProc("python3", [
        "-m", "websockify", WS_PORT, `127.0.0.1:${VNC_PORT}`,
      ], { detached: false, stdio: "ignore", env: { ...process.env } });
      _vncProcs.push(wsProc);
      await new Promise(r => setTimeout(r, 1000));

      if (wsProc.exitCode !== null) {
        console.error("[VNC] websockify failed to start");
        _vncStarting = false; return false;
      }

      // 4. Set DISPLAY for Playwright
      process.env.DISPLAY = DISPLAY;
      process.env.DZECK_VNC_DISPLAY = DISPLAY;

      _vncStarted = true;
      _vncStarting = false;
      console.log(`[VNC] Stack ready: DISPLAY=${DISPLAY} VNC=${VNC_PORT} WS=${WS_PORT}`);
      return true;
    } catch (err: any) {
      console.error("[VNC] Failed to start:", err.message);
      _vncStarting = false;
      return false;
    }
  }

  app.post("/api/vnc/start", async (_req: any, res: any) => {
    const started = await ensureVncRunning();
    res.json({ started });
  });

  // ─── VNC status endpoint ──────────────────────────────────────────────────
  app.get("/api/vnc/status", (_req: any, res: any) => {
    const wsPort = 6081;
    const vncPort = 5910;
    const tcpCheck = net.createConnection({ port: vncPort, host: "127.0.0.1" });
    tcpCheck.setTimeout(800);
    tcpCheck.on("connect", () => {
      tcpCheck.destroy();
      res.json({ ready: true, ws_port: wsPort, vnc_port: vncPort });
    });
    tcpCheck.on("error", () => {
      res.json({ ready: false, ws_port: wsPort, vnc_port: vncPort });
    });
    tcpCheck.on("timeout", () => {
      tcpCheck.destroy();
      res.json({ ready: false, ws_port: wsPort, vnc_port: vncPort });
    });
  });

  const httpServer = createServer(app);

  // ─── WebSocket proxy for VNC (/vnc-ws → websockify :6081) ───────────────
  httpServer.on("upgrade", (req: any, socket: any, head: any) => {
    const url = req.url || "";

    if (!url.startsWith("/vnc-ws")) {
      socket.destroy();
      return;
    }

    const http = require("node:http");
    const proxyHeaders = Object.assign({}, req.headers, { host: "127.0.0.1:6081" });

    const proxyReq = http.request({
      host: "127.0.0.1",
      port: 6081,
      method: req.method || "GET",
      path: "/",
      headers: proxyHeaders,
    });

    proxyReq.on("upgrade", (_proxyRes: any, proxySocket: any, proxyHead: any) => {
      const resLines = [
        "HTTP/1.1 101 Switching Protocols",
        `Upgrade: websocket`,
        "Connection: Upgrade",
        `Sec-WebSocket-Accept: ${_proxyRes.headers["sec-websocket-accept"] || ""}`,
      ];
      const proto = _proxyRes.headers["sec-websocket-protocol"];
      if (proto) resLines.push(`Sec-WebSocket-Protocol: ${proto}`);
      socket.write(resLines.join("\r\n") + "\r\n\r\n");

      if (proxyHead && proxyHead.length > 0) proxySocket.write(proxyHead);
      if (head && head.length > 0) proxySocket.write(head);

      proxySocket.pipe(socket);
      socket.pipe(proxySocket);

      socket.on("close", () => proxySocket.destroy());
      socket.on("error", () => proxySocket.destroy());
      proxySocket.on("close", () => socket.destroy());
      proxySocket.on("error", () => socket.destroy());
    });

    proxyReq.on("error", (err: any) => {
      console.error("[VNC-WS] Proxy to websockify failed:", err.message);
      try { socket.write("HTTP/1.1 503 VNC Not Ready\r\n\r\n"); } catch {}
      socket.destroy();
    });

    proxyReq.end();
  });

  return httpServer;
}
