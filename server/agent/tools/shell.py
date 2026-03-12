"""
Shell execution tools for Dzeck AI Agent.
Uses E2B cloud sandbox for isolated, secure command execution.
Falls back to local subprocess if E2B is unavailable.

Provides: ShellTool class + backward-compatible functions.
"""
import os
import queue
import subprocess
import time
import threading
from typing import Optional, Dict, Any, Callable

from server.agent.models.tool_result import ToolResult
from server.agent.tools.base import BaseTool, tool

E2B_ENABLED = bool(os.environ.get("E2B_API_KEY", ""))

_shell_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()

_stream_local = threading.local()

def set_stream_queue(q: Optional[queue.Queue]) -> None:
    """Register a streaming output queue for the current thread."""
    _stream_local.queue = q

def get_stream_queue() -> Optional[queue.Queue]:
    """Get the streaming output queue for the current thread."""
    return getattr(_stream_local, "queue", None)


def _get_or_create_session(sid: str) -> Dict[str, Any]:
    with _sessions_lock:
        if sid not in _shell_sessions:
            _shell_sessions[sid] = {
                "popen": None,
                "output": "",
                "command": "",
                "return_code": None,
                "lock": threading.Lock(),
            }
        return _shell_sessions[sid]


def _get_session(sid: str) -> Optional[Dict[str, Any]]:
    with _sessions_lock:
        return _shell_sessions.get(sid)


def _run_e2b(command: str, exec_dir: str = "/home/user/dzeck-ai", timeout: int = 90) -> Dict[str, Any]:
    """Execute command via E2B cloud sandbox. Auto-ensures workspace dir exists."""
    try:
        from server.agent.tools.e2b_sandbox import run_command
        return run_command(command, workdir=exec_dir, timeout=timeout)
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "exit_code": -1}


def _run_local(command: str, exec_dir: str = "/tmp", timeout: int = 90) -> Dict[str, Any]:
    """Execute command locally via subprocess with streaming output support."""
    import select
    try:
        if not os.path.isdir(exec_dir):
            exec_dir = "/tmp"

        env = {**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "xterm-256color"}
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=exec_dir,
            env=env,
            bufsize=1,
        )

        stream_q = get_stream_queue()
        stdout_lines = []
        stderr_lines = []
        start = time.time()

        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                proc.kill()
                return {"success": False, "stdout": "".join(stdout_lines),
                        "stderr": "Command timed out after {}s".format(timeout), "exit_code": -1}

            try:
                reads = [proc.stdout.fileno(), proc.stderr.fileno()]
                r, _, _ = select.select(reads, [], [], 0.1)
            except Exception:
                break

            for fd in r:
                if fd == proc.stdout.fileno():
                    line = proc.stdout.readline()
                    if line:
                        stdout_lines.append(line)
                        if stream_q is not None:
                            stream_q.put(("stdout", line.rstrip()))
                elif fd == proc.stderr.fileno():
                    line = proc.stderr.readline()
                    if line:
                        stderr_lines.append(line)
                        if stream_q is not None:
                            stream_q.put(("stderr", line.rstrip()))

            if proc.poll() is not None:
                for line in proc.stdout:
                    stdout_lines.append(line)
                    if stream_q is not None:
                        stream_q.put(("stdout", line.rstrip()))
                for line in proc.stderr:
                    stderr_lines.append(line)
                    if stream_q is not None:
                        stream_q.put(("stderr", line.rstrip()))
                break

        if stream_q is not None:
            stream_q.put(None)

        return {
            "success": proc.returncode == 0,
            "stdout": "".join(stdout_lines),
            "stderr": "".join(stderr_lines),
            "exit_code": proc.returncode if proc.returncode is not None else -1,
        }
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "exit_code": -1}


# Commands that require a graphical display (not available in cloud sandbox)
# These would hang forever if allowed to run — intercept and provide helpful error
_GUI_COMMANDS = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "firefox", "firefox-esr", "epiphany", "midori", "opera", "brave-browser",
    "xdg-open", "xdg-launch", "xdg-email", "xdg-settings",
    "gnome-open", "kde-open", "gvfs-open",
    "xterm", "gnome-terminal", "konsole", "xfce4-terminal",
    "x-www-browser", "sensible-browser",
    "display", "eog", "feh", "sxiv",        # image viewers
    "vlc", "mpv", "mplayer", "totem",       # media players
    "evince", "okular", "zathura",           # document viewers
    "gedit", "mousepad", "kate", "kwrite",  # GUI text editors
    "gimp", "inkscape", "blender",           # GUI tools
    "startx", "xinit", "Xorg", "Xvfb",
]

def _is_gui_command(command: str) -> Optional[str]:
    """
    Check if the command is a GUI/display-dependent program that cannot run
    in a headless cloud sandbox. Returns the detected command name if GUI, else None.
    """
    import shlex
    try:
        parts = shlex.split(command.strip())
    except Exception:
        parts = command.strip().split()
    if not parts:
        return None
    # Check base command name (without path)
    base = os.path.basename(parts[0]).lower()
    for gui_cmd in _GUI_COMMANDS:
        if base == gui_cmd or base.startswith(gui_cmd + " "):
            return base
    # Also intercept "env VAR=val google-chrome ..." patterns
    for part in parts:
        base_part = os.path.basename(part).lower()
        for gui_cmd in _GUI_COMMANDS:
            if base_part == gui_cmd:
                return base_part
    return None


def _sync_e2b_output_file(file_path: str) -> str:
    """
    Transfer a file from E2B sandbox to local server and register it for download.
    Returns download_url string, or '' if failed.
    """
    try:
        import urllib.parse, shutil, hashlib, time as _time
        from server.agent.tools.e2b_sandbox import read_file_bytes

        data = read_file_bytes(file_path)
        if not data:
            return ""

        session_id = os.environ.get("DZECK_SESSION_ID", "")
        if session_id:
            local_dir = f"/tmp/dzeck_files/{session_id}"
        else:
            local_dir = "/tmp/dzeck_files"
        os.makedirs(local_dir, exist_ok=True)

        filename = os.path.basename(file_path)
        dest = os.path.join(local_dir, filename)
        if os.path.exists(dest):
            base, ext = os.path.splitext(filename)
            tag = hashlib.md5(str(_time.time()).encode()).hexdigest()[:6]
            filename = f"{base}_{tag}{ext}"
            dest = os.path.join(local_dir, filename)

        with open(dest, "wb") as f:
            f.write(data)

        encoded_path = urllib.parse.quote(dest, safe="")
        encoded_name = urllib.parse.quote(filename, safe="")
        return f"/api/files/download?path={encoded_path}&name={encoded_name}"
    except Exception as e:
        return ""


def _extract_output_paths_from_command(command: str) -> list:
    """Scan a shell command for output file paths in /home/user/dzeck-ai/output/."""
    import re
    OUTPUT_DIR = "/home/user/dzeck-ai/output/"
    pattern = r"(/home/user/dzeck-ai/output/[\w.\-/]+)"
    paths = re.findall(pattern, command)
    unique = []
    seen = set()
    for p in paths:
        p = p.rstrip("/,;\"'")
        if p not in seen and "." in os.path.basename(p):
            unique.append(p)
            seen.add(p)
    return unique


def shell_exec(command: str, exec_dir: str = "/home/user/dzeck-ai", id: str = "default") -> ToolResult:
    """Execute a shell command. Uses E2B cloud sandbox when available, else local."""

    # Intercept GUI commands early — they would hang forever in a headless environment
    gui_detected = _is_gui_command(command)
    if gui_detected:
        msg = (
            f"[Shell] Command '{gui_detected}' requires a graphical display (GUI) which is "
            f"not available in the cloud sandbox.\n\n"
            f"For web browsing, use the 'web_browse' tool instead of launching a browser via shell.\n"
            f"Example: web_browse(url='https://www.google.com') to navigate to Google.\n\n"
            f"For opening files, use 'file_read' tool to read file contents directly.\n"
            f"For images/screenshots, use the browser tool's built-in screenshot capability."
        )
        return ToolResult(
            success=False,
            message=msg,
            data={"stdout": "", "stderr": msg, "return_code": 1, "command": command,
                  "id": id, "error": "gui_not_available"},
        )

    if E2B_ENABLED:
        res = _run_e2b(command, exec_dir=exec_dir)
    else:
        res = _run_local(command, exec_dir=exec_dir)

    stdout = res.get("stdout", "")
    stderr = res.get("stderr", "")
    exit_code = res.get("exit_code", -1)

    max_chars = 8000
    if len(stdout) > max_chars:
        stdout = stdout[:max_chars] + "\n[Output truncated...]"
    if len(stderr) > max_chars:
        stderr = stderr[:max_chars] + "\n[Error output truncated...]"

    combined = ""
    if stdout.strip():
        combined += "stdout:\n{}".format(stdout)
    if stderr.strip():
        combined += "\nstderr:\n{}".format(stderr)
    combined += "\nreturn_code: {}".format(exit_code)

    sess = _get_or_create_session(id)
    sess["output"] = combined
    sess["return_code"] = exit_code
    sess["command"] = command

    backend = "E2B" if E2B_ENABLED else "local"

    # Auto-sync output files from E2B to local server for download
    synced_files = []
    if E2B_ENABLED and res.get("success", False):
        output_paths = _extract_output_paths_from_command(command)
        for path in output_paths:
            dl_url = _sync_e2b_output_file(path)
            if dl_url:
                synced_files.append({
                    "path": path,
                    "filename": os.path.basename(path),
                    "download_url": dl_url,
                })
                combined += f"\n📎 File siap didownload: {os.path.basename(path)}"

    result_data = {
        "stdout": stdout,
        "stderr": stderr,
        "return_code": exit_code,
        "command": command,
        "id": id,
        "backend": backend,
    }
    if synced_files:
        result_data["synced_files"] = synced_files
        result_data["download_url"] = synced_files[0]["download_url"]
        result_data["filename"] = synced_files[0]["filename"]

    return ToolResult(
        success=res.get("success", False),
        message=combined,
        data=result_data,
    )


def shell_view(id: str = "default") -> ToolResult:
    """View the current output/status of a shell session."""
    session = _get_session(id)
    if not session:
        available = []
        with _sessions_lock:
            available = list(_shell_sessions.keys())
        return ToolResult(
            success=True,
            message="Shell session '{}' tidak ditemukan (sudah selesai atau belum dimulai). Session aktif: {}".format(
                id, available or ["(tidak ada)"]),
            data={"id": id, "found": False, "available_sessions": available},
        )
    output = session.get("output", "(belum ada output)")
    return ToolResult(
        success=True,
        message="Session '{}' (perintah: {})\n\n{}".format(id, session.get("command", ""), output),
        data={
            "id": id,
            "command": session.get("command", ""),
            "output": output,
            "return_code": session.get("return_code"),
            "found": True,
        },
    )


def shell_wait(id: str = "default", seconds: int = 5) -> ToolResult:
    """Wait N seconds then show session status. Always returns success=True."""
    seconds = max(1, min(int(seconds) if seconds else 5, 120))
    time.sleep(min(seconds, 3))
    return shell_view(id)


def shell_write_to_process(id: str, input: str, press_enter: bool = True) -> ToolResult:
    """Send input to an existing session by re-running with piped input."""
    session = _get_session(id)
    if not session:
        return ToolResult(
            success=True,
            message="Session '{}' tidak ditemukan.".format(id),
            data={"id": id, "found": False, "input": input},
        )
    last_command = session.get("command", "")
    if last_command:
        stdin_data = (input + "\n") if press_enter else input
        combined_cmd = "echo '{}' | {}".format(stdin_data.strip(), last_command)
        if E2B_ENABLED:
            res = _run_e2b(combined_cmd)
        else:
            res = _run_local(combined_cmd)
        out = (res.get("stdout") or "") + (res.get("stderr") or "")
        session["output"] = out
        return ToolResult(
            success=res.get("success", False),
            message="Input '{}' dikirim. Output: {}".format(input, out[:500]),
            data={"id": id, "input": input, "output": out},
        )
    return ToolResult(
        success=True,
        message="Session '{}' tidak memiliki command aktif.".format(id),
        data={"id": id, "found": True, "active": False},
    )


def shell_kill_process(id: str = "default") -> ToolResult:
    """Remove/terminate a shell session."""
    with _sessions_lock:
        session = _shell_sessions.pop(id, None)
    if not session:
        return ToolResult(
            success=True,
            message="Session '{}' tidak ada atau sudah dihentikan.".format(id),
            data={"id": id, "found": False},
        )
    return ToolResult(
        success=True,
        message="Session '{}' berhasil dihentikan.".format(id),
        data={"id": id, "found": True},
    )


class ShellTool(BaseTool):
    """Shell tool class - routes to E2B cloud sandbox."""

    name: str = "shell"

    def __init__(self) -> None:
        super().__init__()

    @tool(
        name="shell_exec",
        description=(
            "Execute commands in a specified shell session via E2B cloud sandbox. "
            "Use for: running code/scripts, installing packages, file management, "
            "starting services, checking system status. "
            "Commands run in an isolated cloud environment."
        ),
        parameters={
            "id": {"type": "string", "description": "Unique identifier of the target shell session (e.g. 'main', 'build', 'test')"},
            "exec_dir": {"type": "string", "description": "Working directory for command execution. Default: /home/user/dzeck-ai"},
            "command": {"type": "string", "description": "Shell command to execute (bash syntax supported)"},
        },
        required=["id", "exec_dir", "command"],
    )
    def _shell_exec(self, id: str, exec_dir: str, command: str) -> ToolResult:
        return shell_exec(command=command, exec_dir=exec_dir, id=id)

    @tool(
        name="shell_view",
        description="View the content of a specified shell session.",
        parameters={"id": {"type": "string", "description": "Unique identifier of the target shell session"}},
        required=["id"],
    )
    def _shell_view(self, id: str) -> ToolResult:
        return shell_view(id=id)

    @tool(
        name="shell_wait",
        description="Wait N seconds then show session status.",
        parameters={
            "id": {"type": "string", "description": "Unique identifier of the target shell session"},
            "seconds": {"type": "integer", "description": "Seconds to wait (1-120, default 5)"},
        },
        required=["id"],
    )
    def _shell_wait(self, id: str, seconds: Optional[int] = None) -> ToolResult:
        return shell_wait(id=id, seconds=seconds or 5)

    @tool(
        name="shell_write_to_process",
        description="Send input to a running process in a shell session.",
        parameters={
            "id": {"type": "string", "description": "Unique identifier of the target shell session"},
            "input": {"type": "string", "description": "Input content to send"},
            "press_enter": {"type": "boolean", "description": "Whether to press Enter after input (default true)"},
        },
        required=["id", "input", "press_enter"],
    )
    def _shell_write_to_process(self, id: str, input: str, press_enter: bool = True) -> ToolResult:
        return shell_write_to_process(id=id, input=input, press_enter=press_enter)

    @tool(
        name="shell_kill_process",
        description="Terminate a shell session.",
        parameters={"id": {"type": "string", "description": "Unique identifier of the target shell session"}},
        required=["id"],
    )
    def _shell_kill_process(self, id: str) -> ToolResult:
        return shell_kill_process(id=id)
