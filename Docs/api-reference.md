# 📡 REST API Reference

> Complete API documentation for all 40+ endpoints in the Persona platform.

---

## Table of Contents

- [Overview](#overview)
- [Scraper Control Endpoints](#scraper-control-endpoints)
- [Client API Endpoints](#client-api-endpoints)
- [Admin API Endpoints](#admin-api-endpoints)
- [Task Bucket API Endpoints](#task-bucket-api-endpoints)
- [Export API Endpoints](#export-api-endpoints)
- [Profile Ranking API](#profile-ranking-api)
- [Persona Bulk API](#persona-bulk-api)
- [SSE Events Endpoint](#sse-events-endpoint)
- [Error Handling](#error-handling)

---

## Overview

- **Base URL**: `http://localhost:5000`
- **Content Type**: All request/response bodies are `application/json` unless downloading files
- **Authentication**: No API key required (controlled by network access)
- **CORS**: Enabled for all origins via `flask-cors`

### Common Response Structure

**Success:**
```json
{
  "success": true,
  "message": "Operation completed",
  "data": { ... }
}
```

**Error:**
```json
{
  "success": false,
  "error": "Description of the error"
}
```

### HTTP Status Codes Used

| Code | Meaning |
|------|---------|
| `200` | Success |
| `201` | Created (task added to queue) |
| `202` | Accepted (task queued, processing in background) |
| `400` | Bad Request (missing required fields) |
| `401` | Unauthorized (scraper not authenticated) |
| `404` | Not Found (job/task/profile not found) |
| `500` | Internal Server Error |

---

## Scraper Control Endpoints

### `POST /api/scraper/init` — Initialize Browser

Starts the Playwright Chromium browser and creates a persistent context.

**Request:**
```json
{
  "headless": true,
  "browser_type": "chromium",
  "session_name": "default"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `headless` | `bool` | `false` | Run browser without visible window |
| `browser_type` | `string` | `"chromium"` | Browser engine |
| `session_name` | `string` | `"default"` | Persistent data directory name |

**Response (200):**
```json
{
  "success": true,
  "message": "Browser initialized"
}
```

**Notes:**
- If a scraper is already running, it will be closed first
- The browser data is stored in `browser_data/{session_name}/`
- First call may take 5-10 seconds to launch the browser

---

### `POST /api/scraper/login` — Log In to LinkedIn

**Request:**
```json
{
  "email": "user@example.com",
  "password": "your_password"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Login successful!"
}
```

**Response (400 — missing fields):**
```json
{
  "success": false,
  "error": "Email and password required"
}
```

**Notes:**
- Must call `/api/scraper/init` first
- After successful login, session is persisted in `browser_data/`
- Subsequent server restarts reuse the saved session automatically

---

### `GET /api/scraper/stats` — Get Scraper Statistics

**Response (200):**
```json
{
  "success": true,
  "stats": {
    "requests_made": 42,
    "profiles_scraped": 38,
    "errors": 4,
    "start_time": "2026-06-30T10:00:00",
    "runtime_seconds": 3600.5,
    "is_authenticated": true
  }
}
```

---

### `POST /api/scraper/search` — Search LinkedIn for People

**Request:**
```json
{
  "first_name": "John",
  "last_name": "Doe",
  "company": "Google",
  "max_results": 10
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `first_name` | `string` | Yes* | First name |
| `last_name` | `string` | Yes* | Last name |
| `company` | `string` | No | Company name filter |
| `max_results` | `int` | No (default: 10) | Maximum results to return |

\* At least one of `first_name` or `last_name` is required.

**Response (200):**
```json
{
  "success": true,
  "results": [
    {
      "profile_url": "https://www.linkedin.com/in/johndoe",
      "name": "John Doe",
      "profile_picture": "https://media.licdn.com/dms/image/...",
      "headline": "Software Engineer at Google"
    }
  ],
  "total": 5
}
```

---

### `POST /api/scraper/search-and-extract` — Search & Extract All Found Profiles

Performs a people search then automatically extracts the full profile for each result. Runs in the background.

**Request:**
```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "company": ""
}
```

**Response (202 — task started):**
```json
{
  "success": true,
  "status": "started",
  "message": "Scraping started in background. Please check back later."
}
```

**Response (200 — cached result):**
```json
{
  "success": true,
  "cached": true,
  "profiles": [ { "name": "Jane Smith", ... } ],
  "total": 3
}
```

**Response (202 — already in progress):**
```json
{
  "success": true,
  "status": "in_progress",
  "message": "Scraping is still running...",
  "total": 0,
  "profiles": []
}
```

---

### `POST /api/scraper/close` — Close Browser

**Response (200):**
```json
{
  "success": true,
  "message": "Closed"
}
```

---

## Client API Endpoints

### `POST /api/client/scrape` — Submit a Search Request

The primary client-facing endpoint. Routes all requests through the Task Bucket for automatic background processing.

**Request:**
```json
{
  "name": "John Doe"
}
```

**Response (200 — cached):**
```json
{
  "success": true,
  "cached": true,
  "profiles": [ { ... } ],
  "total": 3,
  "reference_number": "cached_John Doe"
}
```

**Response (202 — already queued):**
```json
{
  "success": true,
  "status": "pending",
  "reference_number": "a1b2c3d4-e5f6-...",
  "message": "Already queued. Check back soon."
}
```

**Response (202 — newly queued):**
```json
{
  "success": true,
  "status": "queued",
  "reference_number": "a1b2c3d4-e5f6-...",
  "message": "Task queued in the bucket. The worker will process it automatically."
}
```

---

### `GET /api/client/scrape-status` — Poll Task Status

**Query Parameters:** `?task_id=...` or `?name=...`

**Response (202 — pending):**
```json
{
  "success": true,
  "status": "pending",
  "message": "Queued in Task Bucket — the worker will process it automatically."
}
```

**Response (202 — in progress):**
```json
{
  "success": true,
  "status": "in_progress",
  "message": "Currently scraping LinkedIn profiles…"
}
```

**Response (200 — completed):**
```json
{
  "success": true,
  "status": "completed",
  "profiles": [
    {
      "name": "John Doe",
      "headline": "Software Engineer at Google",
      "location": "San Francisco, CA",
      ...
    }
  ],
  "total": 3
}
```

**Response (200 — failed):**
```json
{
  "success": false,
  "status": "failed",
  "error": "No profile found for: John Doe"
}
```

---

### `GET/POST /api/client/retrieve` — Retrieve Results by Return Code

**Query/Body:** `return_code`

**Response (200 — completed):**
```json
{
  "success": true,
  "status": "completed",
  "profile": {
    "name": "John Doe",
    "headline": "...",
    ...
  },
  "csv_url": "/api/client/download/csv?return_code=abc123"
}
```

---

### `GET/POST /api/client/lookup-by-reference` — Lookup by Reference Number

**Query/Body:** `reference_number` (also accepts `#reference_number`)

**Response (200 — completed):**
```json
{
  "success": true,
  "status": "completed",
  "reference_number": "a1b2c3d4-...",
  "person_name": "John Doe",
  "scraped_at": "2026-06-30T10:15:00",
  "is_bulk": false,
  "profiles": [ { ... } ],
  "total": 1
}
```

**Response (202 — in progress):**
```json
{
  "success": false,
  "status": "in_progress",
  "reference_number": "a1b2c3d4-...",
  "person_name": "John Doe",
  "requested_at": "2026-06-30T10:10:00",
  "message": "This profile is still being scraped. Please try again in a few seconds."
}
```

---

### `GET /api/client/download/csv` — Download CSV File

**Query:** `?return_code=abc123`

**Response:** File download (`text/csv`)

---

### `GET /api/client/download/json` — Download JSON File

**Query:** `?return_code=abc123`

**Response:** File download (`application/json`)

---

### `GET /api/client/download/pdf` — Download PDF Report

**Query:** `?return_code=abc123`

**Response:** File download (`application/pdf`)

The PDF includes:
- LinkedIn blue header banner
- Profile photo (downloaded and embedded)
- Name, headline, location, URL, connections
- All sections: About, Experience, Education, Skills, Certifications, Languages, Volunteer, Honors, Recommendations

---

## Admin API Endpoints

### `GET /api/admin/approvals` — List All Scrape Requests

Returns a combined list from both the Task Bucket queue and jobs.json, sorted by newest first.

**Response (200):**
```json
{
  "success": true,
  "approvals": [
    {
      "request_id": "a1b2c3d4-...",
      "reference_number": "a1b2c3d4-...",
      "person_name": "John Doe",
      "profile_url": "https://www.linkedin.com/in/johndoe",
      "status": "completed",
      "requested_at": "2026-06-30T10:00:00",
      "scraped_at": "2026-06-30T10:02:30",
      "error": null
    }
  ]
}
```

---

### `POST /api/admin/approve` — Retry/Re-scrape a Job

**Request:**
```json
{
  "request_id": "a1b2c3d4-..."
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Re-scrape triggered for request a1b2c3d4-..."
}
```

---

### `POST /api/admin/scrape-requested-name` — Manually Scrape a Name

Synchronous scrape — blocks until complete.

**Request:**
```json
{
  "person_name": "John Doe",
  "request_id": "abc123"
}
```

**Response (200):**
```json
{
  "success": true,
  "profile": { ... }
}
```

---

### `GET /api/admin/db-profiles` — Get All Profiles

**Response (200):**
```json
{
  "success": true,
  "profiles": [ { ... }, { ... }, ... ]
}
```

---

### `GET /api/admin/download-db/json` — Download Master JSON Database

**Response:** File download of `all_scraped_profiles.json`

---

### `GET /api/admin/download-db/csv` — Download Master CSV Database

**Response:** File download of `all_scraped_profiles.csv`

---

### `POST /api/admin/destroy-db` — Delete Entire Database

⚠️ **Destructive operation** — deletes all scraped data files.

**Response (200):**
```json
{
  "success": true
}
```

---

### `GET /api/admin/events` — SSE Event Stream

Opens a Server-Sent Events connection for real-time admin updates.

**Response:** `text/event-stream`

```
data: {"type":"connected"}

data: {"type":"bucket_update","task_id":"abc","status":"in_progress","query":"John Doe"}

data: {"type":"new_scrape","name":"John Doe","count":1}

: ping
```

---

## Task Bucket API Endpoints

### `POST /api/bucket/add` — Add Tasks to Queue

**Request:**
```json
{
  "queries": ["John Doe", "https://linkedin.com/in/janedoe", "Jane Smith"],
  "type": "name"
}
```

Or a single query:
```json
{
  "query": "John Doe"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `queries` | `string[]` | List of names or URLs to queue |
| `query` | `string` | Single query (alternative to `queries`) |
| `type` | `string` | `"name"` or `"url"` (auto-detected for URLs) |

**Response (201):**
```json
{
  "success": true,
  "added": 3,
  "tasks": [
    {
      "id": "a1b2c3d4-...",
      "query": "John Doe",
      "type": "name",
      "status": "pending",
      "added_at": "2026-06-30T10:00:00",
      ...
    }
  ]
}
```

---

### `POST /api/bucket/add-search` — Add Structured Search Task

**Request:**
```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "company": "Google",
  "max_results": 5
}
```

**Response (201):**
```json
{
  "success": true,
  "task": {
    "id": "a1b2c3d4-...",
    "query": "Jane Smith @ Google",
    "type": "search",
    "search_params": {
      "first_name": "Jane",
      "last_name": "Smith",
      "company": "Google",
      "max_results": 5
    },
    "status": "pending",
    ...
  }
}
```

---

### `GET /api/bucket/status` — Get Queue Status

**Response (200):**
```json
{
  "success": true,
  "worker_running": true,
  "worker_paused": false,
  "rest_seconds": 30,
  "summary": {
    "pending": 3,
    "in_progress": 1,
    "completed": 12,
    "failed": 2,
    "total": 18
  },
  "tasks": [
    {
      "id": "a1b2c3d4-...",
      "query": "John Doe",
      "type": "name",
      "status": "completed",
      "added_at": "2026-06-30T10:00:00",
      "started_at": "2026-06-30T10:00:05",
      "completed_at": "2026-06-30T10:01:30",
      "result_name": "John Doe",
      "result_url": "https://www.linkedin.com/in/johndoe",
      "profiles_found": 1,
      "error": null
    }
  ]
}
```

---

### `POST /api/bucket/pause` — Pause Worker

**Response (200):**
```json
{
  "success": true,
  "paused": true
}
```

---

### `POST /api/bucket/resume` — Resume Worker

**Response (200):**
```json
{
  "success": true,
  "paused": false
}
```

---

### `POST /api/bucket/config` — Update Worker Configuration

**Request:**
```json
{
  "rest_seconds": 45
}
```

**Response (200):**
```json
{
  "success": true,
  "config": {
    "rest_seconds": 45
  }
}
```

---

### `POST /api/bucket/remove` — Remove Pending Task

**Request:**
```json
{
  "task_id": "a1b2c3d4-..."
}
```

**Response (200):**
```json
{
  "success": true
}
```

---

### `POST /api/bucket/clear` — Clear Completed/Failed Tasks

**Request:**
```json
{
  "all": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `all` | `bool` | If `true`, clears ALL tasks. If `false` (default), only clears completed and failed tasks. |

**Response (200):**
```json
{
  "success": true,
  "removed": 14,
  "remaining": 4
}
```

---

## Export API Endpoints

### `POST /api/scraper/export` — Export Data

**Request:**
```json
{
  "data": {
    "profiles": [ { ... }, { ... } ]
  },
  "format": "json"
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `format` | `"json"`, `"csv"` | Output format |

**Response:** File download

---

### `POST /api/export-text-pdf` — Export Raw Text as PDF

**Request:**
```json
{
  "text": "Full profile text content..."
}
```

**Response:** PDF file download

---

### `POST /api/export-profile-pdf` — Export Single Profile as PDF

**Request:**
```json
{
  "profile": {
    "name": "John Doe",
    "headline": "...",
    ...
  }
}
```

**Response:** PDF file download

---

### `POST /api/export-bulk-pdf` — Export Multiple Profiles as PDF

**Request:**
```json
{
  "profiles": [
    { "name": "John Doe", ... },
    { "name": "Jane Smith", ... }
  ]
}
```

**Response:** PDF file download (one page per profile)

---

## Profile Ranking API

### `POST /api/rank` — Rank Profiles

**Request:**
```json
{
  "profiles": [
    {
      "name": "John Doe",
      "headline": "Software Engineer",
      "location": "Colombo, Sri Lanka",
      "about": "Experienced developer...",
      "connections": "500+",
      "experiences": [ { ... } ],
      "education": [ { ... } ],
      "skills": ["Python", "Java"],
      "certifications": [ { ... } ],
      "recommendations": [ { ... } ],
      "volunteer": [ { ... } ],
      "languages": [ { ... } ]
    }
  ]
}
```

**Response (200):**
```json
{
  "success": true,
  "total_input": 10,
  "sri_lankan_count": 7,
  "non_sri_lankan_filtered": 3,
  "ranked": [
    {
      "rank": 1,
      "profile": { ... },
      "scoring": {
        "total_score": 127.5,
        "profile_strength": 89.0,
        "field_follower_score": 38.5,
        "field_category": "Software & IT",
        "is_sri_lankan": true,
        "connections_count": 500,
        "breakdown": {
          "has_headline": 8,
          "headline_length": 3.2,
          "has_about": 8,
          "about_length": 4.5,
          "experience_count": 12,
          "experience_quality": 6,
          "education_count": 8,
          "skills_count": 10,
          "certifications": 6,
          "featured": 0,
          "connections_known": 6,
          "profile_photo": 4,
          "recommendations": 5,
          "volunteer": 3,
          "languages": 2,
          "field_match_followers": 38.5
        }
      },
      "tier": {
        "label": "Elite",
        "color": "#7c3aed",
        "icon": "fa-crown"
      }
    }
  ]
}
```

---

## Persona Bulk API

### `POST /api/persona/bulk-scrape` — Submit Bulk Scrape

**Request:**
```json
{
  "profile_urls": [
    "https://www.linkedin.com/in/user1",
    "https://www.linkedin.com/in/user2"
  ],
  "return_code": "custom_batch_001"
}
```

**Response (202):**
```json
{
  "success": true,
  "message": "Bulk scrape request queued successfully in background.",
  "return_code": "custom_batch_001",
  "status": "in_progress"
}
```

---

### `GET/POST /api/persona/bulk-retrieve` — Retrieve Bulk Results

**Query/Body:** `return_code`

> **Note:** A 1-minute delay policy is enforced after scrape completion. If you query within 60 seconds of completion, you'll receive a `waiting_delay` status.

**Response (200 — waiting delay):**
```json
{
  "success": false,
  "status": "waiting_delay",
  "message": "Bulk scrape completed, but data cannot be retrieved yet. Under the 1-minute delay policy, you must wait another 45 seconds.",
  "remaining_seconds": 45
}
```

**Response (200 — ready):**
```json
{
  "success": true,
  "status": "completed",
  "profiles": [ { ... }, { ... } ],
  "csv_url": "/api/client/download/csv?return_code=custom_batch_001",
  "pdf_url": "/api/client/download/pdf?return_code=custom_batch_001"
}
```

---

## Error Handling

### Common Error Responses

**Scraper not initialized:**
```json
{
  "success": false,
  "error": "Not initialized"
}
```
→ Call `POST /api/scraper/init` first.

**Not authenticated:**
```json
{
  "success": false,
  "error": "Not authenticated"
}
```
→ Call `POST /api/scraper/login` first.

**Missing required fields:**
```json
{
  "success": false,
  "error": "name is required"
}
```
→ Check the endpoint's required fields.

**Job not found:**
```json
{
  "success": false,
  "error": "No scrape request found for the provided return_code"
}
```
→ Verify the return code or reference number.

**Scrape failed:**
```json
{
  "success": false,
  "status": "failed",
  "error": "No profile found for: John Doe"
}
```
→ The scraper couldn't find or extract the requested profile. Try a different search query or retry.
