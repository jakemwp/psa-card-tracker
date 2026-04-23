"""
Shared headless Chrome wrapper using undetected-chromedriver.
Bypasses Cloudflare bot detection on psacard.com.

Automatically detects the installed Chrome major version and pins
ChromeDriver to the same version to avoid session-not-created errors.
"""

import re
import subprocess
import time
from bs4 import BeautifulSoup

_driver = None  # module-level singleton — one browser for the whole session


def _get_chrome_major_version() -> int | None:
    """Read the installed Chrome major version from the registry or exe."""
    # Registry path used by the official Chrome installer
    import winreg
    paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Google\Chrome\BLBeacon"),
    ]
    for hive, subkey in paths:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "version")
                major = int(str(val).split(".")[0])
                return major
        except Exception:
            continue

    # Fallback: ask the exe directly
    for exe in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        try:
            out = subprocess.check_output(
                [exe, "--version"], stderr=subprocess.DEVNULL, timeout=5
            ).decode()
            m = re.search(r"(\d+)\.", out)
            if m:
                return int(m.group(1))
        except Exception:
            continue

    return None


def _get_driver():
    global _driver
    if _driver is not None:
        try:
            _ = _driver.window_handles   # raises if dead
            return _driver
        except Exception:
            _driver = None

    import undetected_chromedriver as uc

    chrome_ver = _get_chrome_major_version()

    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--log-level=3")

    kwargs = dict(options=options, use_subprocess=True)
    if chrome_ver:
        kwargs["version_main"] = chrome_ver   # pin driver to installed Chrome

    _driver = uc.Chrome(**kwargs)
    return _driver


def fetch(url: str, wait: float = 3.0) -> BeautifulSoup:
    """
    Fetch a URL with a real Chrome browser (bypasses Cloudflare).
    Waits up to 15 s for Cloudflare challenge to clear, then an
    additional `wait` seconds for JS to finish rendering.
    Returns a BeautifulSoup of the fully-rendered page.
    """
    driver = _get_driver()
    driver.get(url)

    # Wait for Cloudflare challenge page to resolve
    deadline = time.time() + 15
    while time.time() < deadline:
        title = (driver.title or "").lower()
        if "just a moment" in title or "checking" in title or "please wait" in title:
            time.sleep(1)
        else:
            break

    time.sleep(wait)  # let dynamic JS content settle
    return BeautifulSoup(driver.page_source, "lxml")


def quit():
    global _driver
    if _driver:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None
