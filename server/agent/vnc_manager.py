"""
VNC Manager for Dzeck AI.
Starts Xvfb virtual display + x11vnc server + websockify proxy.
Provides real-time VNC streaming to the web frontend via noVNC.
"""
import os
import subprocess
import threading
import time
import logging
import signal
import atexit

logger = logging.getLogger(__name__)

DISPLAY_NUM = ":10"
VNC_PORT = 5910
WS_PORT = 6081
SCREEN_RES = "1280x720x24"

_procs: list = []
_started = False
_lock = threading.Lock()


def _kill_proc(proc):
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _cleanup():
    for p in _procs:
        _kill_proc(p)


atexit.register(_cleanup)


def _find_bin(name: str) -> str:
    import shutil
    path = shutil.which(name)
    if path:
        return path
    nix_paths = [
        f"/nix/store",
    ]
    for base in nix_paths:
        try:
            import glob as _glob
            matches = _glob.glob(f"{base}/*/{name}")
            if matches:
                return matches[0]
        except Exception:
            pass
    return name


def start_vnc() -> bool:
    global _started
    with _lock:
        if _started:
            return True
        try:
            env = os.environ.copy()

            xvfb_bin = _find_bin("Xvfb")
            x11vnc_bin = _find_bin("x11vnc")

            logger.info(f"[VNC] Starting Xvfb on display {DISPLAY_NUM} ({SCREEN_RES})...")
            xvfb_proc = subprocess.Popen(
                [xvfb_bin, DISPLAY_NUM, "-screen", "0", SCREEN_RES, "-ac", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env,
            )
            _procs.append(xvfb_proc)
            time.sleep(1.5)

            if xvfb_proc.poll() is not None:
                logger.error("[VNC] Xvfb failed to start.")
                return False

            display_env = dict(env, DISPLAY=DISPLAY_NUM)

            logger.info(f"[VNC] Starting x11vnc on port {VNC_PORT}...")
            x11vnc_proc = subprocess.Popen(
                [
                    x11vnc_bin,
                    "-display", DISPLAY_NUM,
                    "-forever",
                    "-shared",
                    "-nopw",
                    "-rfbport", str(VNC_PORT),
                    "-noxdamage",
                    "-noxfixes",
                    "-nocursorshape",
                    "-nocursor",
                    "-quiet",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=display_env,
            )
            _procs.append(x11vnc_proc)
            time.sleep(1.5)

            if x11vnc_proc.poll() is not None:
                logger.error("[VNC] x11vnc failed to start.")
                return False

            logger.info(f"[VNC] Starting websockify on port {WS_PORT} -> VNC port {VNC_PORT}...")
            ws_proc = subprocess.Popen(
                ["python3", "-m", "websockify", str(WS_PORT), f"127.0.0.1:{VNC_PORT}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env,
            )
            _procs.append(ws_proc)
            time.sleep(1.0)

            if ws_proc.poll() is not None:
                logger.error("[VNC] websockify failed to start.")
                return False

            _started = True
            logger.info(f"[VNC] VNC stack ready: DISPLAY={DISPLAY_NUM}, VNC={VNC_PORT}, WS={WS_PORT}")

            _draw_idle_screen()
            return True

        except Exception as e:
            logger.error(f"[VNC] Failed to start VNC stack: {e}")
            return False


def _draw_idle_screen():
    """Draw a simple background on the virtual display so it's not black."""
    try:
        env = dict(os.environ, DISPLAY=DISPLAY_NUM)
        xsetroot = _find_bin("xsetroot")
        subprocess.Popen(
            [xsetroot, "-solid", "#1a1a2e"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).wait(timeout=3)
    except Exception:
        pass


def is_running() -> bool:
    return _started and all(p.poll() is None for p in _procs if p is not None)


def get_display() -> str:
    return DISPLAY_NUM if _started else ""


def get_ws_port() -> int:
    return WS_PORT
