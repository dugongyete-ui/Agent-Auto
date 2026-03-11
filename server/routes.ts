import { createServer, type Server } from "node:http";
import { spawn } from "node:child_process";
import * as https from "node:https";
import * as net from "node:net";
import * as fs from "node:fs";
import * as path from "node:path";
import { randomUUID } from "node:crypto";
import multer from "multer";
import { WebSocketServer, WebSocket as WsWebSocket } from "ws";

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
  const model = process.env.CF_MODEL || "@cf/meta/llama-3.3-70b-instruct-fp8-fast";
  const agentModel = process.env.CF_AGENT_MODEL || "@cf/meta/llama-3.3-70b-instruct-fp8-fast";
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

// Exported so index.ts can attach VNC WebSocket handling to extra port servers
export let handleVncUpgrade: ((req: any, socket: any, head: any) => void) | null = null;

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
  const VNC_DISPLAY = ":10";
  const VNC_PORT_NUM = 5910;

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
      const { spawn: spawnProc, execSync } = require("node:child_process");

      // Fast binary lookup: only use `which` (respects PATH) with known fallbacks
      const findBin = (name: string, fallback: string | null = null): string => {
        try {
          const p = execSync(`which ${name} 2>/dev/null`, { encoding: "utf-8", timeout: 2000 }).trim();
          if (p) return p;
        } catch {}
        return fallback !== null ? fallback : name;
      };

      // Use known nix store paths as fallbacks (from environment introspection)
      const xvfb = findBin("Xvfb", "/nix/store/8jlz3l9kf9w7zq263vy3ms5c90hy96r4-xorg-server-21.1.13/bin/Xvfb");
      const x11vnc = findBin("x11vnc", "/nix/store/x15ycm43gka3mkj8lxy14mv8iazxk60s-x11vnc-0.9.16/bin/x11vnc");
      const xsetroot = findBin("xsetroot", "");

      console.log(`[VNC] Binaries: Xvfb=${xvfb} x11vnc=${x11vnc}`);

      // Kill any stale processes on the display/port before starting
      try { execSync(`pkill -f "Xvfb ${VNC_DISPLAY}" 2>/dev/null; true`); } catch {}
      try { execSync(`pkill -f "x11vnc.*${VNC_PORT_NUM}" 2>/dev/null; true`); } catch {}
      await new Promise(r => setTimeout(r, 800));

      // Remove stale X lock files so Xvfb can start fresh
      const displayNum = VNC_DISPLAY.replace(":", "");
      try {
        const lockFile = `/tmp/.X${displayNum}-lock`;
        const socketFile = `/tmp/.X11-unix/X${displayNum}`;
        if (fs.existsSync(lockFile)) { fs.unlinkSync(lockFile); console.log(`[VNC] Removed stale lock: ${lockFile}`); }
        if (fs.existsSync(socketFile)) { fs.unlinkSync(socketFile); console.log(`[VNC] Removed stale socket: ${socketFile}`); }
      } catch (e: any) { console.warn("[VNC] Lock cleanup warning:", e.message); }

      // 1. Start Xvfb
      const xvfbProc = spawnProc(xvfb, [VNC_DISPLAY, "-screen", "0", "1280x720x24", "-ac", "-nolisten", "tcp"], {
        detached: false, stdio: "ignore",
        env: { ...process.env },
      });
      _vncProcs.push(xvfbProc);
      await new Promise(r => setTimeout(r, 2000));

      if (xvfbProc.exitCode !== null) {
        console.error("[VNC] Xvfb failed to start");
        _vncStarting = false; return false;
      }

      // 2. Draw solid background so display isn't black
      if (xsetroot) {
        try {
          spawnProc(xsetroot, ["-solid", "#0e0e14"], {
            detached: false, stdio: "ignore",
            env: { ...process.env, DISPLAY: VNC_DISPLAY },
          });
        } catch {}
      }

      // 3. Start x11vnc on VNC_PORT_NUM (avoids conflict with any system :5900)
      const x11vncProc = spawnProc(x11vnc, [
        "-display", VNC_DISPLAY, "-forever", "-shared", "-nopw",
        "-rfbport", String(VNC_PORT_NUM),
        "-noxdamage", "-noxfixes", "-nocursorshape", "-nocursor", "-quiet",
      ], {
        detached: false, stdio: "ignore",
        env: { ...process.env, DISPLAY: VNC_DISPLAY },
      });
      _vncProcs.push(x11vncProc);
      await new Promise(r => setTimeout(r, 2000));

      if (x11vncProc.exitCode !== null) {
        console.error("[VNC] x11vnc failed to start");
        _vncStarting = false; return false;
      }

      // 4. Set DISPLAY for Playwright and sub-processes
      process.env.DISPLAY = VNC_DISPLAY;
      process.env.DZECK_VNC_DISPLAY = VNC_DISPLAY;

      // 5. Launch Chromium on the virtual display so it's not blank
      try {
        const chromiumPath = findBin("chromium", "") || findBin("chromium-browser", "") || findBin("google-chrome", "");
        if (chromiumPath) {
          spawnProc(chromiumPath, [
            "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
            "--window-size=1280,720", "--start-maximized",
            "about:blank",
          ], {
            detached: false, stdio: "ignore",
            env: { ...process.env, DISPLAY: VNC_DISPLAY },
          });
          console.log("[VNC] Chromium launched on display");
        }
      } catch {}

      _vncStarted = true;
      _vncStarting = false;
      console.log(`[VNC] Stack ready: DISPLAY=${VNC_DISPLAY} VNC_PORT=${VNC_PORT_NUM} (WS proxied natively)`);
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

  // ─── VNC viewer HTML page (loaded by React Native WebView) ───────────────
  app.get("/vnc-view", (_req: any, res: any) => {
    const html = path.join(__dirname, "templates", "vnc-view.html");
    if (fs.existsSync(html)) {
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.setHeader("Cache-Control", "no-store");
      res.sendFile(html);
    } else {
      res.status(404).send("vnc-view.html not found");
    }
  });

  // ─── VNC status endpoint ──────────────────────────────────────────────────
  app.get("/api/vnc/status", (_req: any, res: any) => {
    const wsPort = 6081;
    const vncPort = 5900;
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

  // ─── Auto-start VNC at server boot so DISPLAY is set for all agent requests ─
  setImmediate(() => {
    ensureVncRunning().then((ok) => {
      if (ok) {
        console.log("[VNC] Auto-started VNC stack at server boot — browser will use display :10");
      } else {
        console.warn("[VNC] Auto-start failed — VNC display may be unavailable");
      }
    }).catch((e: any) => {
      console.warn("[VNC] Auto-start error:", e?.message);
    });
  });

  // ─── WebSocket proxy for VNC (/vnc-ws → raw TCP :5910) ─────────────────
  // Native Node.js WS→TCP proxy — no websockify needed.
  // noVNC sends binary RFB protocol over WebSocket; we relay it directly to x11vnc.
  const wss = new WebSocketServer({ noServer: true });

  wss.on("connection", (clientWs: any, _req: any) => {
    console.log(`[VNC-WS] Client connected → proxying to VNC TCP:${VNC_PORT_NUM}`);

    const vncSocket = net.createConnection({ port: VNC_PORT_NUM, host: "127.0.0.1" });

    vncSocket.on("connect", () => {
      console.log(`[VNC-WS] TCP connected to x11vnc:${VNC_PORT_NUM} ✓`);
    });

    // Relay: WebSocket client → VNC TCP socket
    clientWs.on("message", (data: Buffer | ArrayBuffer | Buffer[], isBinary: boolean) => {
      if (vncSocket.writable) {
        const buf = Buffer.isBuffer(data) ? data : Buffer.from(data as ArrayBuffer);
        vncSocket.write(buf);
      }
    });

    // Relay: VNC TCP socket → WebSocket client
    vncSocket.on("data", (data: Buffer) => {
      if (clientWs.readyState === 1 /* OPEN */) {
        clientWs.send(data, { binary: true });
      }
    });

    const cleanup = () => {
      try { if (clientWs.readyState !== 3) clientWs.close(); } catch {}
      try { vncSocket.destroy(); } catch {}
    };

    vncSocket.on("error", (err: Error) => {
      console.error("[VNC-WS] TCP error:", err.message);
      cleanup();
    });

    vncSocket.on("close", () => {
      console.log("[VNC-WS] VNC TCP connection closed");
      cleanup();
    });

    clientWs.on("error", () => cleanup());
    clientWs.on("close", () => {
      console.log("[VNC-WS] Browser client disconnected");
      cleanup();
    });
  });

  // Shared upgrade handler — also applied to extra-port servers in index.ts
  handleVncUpgrade = (req: any, socket: any, head: any) => {
    const url = req.url || "";
    if (url.startsWith("/vnc-ws")) {
      wss.handleUpgrade(req, socket, head, (ws: any) => {
        wss.emit("connection", ws, req);
      });
    } else {
      socket.destroy();
    }
  };

  httpServer.on("upgrade", handleVncUpgrade);

  return httpServer;
}
