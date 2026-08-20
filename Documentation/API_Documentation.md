# API Documentation - Persona Project

*Base URL:* `http://localhost:5000`

## Scraper Controls
### `POST /api/scraper/init`
Initializes the Playwright browser.
- **Body:** `{"headless": true, "session_name": "default"}`
- **Response:** `{"success": true, "message": "..."}`

### `POST /api/scraper/login`
Submits credentials to LinkedIn (requires headless=false).
- **Body:** `{"email": "...", "password": "..."}`

### `GET /api/scraper/stats`
Returns current scraper health.
- **Response:** `{"success": true, "stats": {"requests_made": 5, "is_authenticated": true, ...}}`

## Task Bucket
### `POST /api/bucket/add`
Adds profiles to the background queue.
- **Body:** `{"queries": ["https://linkedin.com/in/...", "John Doe"], "type": "mixed"}`

### `GET /api/bucket/status`
Returns queue summary.
- **Response:** `{"success": true, "worker_running": true, "summary": {"pending": 2, "completed": 5}}`

### `POST /api/bucket/pause` & `/api/bucket/resume`
Pauses or resumes the background worker.

## Client Portal
### `POST /api/client/scrape`
Submits a name search. If cached, returns immediately; otherwise queues it.
- **Body:** `{"name": "Satya Nadella"}`
- **Response (Queued):** `{"status": "queued", "reference_number": "req-123"}`

### `GET /api/client/scrape-status`
Polls for completion.
- **Params:** `?task_id=req-123`
- **Response:** `{"status": "completed", "profiles": [...]}`

## Event Stream (SSE)
### `GET /api/admin/events`
Text/event-stream endpoint. Pushes JSON data when tasks start, fail, or complete, and when queue statuses change.
