"""
E2B Sandbox Manager for Dzeck AI Agent.
Provides a persistent, isolated cloud sandbox for shell and browser automation.
All tool calls (shell, browser) are routed through this secure E2B environment.
Uses E2B v2 API: Sandbox.create() pattern.
"""
import os
import json
import logging
import threading
import base64
from typing import Optional, Any, Dict

logger = logging.getLogger(__name__)

E2B_API_KEY = os.environ.get("E2B_API_KEY", "")

_sandbox_lock = threading.Lock()
_sandbox: Optional[Any] = None


def get_sandbox() -> Optional[Any]:
    """Get or create the E2B sandbox singleton."""
    global _sandbox
    if _sandbox is not None:
        try:
            _sandbox.commands.run("echo ok", timeout=5)
            return _sandbox
        except Exception:
            logger.warning("[E2B] Sandbox appears dead, recreating...")
            _sandbox = None

    with _sandbox_lock:
        if _sandbox is None:
            _sandbox = _create_sandbox()
    return _sandbox


WORKSPACE_DIR = "/home/user/dzeck-ai"
OUTPUT_DIR = "/home/user/dzeck-ai/output"


def _create_sandbox() -> Optional[Any]:
    """Create a new E2B sandbox instance using Sandbox.create()."""
    if not E2B_API_KEY:
        logger.error("[E2B] E2B_API_KEY not set. Cannot create sandbox.")
        return None
    try:
        from e2b import Sandbox
        logger.info("[E2B] Creating new sandbox...")
        sb = Sandbox.create(api_key=E2B_API_KEY, timeout=600)
        logger.info("[E2B] Sandbox ready (id=%s, timeout=600s). Setting up workspace...", sb.sandbox_id)
        sb.commands.run(
            f"mkdir -p {WORKSPACE_DIR} {OUTPUT_DIR} && cd {WORKSPACE_DIR}",
            timeout=10
        )
        sb.commands.run(
            "pip install reportlab python-docx openpyxl Pillow 2>/dev/null || true",
            timeout=60
        )
        logger.info("[E2B] Workspace %s created with packages (id=%s)", WORKSPACE_DIR, sb.sandbox_id)
        return sb
    except Exception as e:
        logger.error("[E2B] Failed to create sandbox: %s", e)
        return None


def reset_sandbox() -> Optional[Any]:
    """Force-recreate the sandbox."""
    global _sandbox
    with _sandbox_lock:
        if _sandbox:
            try:
                _sandbox.kill()
            except Exception:
                pass
        _sandbox = _create_sandbox()
    return _sandbox


def keepalive() -> bool:
    """Send a keepalive ping to the sandbox to extend its lifetime."""
    sb = get_sandbox()
    if sb is None:
        return False
    try:
        sb.set_timeout(600)
        return True
    except Exception:
        try:
            sb.commands.run("echo ok", timeout=5)
            return True
        except Exception:
            return False


def run_command(command: str, workdir: str = "/home/user/dzeck-ai", timeout: int = 90) -> Dict[str, Any]:
    """Run a shell command in the E2B sandbox and return result dict."""
    sb = get_sandbox()
    if sb is None:
        return {
            "success": False,
            "stdout": "",
            "stderr": "E2B sandbox not available. Check E2B_API_KEY.",
            "exit_code": -1,
        }
    try:
        result = sb.commands.run(command, cwd=workdir, timeout=timeout)
        return {
            "success": (result.exit_code == 0),
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": result.exit_code,
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
        }


def run_browser_script(script: str, timeout: int = 90) -> Dict[str, Any]:
    """Run a Playwright Python script inside E2B sandbox and return JSON output."""
    sb = get_sandbox()
    if sb is None:
        return {"success": False, "error": "E2B sandbox not available."}
    try:
        script_path = "/tmp/dzeck_browser_script.py"
        sb.files.write(script_path, script)
        result = sb.commands.run(f"python3 {script_path}", timeout=timeout)
        stdout = result.stdout or ""
        if result.exit_code != 0:
            err = result.stderr or result.stdout or "Script failed"
            return {"success": False, "error": err}
        try:
            return json.loads(stdout)
        except Exception:
            return {"success": True, "output": stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_file(path: str) -> Optional[str]:
    """Read a file from the E2B sandbox."""
    sb = get_sandbox()
    if sb is None:
        return None
    try:
        return sb.files.read(path)
    except Exception:
        return None


def write_file(path: str, content: str, append: bool = False) -> bool:
    """Write a file to the E2B sandbox. If append=True, appends to existing content."""
    sb = get_sandbox()
    if sb is None:
        return False
    try:
        import shlex
        parent = "/".join(path.split("/")[:-1])
        if parent:
            sb.commands.run(f"mkdir -p {shlex.quote(parent)}", timeout=5)
        if append:
            existing = ""
            try:
                existing = sb.files.read(path) or ""
            except Exception:
                pass
            content = existing + content
        sb.files.write(path, content)
        return True
    except Exception as e:
        logger.warning("[E2B] Failed to write file %s: %s", path, e)
        return False


def sync_file_to_sandbox(local_path: str, sandbox_path: str = "") -> bool:
    """Copy a local file into the E2B sandbox (binary-safe via base64)."""
    if not E2B_API_KEY:
        return False
    sb = get_sandbox()
    if sb is None:
        return False
    try:
        import os, shlex
        if not os.path.isfile(local_path):
            return False
        with open(local_path, "rb") as f:
            raw = f.read()
        if not sandbox_path:
            sandbox_path = os.path.join(WORKSPACE_DIR, os.path.basename(local_path))
        parent = "/".join(sandbox_path.split("/")[:-1])
        if parent:
            sb.commands.run(f"mkdir -p {shlex.quote(parent)}", timeout=5)
        b64 = base64.b64encode(raw).decode("ascii")
        sb.commands.run(
            f"echo {shlex.quote(b64)} | base64 -d > {shlex.quote(sandbox_path)}",
            timeout=30
        )
        logger.info("[E2B] Synced local %s → sandbox %s (binary-safe)", local_path, sandbox_path)
        return True
    except Exception as e:
        logger.warning("[E2B] Failed to sync file to sandbox: %s", e)
        return False


def sync_file_from_sandbox(sandbox_path: str, local_path: str = "") -> Optional[str]:
    """Copy a file from E2B sandbox to local filesystem (binary-safe via base64). Returns local path or None."""
    if not E2B_API_KEY:
        return None
    sb = get_sandbox()
    if sb is None:
        return None
    try:
        import os, shlex
        if not local_path:
            _sess = os.environ.get("DZECK_SESSION_ID", "")
            _base = f"/tmp/dzeck_files/{_sess}" if _sess else "/tmp/dzeck_files"
            local_path = os.path.join(_base, os.path.basename(sandbox_path))
        parent = os.path.dirname(local_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        result = sb.commands.run(
            f"base64 -w0 {shlex.quote(sandbox_path)}",
            timeout=30
        )
        if result.exit_code != 0 or not result.stdout:
            content = sb.files.read(sandbox_path)
            if content is None:
                return None
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            raw = base64.b64decode(result.stdout.strip())
            with open(local_path, "wb") as f:
                f.write(raw)
        logger.info("[E2B] Synced sandbox %s → local %s (binary-safe)", sandbox_path, local_path)
        return local_path
    except Exception as e:
        logger.warning("[E2B] Failed to sync file from sandbox: %s", e)
        return None


def list_workspace_files() -> list:
    """List files in the E2B workspace directory."""
    sb = get_sandbox()
    if sb is None:
        return []
    try:
        result = sb.commands.run(f"find {WORKSPACE_DIR} -type f -maxdepth 3 2>/dev/null | head -50", timeout=10)
        if result.stdout:
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return []
    except Exception:
        return []


def list_output_files() -> list:
    """List files in the E2B output directory (deliverables only)."""
    sb = get_sandbox()
    if sb is None:
        return []
    try:
        result = sb.commands.run(f"find {OUTPUT_DIR} -type f -maxdepth 3 2>/dev/null | head -50", timeout=10)
        if result.stdout:
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return []
    except Exception:
        return []
