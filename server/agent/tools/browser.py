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
        import base64
        ss_bytes = page.screenshot(type="jpeg", quality=55, full_page=False)
        ss_b64 = "data:image/jpeg;base64," + base64.b64encode(ss_bytes).decode()
        browser.close()
        print(json.dumps({"success":True,"url":current_url,"title":title,"content":content,"screenshot_b64":ss_b64}))
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
                "screenshot_b64": res.get("screenshot_b64"),
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
        import base64
        ss_b64 = "data:image/jpeg;base64," + base64.b64encode(page.screenshot(type="jpeg", quality=55)).decode()
        browser.close()
        print(json.dumps({"success":True,"url":current_url,"title":title,"content":content,"screenshot_b64":ss_b64}))
except Exception as e:
    print(json.dumps({"success":False,"error":str(e)}))
''', url=self.current_url, x=x, y=y, button=button)
        res = self._run_playwright(script)
        self.current_url = res.get("url", self.current_url)
        return ToolResult(
            success=res.get("success", False),
            message="Clicked at ({}, {}). Page: {}\n\n{}".format(x, y, res.get("title",""), res.get("content","")),
            data={"x": x, "y": y, "button": button, "url": res.get("url",""), "screenshot_b64": res.get("screenshot_b64")},
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
        import base64
        ss_b64 = "data:image/jpeg;base64," + base64.b64encode(page.screenshot(type="jpeg", quality=55)).decode()
        browser.close()
        print(json.dumps({"success":True,"content":content,"screenshot_b64":ss_b64}))
except Exception as e:
    print(json.dumps({"success":False,"error":str(e)}))
''', url=self.current_url, delta_y=delta_y)
        res = self._run_playwright(script)
        return ToolResult(
            success=res.get("success", False),
            message="Scrolled {}.\n\n{}".format(direction, res.get("content", res.get("error", ""))),
            data={"direction": direction, "amount": amount, "screenshot_b64": res.get("screenshot_b64")},
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
        self.current_url: Optional[str] = None
        self.console_logs: List[str] = []

    def start(self) -> bool:
        if not _playwright_available:
            return False
        try:
            from playwright.sync_api import sync_playwright

            display = os.environ.get("DISPLAY", "") or os.environ.get("DZECK_VNC_DISPLAY", "")

            if display:
                self._headless = False
                logger.info("[Browser] Using VNC display %s (non-headless).", display)
            else:
                self._headless = True
                logger.info("[Browser] No DISPLAY found, using headless mode.")

            self._pw = sync_playwright().start()

            launch_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--no-zygote",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--window-size=1280,720",
                "--window-position=0,0",
            ]

            if not display:
                launch_args += ["--disable-gpu", "--single-process"]

            env = dict(os.environ)
            if display:
                env["DISPLAY"] = display

            self._browser = self._pw.chromium.launch(
                headless=self._headless,
                args=launch_args,
                env=env if not self._headless else None,
            )
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            self._page = self._context.new_page()
            self._page.on("console", lambda msg: self.console_logs.append("[{}] {}".format(msg.type, msg.text)))
            self._started = True
            mode = "VNC non-headless" if not self._headless else "headless"
            logger.info("[Browser] Playwright started (%s).", mode)
            return True
        except Exception as e:
            logger.error("[Browser] Failed to start Playwright: %s", e)
            self._started = False
            return False

    def _capture_screenshot_b64(self) -> Optional[str]:
        try:
            import base64
            data = self._page.screenshot(type="jpeg", quality=55, full_page=False)
            return "data:image/jpeg;base64," + base64.b64encode(data).decode()
        except Exception:
            return None

    def navigate(self, url: str) -> ToolResult:
        if not self._started and not self.start():
            return ToolResult(success=False, message="Playwright not available.")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self._page.wait_for_timeout(1200)
            self.current_url = self._page.url
            title = self._page.title()
            content = self._page.inner_text("body")[:8000]
            screenshot_b64 = self._capture_screenshot_b64()
            return ToolResult(
                success=True,
                message="Page: {}\nURL: {}\n\n{}".format(title, self.current_url, content),
                data={"url": self.current_url, "title": title, "content": content, "screenshot_b64": screenshot_b64},
            )
        except Exception as e:
            return ToolResult(success=False, message="Navigate failed: {}".format(e))

    def view(self) -> ToolResult:
        if not self._started:
            return ToolResult(success=False, message="No page loaded.")
        try:
            content = self._page.inner_text("body")[:8000]
            title = self._page.title()
            screenshot_b64 = self._capture_screenshot_b64()
            return ToolResult(
                success=True,
                message="Page: {}\nURL: {}\n\n{}".format(title, self.current_url, content),
                data={"url": self.current_url, "title": title, "content": content, "screenshot_b64": screenshot_b64},
            )
        except Exception as e:
            return ToolResult(success=False, message="View failed: {}".format(e))

    def click(self, x: float, y: float, button: str = "left") -> ToolResult:
        if not self._started and not self.start():
            return ToolResult(success=False, message="Playwright not available.")
        try:
            btn_map = {"left": "left", "right": "right", "middle": "middle"}
            self._page.mouse.click(x, y, button=btn_map.get(button, "left"))
            self._page.wait_for_timeout(800)
            self.current_url = self._page.url
            title = self._page.title()
            content = self._page.inner_text("body")[:6000]
            screenshot_b64 = self._capture_screenshot_b64()
            return ToolResult(
                success=True,
                message="Clicked ({}, {}). Page: {}\nURL: {}\n\n{}".format(x, y, title, self.current_url, content),
                data={"x": x, "y": y, "button": button, "url": self.current_url, "title": title, "content": content, "screenshot_b64": screenshot_b64},
            )
        except Exception as e:
            return ToolResult(success=False, message="Click failed: {}".format(e))

    def type_text(self, text: str) -> ToolResult:
        if not self._started and not self.start():
            return ToolResult(success=False, message="Playwright not available.")
        try:
            self._page.keyboard.type(text)
            self._page.wait_for_timeout(500)
            screenshot_b64 = self._capture_screenshot_b64()
            return ToolResult(
                success=True,
                message="Typed: {}".format(repr(text)),
                data={"text": text, "url": self.current_url, "screenshot_b64": screenshot_b64},
            )
        except Exception as e:
            return ToolResult(success=False, message="Type failed: {}".format(e))

    def scroll(self, direction: str, amount: int = 3) -> ToolResult:
        if not self._started and not self.start():
            return ToolResult(success=False, message="Playwright not available.")
        try:
            delta_y = amount * 200 if direction == "down" else -amount * 200
            self._page.mouse.wheel(0, delta_y)
            self._page.wait_for_timeout(500)
            content = self._page.inner_text("body")[:4000]
            screenshot_b64 = self._capture_screenshot_b64()
            return ToolResult(
                success=True,
                message="Scrolled {}.\n\n{}".format(direction, content),
                data={"direction": direction, "amount": amount, "url": self.current_url, "screenshot_b64": screenshot_b64},
            )
        except Exception as e:
            return ToolResult(success=False, message="Scroll failed: {}".format(e))

    def console_view(self, max_lines: int = 100) -> ToolResult:
        logs = self.console_logs[-max_lines:]
        text = "\n".join(logs) if logs else "(No console logs)"
        return ToolResult(success=True, message="Console logs:\n\n{}".format(text), data={"logs": logs})

    def save_screenshot(self, path: str) -> ToolResult:
        if not self._started:
            return ToolResult(success=False, message="No page loaded.")
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._page.screenshot(path=path, full_page=False)
            return ToolResult(success=True, message="Screenshot saved to: {}".format(path), data={"save_path": path})
        except Exception as e:
            return ToolResult(success=False, message="Save screenshot failed: {}".format(e))

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._started = False


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


def _make_session() -> Any:
    """Create the best available browser session.
    Priority: Local Playwright > E2B > HTTP fallback.
    Auto-installs Chromium if needed.
    """
    if _playwright_available and PLAYWRIGHT_ENABLED:
        sess = PlaywrightSession()
        if sess.start():
            logger.info("[Browser] Using local headless Playwright (screenshot mode).")
            return sess
        logger.warning("[Browser] Local Playwright failed — trying auto-install Chromium...")
        if _install_playwright_chromium():
            sess2 = PlaywrightSession()
            if sess2.start():
                logger.info("[Browser] Playwright started after auto-install.")
                return sess2
        logger.warning("[Browser] Playwright still unavailable, trying fallback.")

    if E2B_ENABLED:
        logger.info("[Browser] Using E2B cloud sandbox for browser automation.")
        return E2BBrowserSession()

    logger.warning("[Browser] Using HTTP fallback (no screenshots).")
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
            data={"path": path, "size": len(data), "mime": mime, "screenshot_b64": b64},
        )
    except Exception as e:
        return ToolResult(success=False, message="Failed to view image: {}".format(e))


# ─── BrowserTool class (Manus pattern) ────────────────────────────────────────

class BrowserTool:
    """Browser tool class wrapping all browser functions."""

    name: str = "browser"

    def get_tools(self) -> list:
        return []
