# System Architecture - Persona Project

## 1. Physical Architecture
Persona runs as a localized monolith on a single machine or VPS.

```text
[ Windows / Ubuntu Host Server ]
 ├── [ Python Interpreter ]
 │    ├── Flask (Port 5000)
 │    └── Asyncio Daemon Thread (Playwright)
 ├── [ Chromium Binaries ]
 └── [ Local Disk ]
      ├── browser_data/ (Cookies & Cache)
      └── exports/ (Database JSON/CSV)
```

## 2. Logical Architecture Layers

### Presentation Layer
- Serves static templates (`index.html`, `client.html`).
- Consumes REST APIs via JavaScript `fetch()`.
- Subscribes to `/api/admin/events` using `EventSource` for real-time status pushes.

### API & Orchestration Layer (`app.py`)
- Defines standard HTTP routes.
- Handles Task Bucket CRUD operations (`queue.json`).
- `bucket_worker_loop()` continually runs in the background to execute scheduled scrapes.
- Converts raw extracted dictionaries into cleaned JSON/CSV and PDF reports.

### Execution Layer (`core.py`)
- Abstracts Playwright complexities.
- Navigates LinkedIn's complex SPA (Single Page Application) routing.
- Uses strict DOM queries (`page.evaluate()`) to isolate main content and exclude sidebars.

## 3. Security Boundary
- The application binds to `localhost` (127.0.0.1) by default or `0.0.0.0` if configured.
- It is designed to run behind a reverse proxy (like Nginx) if deployed publicly, as it has no built-in web authentication (login system for admins) beyond the LinkedIn auth handled by the browser.
