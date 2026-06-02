---
name: camoufox
description: "Stealth Firefox (anti-detect) for human-like, hard-to-block web automation and scraping with a Playwright-compatible API — C++-level fingerprint spoofing, humanized cursor, geoip/proxy, OS spoofing. Use when a target blocks bots/headless or needs a realistic browser fingerprint."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [automation, browser, scraping, stealth, anti-detect, playwright, firefox]
    entrypoint: "pip install -U camoufox[geoip]  ·  python -m camoufox fetch  ·  from camoufox.sync_api import Camoufox"
    upstream: "https://github.com/daijro/camoufox (MPL-2.0)"
---

# Camoufox — stealth browser automation

Camoufox is an open-source **Firefox fork built for AI automation**: it mimics a
real human browser and is hard for anti-bot systems to detect. It exposes a
**Playwright-compatible** Python API, so existing Playwright code works with only
the browser-launch line changed. Use it when a normal Playwright/headless Chromium
run gets blocked, fingerprinted, or served a challenge.

> **License note:** Camoufox itself is **MPL-2.0** (this skill doc is MIT). It is a
> separate tool you install; birkin only documents how to drive it.

## When to Use

- A site **blocks bots / headless browsers**, returns CAPTCHAs/challenges, or
  serves different content to automation.
- You need a **consistent, realistic browser fingerprint** (navigator, screen,
  WebGL, audio, timezone/locale, fonts) that matches a chosen OS and proxy region.
- You want **human-like interaction** (cursor movement) during scraping/automation.

## When NOT to Use

- Plain, bot-friendly pages or APIs — use `requests`/`httpx` or vanilla Playwright;
  Camoufox is heavier (downloads a patched Firefox binary).
- You need **Chromium** fingerprints — Camoufox is Firefox-only and cannot spoof
  Chromium. Some WAFs probe SpiderMonkey-specific behavior that is impossible to
  hide.
- Anything that violates a site's Terms of Service or law — scrape responsibly,
  honor robots.txt/rate limits, and only automate what you are authorized to.

## Install

```bash
pip install -U camoufox[geoip]     # [geoip] enables proxy-based timezone/locale
python -m camoufox fetch           # download the patched Firefox binary (one-time)
```

Prerelease build with hardware spoofing (optional):

```bash
pip install -U cloverlabs-camoufox
python -m camoufox sync
python -m camoufox set official/prerelease
python -m camoufox fetch
```

## Usage

**Synchronous** (Playwright sync API under the hood):

```python
from camoufox.sync_api import Camoufox

with Camoufox(headless=True) as browser:
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())
```

**Asynchronous**:

```python
import asyncio
from camoufox.async_api import AsyncCamoufox

async def main():
    async with AsyncCamoufox(headless=True) as browser:
        page = await browser.new_page()
        await page.goto("https://example.com")
        print(await page.title())

asyncio.run(main())
```

The returned `browser`/`page` are standard Playwright objects — use the full
Playwright API (`page.click`, `page.fill`, `page.wait_for_selector`, etc.).

## Key options (pass to `Camoufox(...)` / `AsyncCamoufox(...)`)

| Option | What it does |
|---|---|
| `os` | Target OS for a consistent fingerprint: `"windows"`, `"macos"`, `"linux"` (or a list to randomize). Drives fonts, navigator, etc. |
| `humanize` | `True` (or a max-seconds float) → human-like cursor movement between actions. |
| `geoip` | `True` → derive timezone/locale/geolocation from the proxy's IP (needs `[geoip]`). |
| `proxy` | `{"server": "http://host:port", "username": "...", "password": "..."}`. |
| `locale` / `timezone` | Explicit overrides (e.g. `"ko-KR"`, `"Asia/Seoul"`). |
| `headless` | `True`, `False`, or `"virtual"` (Xvfb on Linux). |
| `fingerprint_preset` | `True` for real BrowserForge-backed presets (recommended on recent versions). |
| `addons` | List of Firefox addon paths to load. |
| `block_images` / `block_webrtc` | Performance / leak-prevention toggles. |

Unset properties are auto-filled from **BrowserForge** fingerprints (statistically
realistic, internally consistent) — prefer leaving things unset over inventing
inconsistent values that anti-bot systems flag.

### Recommended pattern (rotating, geo-consistent)

```python
from camoufox.sync_api import Camoufox

with Camoufox(
    headless=True,
    os=["windows", "macos"],          # randomize across realistic profiles
    humanize=True,
    geoip=True,                        # timezone/locale follow the proxy
    proxy={"server": "http://gate.example:8000",
           "username": "u", "password": "p"},
) as browser:
    page = browser.new_page()
    page.goto("https://target.example/listing", wait_until="domcontentloaded")
    page.wait_for_selector(".item")
    data = page.eval_on_selector_all(".item", "els => els.map(e => e.innerText)")
```

## Caveats

- **Firefox-only**; no Chromium fingerprint injection. SpiderMonkey-engine probes
  cannot be spoofed.
- Fingerprints must stay **internally consistent** — don't hand-set one field and
  leave related ones default; let BrowserForge fill the rest.
- Anti-bot vendors patch over time; treat detection as an arms race and keep
  Camoufox updated (`pip install -U`, re-`fetch`). Active development moved to
  checkpoint releases + forks (CloverLabsAI, VulpineOS) — check the repo for the
  current recommended package.
- First run downloads a full Firefox build (~hundreds of MB) — not suitable for
  tiny/ephemeral environments.

## Sources

- Upstream repo (MPL-2.0): https://github.com/daijro/camoufox
- API mirrors Playwright for Python: https://playwright.dev/python/
