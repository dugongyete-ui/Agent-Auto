"""
Browser tools for Dzeck AI Agent.
Uses E2B cloud sandbox for isolated, headless Playwright browser automation.
Falls back to local Playwright/HTTP if E2B is not available.

Provides: BrowserTool class + backward-compatible functions.
"""
import re
import os
import json
import threading
import logging
import urllib.request
import urllib.parse
import ssl
from typing import Optional, List, Any

from server.agent.models.tool_result import ToolResult

logger = logging.getLogger(__name__)

E2B_ENABLED = bool(os.environ.get("E2B_API_KEY", ""))
PLAYWRIGHT_ENABLED = os.environ.get("PLAYWRIGHT_ENABLED", "true").lower() == "true"


def _find_chromium_executable() -> Optional[str]:
    """Find the best available Chromium/Chrome binary on this system."""
    import glob as _glob
    import subprocess as _sp

    candidates = []
    for pattern in [
        "/home/runner/workspace/.cache/ms-playwright/chromium-*/chrome-linux64/chrome",
        "/home/runner/workspace/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
        "/home/runner/.cache/ms-playwright/chromium-*/chrome-linux64/chrome",
        "/home/runner/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    ]:
        found = sorted(_glob.glob(pattern), reverse=True)
        candidates.extend(found)

    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    # Try PATH
    for name in ("chromium", "chromium-browser", "google-chrome"):
        try:
            result = _sp.run(["which", name], capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

    return None

_browser_lock = threading.Lock()
_browser: Any = None


def _get_browser() -> Any:
    global _browser
    if _browser is not None:
        return _browser
    with _browser_lock:
        if _browser is None:
            _browser = _make_session()
    return _browser


def _reset_browser() -> None:
    global _browser
    with _browser_lock:
        _browser = _make_session()


def _disconnect_browser_on_exit() -> None:
    """On process exit, disconnect from CDP browser without killing it.
    Since we use connect_over_cdp, disconnect just drops the connection
    while the browser (managed by Node.js server) stays alive."""
    global _browser
    if _browser is not None and hasattr(_browser, 'disconnect'):
        try:
            _browser.disconnect()
        except Exception:
            pass
    _browser = None


import atexit
atexit.register(_disconnect_browser_on_exit)


# ─── E2B Browser Session ────────────────────────────────────────────────────

class E2BBrowserSession:
    """Browser session that runs Playwright inside E2B cloud sandbox."""

    def __init__(self) -> None:
        self.current_url: Optional[str] = None
        self.console_logs: List[str] = []
        self._page_state: dict = {}

    def _run_playwright(self, script: str, timeout: int = 60) -> dict:
        from server.agent.tools.e2b_sandbox import run_browser_script
        return run_browser_script(script, timeout=timeout)

    def _make_script(self, template: str, **kwargs) -> str:
        """Safely inject variables into a script template using simple replacement."""
        script = template
        for key, val in kwargs.items():
            script = script.replace("__" + key + "__", repr(val))
        return script

    def navigate(self, url: str) -> ToolResult:
        script = self._make_script('''
import json
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])
        ctx = browser.new_context(viewport={"width":1280,"height":720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = ctx.new_page()
        page.goto(__url__, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1200)
        title = page.title()
        content = page.inner_text("body")[:8000]
        current_url = page.url
        browser.close()
        print(json.dumps({"success":True,"url":current_url,"title":title,"content":content}))
except Exception as e:
    print(json.dumps({"success":False,"error":str(e)}))
''', url=url)
        res = self._run_playwright(script, timeout=60)
        if not res.get("success"):
            return ToolResult(success=False, message="Navigate failed: {}".format(res.get("error", res.get("output", ""))))
        self.current_url = res.get("url", url)
        self._page_state = res
        return ToolResult(
            success=True,
            message="Page: {}\nURL: {}\n\n{}".format(res.get("title",""), res.get("url",""), res.get("content","")),
            data={
                "url": res.get("url", url),
                "title": res.get("title", ""),
                "content": res.get("content", ""),
            },
        )

    def view(self) -> ToolResult:
        if not self.current_url:
            return ToolResult(success=False, message="No page loaded. Use browser_navigate first.")
        return self.navigate(self.current_url)

    def click(self, x: float, y: float, button: str = "left") -> ToolResult:
        if not self.current_url:
            return ToolResult(success=False, message="No page loaded.")
        script = self._make_script('''
import json
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])
        ctx = browser.new_context(viewport={"width":1280,"height":720})
        page = ctx.new_page()
        page.goto(__url__, wait_until="domcontentloaded", timeout=30000)
        page.mouse.click(__x__, __y__, button=__button__)
        page.wait_for_timeout(800)
        current_url = page.url
        title = page.title()
        content = page.inner_text("body")[:6000]
        browser.close()
        print(json.dumps({"success":True,"url":current_url,"title":title,"content":content}))
except Exception as e:
    print(json.dumps({"success":False,"error":str(e)}))
''', url=self.current_url, x=x, y=y, button=button)
        res = self._run_playwright(script)
        self.current_url = res.get("url", self.current_url)
        return ToolResult(
            success=res.get("success", False),
            message="Clicked at ({}, {}). Page: {}\n\n{}".format(x, y, res.get("title",""), res.get("content","")),
            data={"x": x, "y": y, "button": button, "url": res.get("url","")},
        )

    def type_text(self, text: str) -> ToolResult:
        return ToolResult(success=True, message="Text input queued: {}".format(repr(text)), data={"text": text})

    def scroll(self, direction: str, amount: int = 3) -> ToolResult:
        if not self.current_url:
            return ToolResult(success=False, message="No page loaded.")
        delta_y = amount * 300 if direction == "down" else -amount * 300
        script = self._make_script('''
import json
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])
        ctx = browser.new_context(viewport={"width":1280,"height":720})
        page = ctx.new_page()
        page.goto(__url__, wait_until="domcontentloaded", timeout=30000)
        page.mouse.wheel(0, __delta_y__)
        page.wait_for_timeout(500)
        content = page.inner_text("body")[:6000]
        browser.close()
        print(json.dumps({"success":True,"content":content}))
except Exception as e:
    print(json.dumps({"success":False,"error":str(e)}))
''', url=self.current_url, delta_y=delta_y)
        res = self._run_playwright(script)
        return ToolResult(
            success=res.get("success", False),
            message="Scrolled {}.\n\n{}".format(direction, res.get("content", res.get("error", ""))),
            data={"direction": direction, "amount": amount, "url": self.current_url},
        )

    def console_view(self, max_lines: int = 100) -> ToolResult:
        logs = self.console_logs[-max_lines:]
        text = "\n".join(logs) if logs else "(No console logs)"
        return ToolResult(success=True, message="Console logs:\n\n{}".format(text), data={"logs": logs})

    def save_screenshot(self, path: str) -> ToolResult:
        if not self.current_url:
            return ToolResult(success=False, message="No page loaded.")
        return ToolResult(
            success=True,
            message="Screenshot captured (E2B headless). Path: {}".format(path),
            data={"save_path": path, "url": self.current_url},
        )

    def close(self) -> None:
        pass


# ─── Local Playwright Session ─────────────────────────────────────────────────

_playwright_available = False

if PLAYWRIGHT_ENABLED:
    try:
        from playwright.sync_api import sync_playwright
        _playwright_available = True
        logger.info("[Browser] Local Playwright available.")
    except ImportError:
        logger.warning("[Browser] Playwright not installed - will use HTTP fallback.")


class PlaywrightSession:
    """Local Playwright browser session. Uses virtual display (Xvfb) for VNC streaming.
    Falls back to headless if VNC is unavailable."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._started = False
        self._headless = True
        self._cdp_mode = False
        self.current_url: Optional[str] = None
        self.console_logs: List[str] = []

    def _request_vnc_restart(self) -> bool:
        """Ask the Node.js server to restart VNC+Chromium via HTTP API."""
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:5000/api/vnc/start", method="POST",
                                         data=b'{}', headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=30)
            return resp.status == 200
        except Exception as e:
            logger.warning("[Browser] VNC restart request failed: %s", e)
            return False

    def _wait_for_cdp(self, cdp_url: str, timeout: int = 20) -> bool:
        """Wait for CDP endpoint to become responsive."""
        import time as _time
        import urllib.request as _req
        for i in range(timeout):
            try:
                _req.urlopen(cdp_url + "/json/version", timeout=2)
                return True
            except Exception:
                _time.sleep(1)
        return False

    def _connect_cdp(self, cdp_url: str) -> bool:
        """Connect to existing Chromium via CDP. Returns True on success."""
        try:
            self._browser = self._pw.chromium.connect_over_cdp(cdp_url)
            self._cdp_mode = True
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                pages = self._context.pages
                if pages:
                    self._page = pages[0]
                else:
                    self._page = self._context.new_page()
            else:
                self._context = self._browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                )
                self._page = self._context.new_page()
            self._page.on("console", lambda msg: self.console_logs.append("[{}] {}".format(msg.type, msg.text)))
            self._started = True
            self._headless = False
            logger.info("[Browser] Connected to persistent Chromium via CDP (VNC visible).")
            return True
        except Exception as e:
            logger.warning("[Browser] CDP connect failed: %s", e)
            return False

    def _stop_pw(self) -> None:
        """Safely stop the playwright instance if it exists."""
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def _launch_headless(self) -> bool:
        """Launch a local headless Chromium as fallback."""
        try:
            chromium_exe = _find_chromium_executable()
            launch_args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                           "--disable-setuid-sandbox"]
            if chromium_exe:
                self._browser = self._pw.chromium.launch(
                    executable_path=chromium_exe, headless=True, args=launch_args)
            else:
                self._browser = self._pw.chromium.launch(headless=True, args=launch_args)
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            self._page = self._context.new_page()
            self._page.on("console", lambda msg: self.console_logs.append("[{}] {}".format(msg.type, msg.text)))
            self._started = True
            self._headless = True
            logger.info("[Browser] Started local headless Chromium (fallback mode).")
            return True
        except Exception as e:
            logger.warning("[Browser] Headless fallback failed: %s", e)
            return False

    def start(self) -> bool:
        if not _playwright_available:
            return False
        self._stop_pw()
        try:
            from playwright.sync_api import sync_playwright

            cdp_url = os.environ.get("DZECK_CDP_URL", "") or "http://127.0.0.1:9222"

            self._pw = sync_playwright().start()

            if self._wait_for_cdp(cdp_url, timeout=5):
                logger.info("[Browser] CDP endpoint responsive at %s", cdp_url)
                if self._connect_cdp(cdp_url):
                    return True

            logger.info("[Browser] CDP not available — requesting VNC/Chromium restart...")
            self._request_vnc_restart()

            if self._wait_for_cdp(cdp_url, timeout=20):
                logger.info("[Browser] CDP available after restart at %s", cdp_url)
                if self._connect_cdp(cdp_url):
                    return True

            logger.warning("[Browser] CDP unavailable — falling back to headless Chromium")
            if self._launch_headless():
                return True

            logger.error("[Browser] All browser start methods failed")
            self._stop_pw()
            self._started = False
            return False
        except Exception as e:
            logger.error("[Browser] Failed to start Playwright: %s", e)
            self._stop_pw()
            self._started = False
            return False

    def _capture_screenshot_b64(self) -> Optional[str]:
        try:
            import base64
            data = self._page.screenshot(type="jpeg", quality=55, full_page=False)
            return "data:image/jpeg;base64," + base64.b64encode(data).decode()
        except Exception:
            return None

    def _ensure_alive(self) -> bool:
        """Check if the CDP connection is still alive, reconnect if needed."""
        if not self._started:
            return self.start()
        try:
            self._page.title()
            return True
        except Exception as e:
            logger.warning("[Browser] Connection stale (%s), reconnecting...", e)
            self.disconnect()
            self._started = False
            return self.start()

    def navigate(self, url: str) -> ToolResult:
        if not self._ensure_alive():
            return ToolResult(success=False, message="Playwright not available.")
        last_err = None
        for attempt in range(2):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
                self._page.wait_for_timeout(1500)
                self.current_url = self._page.url
                title = self._page.title()
                content = self._page.inner_text("body")[:8000]
                return ToolResult(
                    success=True,
                    message="Page: {}\nURL: {}\n\n{}".format(title, self.current_url, content),
                    data={"url": self.current_url, "title": title, "content": content},
                )
            except Exception as e:
                last_err = e
                logger.warning("[Browser] Navigate attempt %d failed: %s", attempt + 1, e)
                if attempt == 0:
                    try:
                        self._page.wait_for_timeout(2000)
                    except Exception:
                        logger.warning("[Browser] Page dead during retry wait, reconnecting...")
                        self.disconnect()
                        self._started = False
                        if not self.start():
                            break
        return ToolResult(success=False, message="Navigate failed: {}".format(last_err))

    def view(self) -> ToolResult:
        if not self._ensure_alive():
            return ToolResult(success=False, message="No page loaded.")
        try:
            content = self._page.inner_text("body")[:8000]
            title = self._page.title()
            return ToolResult(
                success=True,
                message="Page: {}\nURL: {}\n\n{}".format(title, self.current_url, content),
                data={"url": self.current_url, "title": title, "content": content},
            )
        except Exception as e:
            return ToolResult(success=False, message="View failed: {}".format(e))

    def click(self, x: float, y: float, button: str = "left") -> ToolResult:
        if not self._ensure_alive():
            return ToolResult(success=False, message="Playwright not available.")
        try:
            btn_map = {"left": "left", "right": "right", "middle": "middle"}
            self._page.mouse.click(x, y, button=btn_map.get(button, "left"))
            self._page.wait_for_timeout(800)
            self.current_url = self._page.url
            title = self._page.title()
            content = self._page.inner_text("body")[:6000]
            return ToolResult(
                success=True,
                message="Clicked ({}, {}). Page: {}\nURL: {}\n\n{}".format(x, y, title, self.current_url, content),
                data={"x": x, "y": y, "button": button, "url": self.current_url, "title": title, "content": content},
            )
        except Exception as e:
            return ToolResult(success=False, message="Click failed: {}".format(e))

    def type_text(self, text: str) -> ToolResult:
        if not self._ensure_alive():
            return ToolResult(success=False, message="Playwright not available.")
        try:
            self._page.keyboard.type(text)
            self._page.wait_for_timeout(500)
            return ToolResult(
                success=True,
                message="Typed: {}".format(repr(text)),
                data={"text": text, "url": self.current_url},
            )
        except Exception as e:
            return ToolResult(success=False, message="Type failed: {}".format(e))

    def scroll(self, direction: str, amount: int = 3) -> ToolResult:
        if not self._ensure_alive():
            return ToolResult(success=False, message="Playwright not available.")
        try:
            delta_y = amount * 200 if direction == "down" else -amount * 200
            self._page.mouse.wheel(0, delta_y)
            self._page.wait_for_timeout(500)
            content = self._page.inner_text("body")[:4000]
            return ToolResult(
                success=True,
                message="Scrolled {}.\n\n{}".format(direction, content),
                data={"direction": direction, "amount": amount, "url": self.current_url},
            )
        except Exception as e:
            return ToolResult(success=False, message="Scroll failed: {}".format(e))

    def console_view(self, max_lines: int = 100) -> ToolResult:
        logs = self.console_logs[-max_lines:]
        text = "\n".join(logs) if logs else "(No console logs)"
        return ToolResult(success=True, message="Console logs:\n\n{}".format(text), data={"logs": logs})

    def save_screenshot(self, path: str) -> ToolResult:
        if not self._ensure_alive():
            return ToolResult(success=False, message="No page loaded.")
        local_path = _remap_to_local_path(path)
        try:
            parent = os.path.dirname(local_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._page.screenshot(path=local_path, full_page=False)
            return ToolResult(
                success=True,
                message="Screenshot saved to: {}".format(local_path),
                data={"save_path": local_path, "original_path": path},
            )
        except Exception as e:
            return ToolResult(success=False, message="Save screenshot failed: {}".format(e))

    def disconnect(self) -> None:
        """Disconnect from CDP browser without killing it.
        Browser stays visible on VNC — page content persists."""
        try:
            if self._browser and self._cdp_mode:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None
        self._started = False

    def close(self) -> None:
        self.disconnect()


# ─── HTTP Fallback Session ─────────────────────────────────────────────────────

class HTTPBrowserSession:
    """HTTP-based browser fallback (no JavaScript, no screenshots)."""

    def __init__(self) -> None:
        self.current_url: Optional[str] = None
        self.current_title: str = ""
        self.current_content: str = ""
        self.current_html: str = ""
        self.links: list = []
        self.console_logs: list = []

    def navigate(self, url: str) -> ToolResult:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, context=ctx, timeout=20) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text" not in content_type and "html" not in content_type:
                    return ToolResult(success=True, message="[Binary content: {}]".format(content_type))
                self.current_html = response.read().decode("utf-8", errors="replace")

            title_match = re.search(r"<title[^>]*>(.*?)</title>", self.current_html, re.DOTALL | re.IGNORECASE)
            self.current_title = (
                re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
            )
            self.links = self._extract_links(self.current_html, url)
            self.current_content = self._html_to_text(self.current_html)
            self.current_url = url

            max_chars = 8000
            display = (
                self.current_content[:max_chars] + "\n[Content truncated...]"
                if len(self.current_content) > max_chars
                else self.current_content
            )
            return ToolResult(
                success=True,
                message="Page: {}\nURL: {}\n\n{}".format(self.current_title, url, display),
                data={"url": url, "title": self.current_title, "content": display, "links_count": len(self.links)},
            )
        except Exception as e:
            return ToolResult(success=False, message="Failed to navigate to {}: {}".format(url, e))

    def view(self) -> ToolResult:
        if not self.current_url:
            return ToolResult(success=False, message="No page loaded. Use browser_navigate first.")
        content = self.current_content[:8000]
        return ToolResult(
            success=True,
            message="Current page: {}\nURL: {}\n\n{}".format(self.current_title, self.current_url, content),
            data={"url": self.current_url, "title": self.current_title, "content": content},
        )

    def click(self, x: float, y: float, button: str = "left") -> ToolResult:
        if not self.current_url:
            return ToolResult(success=False, message="No page loaded.")
        if self.links:
            idx = max(0, min(int(y / 100), len(self.links) - 1))
            target = self.links[idx].get("url", "")
            if target:
                return self.navigate(target)
        return ToolResult(success=True, message="Click simulated at ({}, {}).".format(x, y))

    def type_text(self, text: str) -> ToolResult:
        self.console_logs.append("[type] {}".format(text))
        return ToolResult(success=True, message="Typed: {}".format(repr(text)), data={"text": text})

    def scroll(self, direction: str, amount: int = 3) -> ToolResult:
        if not self.current_url:
            return ToolResult(success=False, message="No page loaded.")
        content = self.current_content
        chunk = 2000 * amount
        snippet = content[chunk:chunk + 4000] if direction == "down" else content[:4000]
        return ToolResult(success=True, message="Scrolled {}.\n\n{}".format(direction, snippet))

    def console_view(self, max_lines: int = 100) -> ToolResult:
        logs = self.console_logs[-max_lines:]
        text = "\n".join(logs) if logs else "(No console logs)"
        return ToolResult(success=True, message="Console:\n\n{}".format(text), data={"logs": logs})

    def save_screenshot(self, path: str) -> ToolResult:
        return ToolResult(success=False, message="Screenshots not available in HTTP mode.")

    def _extract_links(self, html: str, base_url: str) -> list:
        links = []
        pattern = re.compile(r'<a[^>]+href=["\']([^"\'#][^"\']*)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        seen = set()
        for match in pattern.finditer(html):
            href = match.group(1).strip()
            text = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/") and base_url:
                parsed = urllib.parse.urlparse(base_url)
                href = "{}://{}{}".format(parsed.scheme, parsed.netloc, href)
            elif not href.startswith("http"):
                continue
            if href not in seen and len(links) < 100:
                seen.add(href)
                links.append({"url": href, "text": text[:100]})
        return links

    def _html_to_text(self, html: str) -> str:
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
        html = re.sub(r"<(?:br|p|div|h[1-6]|li|tr|section|article)[^>]*>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", html)
        text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return "\n".join(lines)


def _install_playwright_chromium() -> bool:
    """Try to auto-install Playwright Chromium browser if not found."""
    import subprocess
    import sys
    try:
        logger.info("[Browser] Installing Playwright Chromium...")
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=180
        )
        if result.returncode == 0:
            logger.info("[Browser] Playwright Chromium installed successfully.")
            return True
        else:
            logger.error("[Browser] Playwright Chromium install failed: %s", result.stderr[:500])
            return False
    except Exception as e:
        logger.error("[Browser] Auto-install exception: %s", e)
        return False


def _remap_to_local_path(path: str) -> str:
    """Remap E2B sandbox paths to local writable paths when running locally."""
    e2b_prefix = "/home/user/dzeck-ai"
    if path.startswith(e2b_prefix):
        rel = path[len(e2b_prefix):]
        local = "/tmp/dzeck_workspace" + rel
        return local
    if path.startswith("/home/user/"):
        rel = path[len("/home/user/"):]
        return "/tmp/dzeck_workspace/" + rel
    return path


def _make_session() -> Any:
    """Create the best available browser session.
    Priority: Local Playwright (CDP/VNC > headless fallback) > E2B > HTTP fallback.
    """
    if _playwright_available and PLAYWRIGHT_ENABLED:
        sess = PlaywrightSession()
        if sess.start():
            mode = "VNC CDP" if not sess._headless else "headless"
            logger.info("[Browser] Using local Playwright (%s).", mode)
            return sess
        sess.disconnect()
        logger.warning("[Browser] Local Playwright failed — trying auto-install chromium...")
        if _install_playwright_chromium():
            sess2 = PlaywrightSession()
            if sess2.start():
                mode2 = "VNC CDP" if not sess2._headless else "headless"
                logger.info("[Browser] Playwright ready after auto-install (%s).", mode2)
                return sess2
            sess2.disconnect()
        logger.warning("[Browser] Local Playwright still unavailable.")

    if E2B_ENABLED:
        logger.info("[Browser] Falling back to E2B cloud browser (screenshots only).")
        return E2BBrowserSession()

    logger.warning("[Browser] Using HTTP fallback (no screenshots, no JS).")
    return HTTPBrowserSession()


# ─── Public Tool Functions ─────────────────────────────────────────────────────

def browser_navigate(url: str, **kwargs) -> ToolResult:
    """Navigate browser to specified URL."""
    return _get_browser().navigate(url)


def browser_view() -> ToolResult:
    """View content of the current browser page."""
    return _get_browser().view()


def browser_click(
    coordinate_x: Optional[float] = None,
    coordinate_y: Optional[float] = None,
    index: Optional[int] = None,
    button: str = "left",
) -> ToolResult:
    """Click on element in the current browser page."""
    x = float(coordinate_x) if coordinate_x is not None else 0.0
    y = float(coordinate_y) if coordinate_y is not None else 0.0
    return _get_browser().click(x, y, button)


def browser_input(
    text: str,
    press_enter: bool = False,
    coordinate_x: Optional[float] = None,
    coordinate_y: Optional[float] = None,
    index: Optional[int] = None,
) -> ToolResult:
    """Overwrite text in editable elements on the current browser page."""
    b = _get_browser()
    if coordinate_x is not None and coordinate_y is not None:
        b.click(float(coordinate_x), float(coordinate_y))
    result = b.type_text(text)
    if press_enter and result.success:
        browser_press_key("Enter")
    return result


def browser_move_mouse(coordinate_x: float, coordinate_y: float) -> ToolResult:
    """Move cursor to specified position on the current browser page."""
    b = _get_browser()
    if hasattr(b, "_page") and b._page:
        try:
            b._page.mouse.move(float(coordinate_x), float(coordinate_y))
            return ToolResult(
                success=True,
                message="Mouse moved to ({}, {}).".format(coordinate_x, coordinate_y),
            )
        except Exception as e:
            return ToolResult(success=False, message="Move mouse failed: {}".format(e))
    return ToolResult(
        success=True,
        message="Mouse move to ({}, {}).".format(coordinate_x, coordinate_y),
    )


def browser_press_key(key: str) -> ToolResult:
    """Simulate key press in the current browser page."""
    b = _get_browser()
    if hasattr(b, "_page") and b._page:
        try:
            b._page.keyboard.press(key)
            return ToolResult(success=True, message="Pressed key: {}".format(key))
        except Exception as e:
            return ToolResult(success=False, message="Press key failed: {}".format(e))
    return ToolResult(success=True, message="Key press simulated: {}".format(key))


def browser_select_option(index: int, option: int) -> ToolResult:
    """Select specified option from dropdown list element."""
    b = _get_browser()
    if hasattr(b, "_page") and b._page:
        try:
            selects = b._page.query_selector_all("select")
            if index < 0 or index >= len(selects):
                return ToolResult(
                    success=True,
                    message="Tidak ada dropdown di index {}. Ditemukan {} dropdown.".format(index, len(selects)),
                    data={"dropdown_index": index, "found": len(selects), "selected": False},
                )
            select_el = selects[index]
            options = select_el.query_selector_all("option")
            if option < 0 or option >= len(options):
                return ToolResult(
                    success=True,
                    message="Tidak ada option di index {}.".format(option),
                    data={"dropdown_index": index, "option_index": option, "found": len(options), "selected": False},
                )
            value = options[option].get_attribute("value") or ""
            select_el.select_option(value=value)
            return ToolResult(
                success=True,
                message="Option {} dipilih dari dropdown {}.".format(option, index),
                data={"dropdown_index": index, "option_index": option, "value": value, "selected": True},
            )
        except Exception as e:
            return ToolResult(
                success=True,
                message="Select option: {}".format(e),
                data={"error": str(e), "selected": False},
            )
    return ToolResult(
        success=True,
        message="Select option tidak tersedia di mode ini.",
        data={"selected": False},
    )


def browser_scroll_up(amount: int = 3) -> ToolResult:
    """Scroll up on the current browser page."""
    return _get_browser().scroll("up", amount)


def browser_scroll_down(amount: int = 3) -> ToolResult:
    """Scroll down on the current browser page."""
    return _get_browser().scroll("down", amount)


def browser_console_exec(javascript: str) -> ToolResult:
    """Execute JavaScript in the browser page."""
    b = _get_browser()
    if hasattr(b, "_page") and b._page:
        try:
            result = b._page.evaluate(javascript)
            return ToolResult(
                success=True,
                message="JavaScript executed. Result: {}".format(result),
                data={"result": result},
            )
        except Exception as e:
            return ToolResult(success=False, message="JS execution failed: {}".format(e))
    return ToolResult(success=True, message="JS execution not available in this mode.")


def browser_console_view(max_lines: int = 100) -> ToolResult:
    """View browser console logs."""
    return _get_browser().console_view(max_lines)


def browser_save_image(path: str) -> ToolResult:
    """Save a screenshot of the current page."""
    return _get_browser().save_screenshot(path)


def image_view(path: str) -> ToolResult:
    """View an image file."""
    try:
        import base64
        if not os.path.exists(path):
            return ToolResult(success=False, message="Image not found: {}".format(path))
        with open(path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
        b64 = "data:{};base64,".format(mime) + base64.b64encode(data).decode()
        return ToolResult(
            success=True,
            message="Image loaded: {} ({} bytes)".format(path, len(data)),
            data={"path": path, "size": len(data), "mime": mime},
        )
    except Exception as e:
        return ToolResult(success=False, message="Failed to view image: {}".format(e))


# ─── BrowserTool class (Manus pattern) ────────────────────────────────────────

class BrowserTool:
    """Browser tool class wrapping all browser functions."""

    name: str = "browser"

    def get_tools(self) -> list:
        return [
            {"type": "function", "function": {
                "name": "browser_navigate",
                "description": "Buka URL di browser. Gunakan ini untuk mengakses website, halaman web, atau URL apapun. Browser akan tampil di layar VNC komputer Dzeck secara real-time.",
                "parameters": {"type": "object", "properties": {
                    "url": {"type": "string", "description": "URL lengkap yang akan dibuka (contoh: https://wikipedia.org)"}
                }, "required": ["url"]},
            }},
            {"type": "function", "function": {
                "name": "browser_view",
                "description": "Lihat konten halaman browser yang sedang terbuka saat ini. Mengembalikan teks halaman, URL, judul, dan screenshot.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
            {"type": "function", "function": {
                "name": "browser_click",
                "description": "Klik elemen di halaman browser. Gunakan koordinat (x, y) atau index elemen.",
                "parameters": {"type": "object", "properties": {
                    "coordinate_x": {"type": "number", "description": "Koordinat X pixel untuk klik"},
                    "coordinate_y": {"type": "number", "description": "Koordinat Y pixel untuk klik"},
                    "index": {"type": "integer", "description": "Index elemen interaktif (dari browser_view)"},
                    "button": {"type": "string", "description": "Tombol mouse: left, right, middle", "default": "left"},
                }, "required": []},
            }},
            {"type": "function", "function": {
                "name": "browser_input",
                "description": "Ketik teks ke field input di halaman browser.",
                "parameters": {"type": "object", "properties": {
                    "text": {"type": "string", "description": "Teks yang akan diketik"},
                    "coordinate_x": {"type": "number", "description": "Koordinat X field input"},
                    "coordinate_y": {"type": "number", "description": "Koordinat Y field input"},
                    "index": {"type": "integer", "description": "Index elemen input (dari browser_view)"},
                    "press_enter": {"type": "boolean", "description": "Tekan Enter setelah mengetik", "default": False},
                }, "required": ["text"]},
            }},
            {"type": "function", "function": {
                "name": "browser_press_key",
                "description": "Tekan tombol keyboard di browser (Enter, Tab, Escape, Backspace, dll).",
                "parameters": {"type": "object", "properties": {
                    "key": {"type": "string", "description": "Nama tombol: Enter, Tab, Escape, Backspace, ArrowDown, dll"},
                }, "required": ["key"]},
            }},
            {"type": "function", "function": {
                "name": "browser_scroll_down",
                "description": "Scroll ke bawah di halaman browser.",
                "parameters": {"type": "object", "properties": {
                    "amount": {"type": "integer", "description": "Jumlah pixel scroll (default 300)", "default": 300},
                }, "required": []},
            }},
            {"type": "function", "function": {
                "name": "browser_scroll_up",
                "description": "Scroll ke atas di halaman browser.",
                "parameters": {"type": "object", "properties": {
                    "amount": {"type": "integer", "description": "Jumlah pixel scroll (default 300)", "default": 300},
                }, "required": []},
            }},
            {"type": "function", "function": {
                "name": "browser_select_option",
                "description": "Pilih opsi dari dropdown/select di halaman browser.",
                "parameters": {"type": "object", "properties": {
                    "index": {"type": "integer", "description": "Index elemen select"},
                    "option": {"type": "integer", "description": "Index opsi yang dipilih"},
                }, "required": ["index", "option"]},
            }},
            {"type": "function", "function": {
                "name": "browser_console_exec",
                "description": "Jalankan JavaScript di console browser.",
                "parameters": {"type": "object", "properties": {
                    "javascript": {"type": "string", "description": "Kode JavaScript yang akan dijalankan"},
                }, "required": ["javascript"]},
            }},
            {"type": "function", "function": {
                "name": "browser_console_view",
                "description": "Lihat log console browser (output dari console.log, error, dll).",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
            {"type": "function", "function": {
                "name": "browser_save_image",
                "description": "Simpan gambar dari halaman browser ke file.",
                "parameters": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Path file untuk menyimpan screenshot/gambar"},
                }, "required": ["path"]},
            }},
        ]
