# Technical Design Document (TDD) - Persona Project

## 1. Technical Stack
- **Language:** Python 3.9+
- **Web Framework:** Flask
- **Browser Automation:** Microsoft Playwright (Async API)
- **Database:** Flat files (JSON/CSV)
- **Frontend:** HTML5, Vanilla CSS, Vanilla JavaScript, Server-Sent Events (SSE).

## 2. Technical Architecture Decisions
### 2.1 Why Playwright?
Playwright is chosen over Selenium or BeautifulSoup because LinkedIn heavily relies on React and JavaScript for rendering, and strictly blocks basic HTTP scrapers. Playwright allows deep DOM manipulation, network interception, and execution of stealth scripts (`navigator.webdriver` removal).

### 2.2 Why Flat Files instead of SQL?
The initial scope requires extreme portability and ease of setup without external dependencies like PostgreSQL. Flat JSON files with Python `threading.Lock` mechanisms are sufficient for the expected scale (10,000s of profiles).

### 2.3 Concurrency Model
Flask handles incoming HTTP requests synchronously. To prevent long scraping operations (which take ~15-30 seconds per profile) from blocking the server, `app.py` spawns a single daemon thread running an `asyncio` event loop. All Playwright calls are dispatched to this loop.

## 3. Error Handling and Recovery
- **Playwright Crash Recovery:** If the persistent context fails to load due to stale file locks (WinError 32), `core.py` catches the exception, forcibly kills `chrome.exe` using OS-level commands, deletes the `SingletonLock` / `LOCK` files in the profile directory, and attempts a restart.
- **Scrape Retries:** `extract_profile` implements an automatic retry (`MAX_RETRIES = 2`) if it encounters a Playwright `TargetClosedError` or network timeout during extraction.

## 4. Anti-Bot Evasion Techniques
- Hiding WebDriver flags via injected Javascript.
- Custom User-Agent strings.
- Implementation of human-like scrolling (`window.scrollBy`) and randomized `asyncio.sleep()` delays.
- Avoiding headless mode for initial authentication (to solve CAPTCHAs manually).
