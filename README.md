<p align="center">
  <h1 align="center">🔍 Persona</h1>
  <p align="center">
    <strong>LinkedIn Profile Intelligence Platform</strong>
  </p>
  <p align="center">
    Scrape · Search · Rank · Export — Full-stack LinkedIn profile intelligence with real-time admin controls, automated task queuing, and a client-facing portal.
  </p>
  <p align="center">
    <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick%20Start-blue?style=for-the-badge" alt="Quick Start"></a>
    <a href="#-rest-api-reference"><img src="https://img.shields.io/badge/API%20Docs-green?style=for-the-badge" alt="API Docs"></a>
    <a href="#-architecture"><img src="https://img.shields.io/badge/Architecture-purple?style=for-the-badge" alt="Architecture"></a>
  </p>
</p>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Architecture](#-architecture)
- [Project Structure](#-project-structure)
- [Quick Start](#-quick-start)
- [Usage Guide](#-usage-guide)
  - [Admin Dashboard](#admin-dashboard)
  - [Client Portal](#client-portal)
  - [Task Bucket System](#task-bucket-system)
- [REST API Reference](#-rest-api-reference)
  - [Scraper Control](#scraper-control)
  - [Client API](#client-api)
  - [Admin API](#admin-api)
  - [Task Bucket API](#task-bucket-api)
  - [Export API](#export-api)
  - [Profile Ranking API](#profile-ranking-api)
- [Data Schema](#-data-schema)
- [Module Reference](#-module-reference)
  - [app.py — Flask Server & Orchestrator](#apppy--flask-server--orchestrator)
  - [core.py — LinkedIn Scraper Engine](#corepy--linkedin-scraper-engine)
  - [ranker.py — Profile Scoring & Ranking](#rankerpy--profile-scoring--ranking)
  - [llm_parser.py — AI Parser (Optional)](#llm_parserpy--ai-parser-optional)
  - [session_manager.py — Browser Session Persistence](#session_managerpy--browser-session-persistence)
- [Configuration](#-configuration)
- [Known Limitations](#-known-limitations)
- [License](#-license)

---

## 🌐 Overview

**Persona** is a full-stack LinkedIn profile intelligence platform that automates the entire pipeline from profile discovery to structured data export. It uses a real Chromium browser (via Playwright) to navigate LinkedIn, extract every visible profile section, and store structured JSON data — all controlled through a web-based admin dashboard and exposed via a comprehensive REST API.

### What It Does

1. **Navigates** to any LinkedIn profile URL using a real Chromium browser controlled by Playwright
2. **Visits dedicated detail pages** (Experience, Education, Skills, etc.) for richer, more accurate data extraction
3. **Parses** every LinkedIn section into structured JSON — experience, education, skills, certifications, languages, volunteer work, honors, recommendations, and more
4. **Searches** for people by name and company, then auto-extracts all found profiles
5. **Ranks** profiles using a weighted scoring model (profile strength + field-aligned relevance)
6. **Queues** scrape tasks in a persistent Task Bucket with automatic background processing
7. **Exports** data as JSON, CSV, or professionally formatted PDF reports
8. **Streams** live updates to admin browsers via Server-Sent Events (SSE)
9. **Serves** a client-facing portal for end-users to search and view profiles

---

## ✨ Features

| Category | Features |
|----------|----------|
| **Scraping** | Single profile extraction · Bulk scraping · Name-based search & extract · Automatic retry on failure · Rate-limiting with configurable delays |
| **Data Extraction** | 15+ LinkedIn sections parsed · Detail sub-page navigation · Contact info extraction · UI noise filtering · Anti-detection measures |
| **Task Management** | Persistent task queue (Task Bucket) · Background worker with rest periods · Pause/resume controls · Auto-start on server launch |
| **Admin Dashboard** | Real-time scraper status · Job monitoring · SSE live updates · Database management · Bulk task operations |
| **Client Portal** | Search by name · View profile cards · Reference number lookup · Cached results for instant retrieval |
| **Ranking** | Weighted scoring model (0–150 pts) · Profile completeness analysis · Field category detection · Sri Lankan geo-filter · Tiered labels (Beginner → Elite) |
| **Export** | JSON · CSV · PDF (single & bulk) · Full-text PDF · Per-job files · Master database downloads |
| **Persistence** | JSON database with deduplication · CSV mirror · Name-based result cache · Persistent browser sessions |

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PERSONA PLATFORM                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────────────────────────────┐       │
│  │ Client Portal│    │         Admin Dashboard               │       │
│  │ (client.html)│    │         (index.html)                  │       │
│  │              │    │                                       │       │
│  │  • Search    │    │  • Scraper Controls  • Job Monitor    │       │
│  │  • View      │    │  • Task Bucket       • DB Management  │       │
│  │  • Ref Lookup│    │  • SSE Live Updates  • Export Center   │       │
│  └──────┬───────┘    └──────────┬────────────────────────────┘       │
│         │                       │                                    │
│         └───────────┬───────────┘                                    │
│                     │  HTTP / SSE                                    │
│         ┌───────────▼───────────┐                                    │
│         │    app.py (Flask)     │                                    │
│         │                       │                                    │
│         │  • REST API (40+ endpoints)                                │
│         │  • Background async loop                                   │
│         │  • Task Bucket worker                                      │
│         │  • SSE broadcaster                                         │
│         │  • File persistence                                        │
│         └──────┬────────┬───────┘                                    │
│                │        │                                            │
│     ┌──────────▼──┐  ┌──▼──────────────┐                             │
│     │  core.py    │  │   ranker.py     │                             │
│     │  Scraper    │  │   Profile       │                             │
│     │  Engine     │  │   Ranking       │                             │
│     │             │  │                  │                             │
│     │  Playwright │  │  Weighted ML     │                             │
│     │  Chromium   │  │  Scoring Model   │                             │
│     └──────┬──────┘  └──────────────────┘                            │
│            │                                                         │
│     ┌──────▼──────┐                                                  │
│     │  LinkedIn   │                                                  │
│     │  (Browser)  │                                                  │
│     └─────────────┘                                                  │
│                                                                      │
│  ┌────────────────────────────────────────────────────┐               │
│  │                   Data Layer                       │               │
│  │                                                    │               │
│  │  exports/                                          │               │
│  │  ├── all_scraped_profiles.json  (Master JSON DB)   │               │
│  │  ├── all_scraped_profiles.csv   (Master CSV)       │               │
│  │  ├── name_cache.json            (Search cache)     │               │
│  │  └── api_scrapes/                                  │               │
│  │      ├── jobs.json              (Job registry)     │               │
│  │      ├── {id}.json / .csv       (Per-job files)    │               │
│  │      └── scraped_profiles.csv   (Master CSV)       │               │
│  │  exports/task_bucket/                              │               │
│  │  ├── queue.json                 (Task queue)       │               │
│  │  └── config.json                (Worker config)    │               │
│  │  browser_data/{session}/        (Chromium data)    │               │
│  └────────────────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Persistent Browser Context**: Playwright's `launch_persistent_context` stores cookies and session data across restarts — log in once, scrape forever
- **Async Background Loop**: A dedicated `asyncio` event loop runs in a daemon thread, allowing non-blocking scrape operations while Flask handles HTTP requests synchronously
- **Task Bucket Pattern**: A persistent JSON-backed queue with a single background worker that processes tasks sequentially with configurable rest periods between scrapes
- **SSE for Live Updates**: Server-Sent Events push real-time status changes to all connected admin browsers without polling

---

## 📁 Project Structure

```
persona/
├── app.py                  # Flask web server, REST API, task orchestration (2500+ lines)
├── core.py                 # LinkedIn scraper engine — Playwright browser automation (1055 lines)
├── ranker.py               # Profile scoring & ranking model (363 lines)
├── llm_parser.py           # Optional AI-powered profile parser via OpenAI (57 lines)
├── session_manager.py      # Browser cookie session persistence (52 lines)
├── update_app.py           # Migration/update utility script
├── req.txt                 # Python dependencies
├── templates/
│   ├── index.html          # Admin dashboard (single-page app)
│   └── client.html         # Client-facing profile portal
└── README.md               # This file
```

### Auto-Generated at Runtime

```
exports/
├── all_scraped_profiles.json    # Master JSON database (all profiles ever scraped)
├── all_scraped_profiles.csv     # Master CSV mirror
├── name_cache.json              # Name → profile URL cache for instant lookups
└── api_scrapes/
    ├── jobs.json                # Job status registry
    ├── approvals.json           # Legacy approvals (backward compat)
    ├── scraped_profiles.csv     # Appended master CSV for API scrapes
    ├── {return_code}.json       # Per-job JSON result
    ├── {return_code}.csv        # Per-job CSV result
    └── {return_code}.pdf        # Per-job PDF report (generated on demand)

exports/task_bucket/
├── queue.json                   # Persistent task queue
└── config.json                  # Worker configuration (rest_seconds)

browser_data/
└── {session_name}/              # Chromium persistent profile (cookies, localStorage)
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+**
- **pip**
- A valid **LinkedIn account**

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/persona.git
cd persona
```

### 2. Install Dependencies

```bash
pip install -r req.txt
```

### 3. Install Playwright Browsers

```bash
playwright install chromium
```

### 4. (Optional) Configure AI Parser

Create a `.env` file if you want to use the optional AI-powered parser:

```env
OPENAI_API_KEY=sk-...
```

### 5. Start the Server

```bash
python app.py
```

```
Persona - LinkedIn Profile Scraper and Ranker
http://localhost:5000
```

### 6. Log In to LinkedIn

1. Open `http://localhost:5000/admin` in your browser
2. Click **Initialize Scraper** (set `headless: false` to see the browser window)
3. Enter your LinkedIn credentials and click **Login**
4. Once authenticated, the session is saved to `browser_data/default/` and persists across restarts

---

## 📖 Usage Guide

### Admin Dashboard

Access at **`http://localhost:5000/admin`**

The admin dashboard is a full-featured single-page application for controlling every aspect of the scraper:

| Section | Capabilities |
|---------|-------------|
| **Scraper Controls** | Initialize/close browser · Login to LinkedIn · Monitor authentication status |
| **Single Scrape** | Paste a LinkedIn URL → get structured data in seconds |
| **Bulk Scrape** | Paste multiple URLs → sequential extraction with rate limiting |
| **Task Bucket** | Add tasks by name or URL · Monitor queue · Pause/resume worker · Configure rest periods |
| **Job Monitor** | Real-time job status via SSE · Retry failed jobs · View results |
| **Database** | Browse all profiles · Search/filter · Download full DB as JSON/CSV |
| **Export** | Download individual or bulk PDFs · Export filtered data |

### Client Portal

Access at **`http://localhost:5000`** (root URL)

The client portal is a clean, read-only interface designed for end-users:

- **Search by name** — enter a person's name, results are cached for instant future lookups
- **View profile cards** — photo, name, headline, location at a glance
- **Detail modal** — click any card for the full profile (About, Experience, Education, Skills, Certifications, Languages, etc.)
- **Reference number lookup** — retrieve previously scraped profiles by their reference ID
- **Export** — download individual profiles as JSON directly from the detail view

### Task Bucket System

The Task Bucket is a persistent, background task queue designed for automated/unattended scraping:

1. **Add tasks** via the admin UI or API — by name, URL, or structured search
2. **Worker auto-processes** tasks one by one in the background
3. **Configurable rest periods** between tasks (default: 30 seconds) to avoid LinkedIn rate limits
4. **Pause/resume** the worker at any time
5. **Auto-resumes** on server restart — any pending tasks from previous runs continue processing
6. **SSE notifications** broadcast status changes to all connected admins in real-time

---

## 📡 REST API Reference

All endpoints return JSON. Base URL: `http://localhost:5000`

### Scraper Control

<details>
<summary><code>POST /api/scraper/init</code> — Initialize the browser</summary>

**Request Body:**
```json
{
  "headless": true,
  "browser_type": "chromium",
  "session_name": "default"
}
```

**Response:**
```json
{ "success": true, "message": "Browser initialized" }
```
</details>

<details>
<summary><code>POST /api/scraper/login</code> — Log in to LinkedIn</summary>

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "your_password"
}
```

**Response:**
```json
{ "success": true, "message": "Login successful!" }
```
</details>

<details>
<summary><code>GET /api/scraper/stats</code> — Get scraper health & statistics</summary>

**Response:**
```json
{
  "success": true,
  "stats": {
    "requests_made": 42,
    "profiles_scraped": 38,
    "errors": 4,
    "runtime_seconds": 3600.5,
    "is_authenticated": true
  }
}
```
</details>

<details>
<summary><code>POST /api/scraper/search</code> — Search LinkedIn for people</summary>

**Request Body:**
```json
{
  "first_name": "John",
  "last_name": "Doe",
  "company": "Google",
  "max_results": 10
}
```

**Response:**
```json
{
  "success": true,
  "results": [
    {
      "profile_url": "https://www.linkedin.com/in/johndoe",
      "name": "John Doe",
      "profile_picture": "https://media.licdn.com/...",
      "headline": "Software Engineer at Google"
    }
  ],
  "total": 5
}
```
</details>

<details>
<summary><code>POST /api/scraper/search-and-extract</code> — Search & extract all found profiles</summary>

**Request Body:**
```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "company": ""
}
```

**Response (202 Accepted):**
```json
{
  "success": true,
  "status": "started",
  "message": "Scraping started in background. Please check back later."
}
```
</details>

<details>
<summary><code>POST /api/scraper/close</code> — Close the browser</summary>

**Response:**
```json
{ "success": true, "message": "Closed" }
```
</details>

---

### Client API

<details>
<summary><code>POST /api/client/scrape</code> — Submit a search request (auto-queued to Task Bucket)</summary>

**Request Body:**
```json
{ "name": "John Doe" }
```

**Response (cached):**
```json
{
  "success": true,
  "cached": true,
  "profiles": [ { ... } ],
  "total": 3,
  "reference_number": "cached_John Doe"
}
```

**Response (queued — 202):**
```json
{
  "success": true,
  "status": "queued",
  "reference_number": "a1b2c3d4-...",
  "message": "Task queued in the bucket. The worker will process it automatically."
}
```
</details>

<details>
<summary><code>GET /api/client/scrape-status</code> — Poll task status</summary>

**Query Parameters:** `?task_id=...` or `?name=...`

**Response (in progress — 202):**
```json
{
  "success": true,
  "status": "in_progress",
  "message": "Currently scraping LinkedIn profiles…"
}
```

**Response (completed — 200):**
```json
{
  "success": true,
  "status": "completed",
  "profiles": [ { ... } ],
  "total": 3
}
```
</details>

<details>
<summary><code>GET/POST /api/client/retrieve</code> — Retrieve results by return code</summary>

**Query/Body:** `return_code`

**Response:**
```json
{
  "success": true,
  "status": "completed",
  "profile": { ... },
  "csv_url": "/api/client/download/csv?return_code=abc123"
}
```
</details>

<details>
<summary><code>GET/POST /api/client/lookup-by-reference</code> — Retrieve by reference number</summary>

**Query/Body:** `reference_number`

**Response:**
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
</details>

<details>
<summary><code>GET /api/client/download/{format}</code> — Download results</summary>

**Formats:** `csv`, `json`, `pdf`

**Query:** `?return_code=abc123`

**Response:** File download
</details>

---

### Admin API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/approvals` | List all scrape requests (jobs + task bucket) |
| `POST` | `/api/admin/approve` | Retry/re-scrape a failed or stalled job |
| `POST` | `/api/admin/scrape-requested-name` | Manually scrape a specific name |
| `GET` | `/api/admin/db-profiles` | Get all profiles from the master database |
| `GET` | `/api/admin/download-db/json` | Download master database as JSON |
| `GET` | `/api/admin/download-db/csv` | Download master database as CSV |
| `POST` | `/api/admin/destroy-db` | ⚠️ Delete the entire database |
| `GET` | `/api/admin/events` | SSE stream for real-time updates |

---

### Task Bucket API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/bucket/add` | Add name/URL tasks to the queue |
| `POST` | `/api/bucket/add-search` | Add a structured name-based search task |
| `GET` | `/api/bucket/status` | Get full queue status with summary counts |
| `POST` | `/api/bucket/pause` | Pause the background worker |
| `POST` | `/api/bucket/resume` | Resume the background worker |
| `POST` | `/api/bucket/config` | Update worker config (e.g., `rest_seconds`) |
| `POST` | `/api/bucket/remove` | Remove a pending task by ID |
| `POST` | `/api/bucket/clear` | Remove completed/failed tasks from queue |

<details>
<summary>Task Bucket — Add Tasks Example</summary>

```bash
# Add multiple tasks
curl -X POST http://localhost:5000/api/bucket/add \
  -H "Content-Type: application/json" \
  -d '{"queries": ["John Doe", "https://linkedin.com/in/janedoe"], "type": "name"}'

# Add a structured search
curl -X POST http://localhost:5000/api/bucket/add-search \
  -H "Content-Type: application/json" \
  -d '{"first_name": "Jane", "last_name": "Smith", "company": "Google", "max_results": 5}'
```
</details>

<details>
<summary>Task Bucket — Status Response</summary>

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
  "tasks": [ { ... } ]
}
```
</details>

---

### Export API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/scraper/export` | Export data as downloadable JSON or CSV |
| `POST` | `/api/export-text-pdf` | Export raw text as PDF |
| `POST` | `/api/export-profile-pdf` | Export a single profile as a formatted PDF |
| `POST` | `/api/export-bulk-pdf` | Export multiple profiles as a single PDF |

---

### Profile Ranking API

<details>
<summary><code>POST /api/rank</code> — Rank profiles using the scoring model</summary>

**Request Body:**
```json
{
  "profiles": [
    { "name": "...", "headline": "...", "location": "Colombo, Sri Lanka", ... },
    { "name": "...", "headline": "...", "location": "Kandy, Sri Lanka", ... }
  ]
}
```

**Response:**
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
        "connections_count": 500,
        "breakdown": { ... }
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
</details>

---

### Bulk Scraping API (Persona-branded)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/persona/bulk-scrape` | Submit bulk scrape with custom `return_code` |
| `GET/POST` | `/api/persona/bulk-retrieve` | Retrieve bulk scrape results (with 1-min delay policy) |

---

## 📊 Data Schema

Every scraped profile is stored as a JSON object with the following fields:

```json
{
  "name": "Bawantha Beliwaththa",
  "headline": "BSc (Hons) Data Science Undergrad | Developer",
  "location": "Kegalle, Sabaragamuwa, Sri Lanka",
  "connections": "500+ connections",
  "profile_picture": "https://media.licdn.com/...",
  "about": "BSc (Hons) Data Science undergraduate...",
  "current_job": {
    "title": "Project Head",
    "company": "St. Mary's College, Kegalle",
    "duration": "2023 - Present",
    "location": "Kegalle, Sri Lanka"
  },
  "experience": [
    {
      "title": "Project Head",
      "company": "St. Mary's College, Kegalle",
      "duration": "2023 - Present",
      "location": "Kegalle, Sri Lanka"
    }
  ],
  "qualifications": [
    {
      "institution": "University of Hertfordshire",
      "degree": "BSc (Hons) in Data Science",
      "dates": "2024 – 2028"
    }
  ],
  "certifications": [
    {
      "name": "Python for Data Science",
      "issuer": "Coursera",
      "date": "Issued Dec 2023"
    }
  ],
  "skills": [
    { "skill": "Python", "endorsements": "47 endorsements" },
    { "skill": "Data Science", "endorsements": "35 endorsements" }
  ],
  "languages": [
    { "language": "English", "proficiency": "Professional working proficiency" },
    { "language": "Sinhala", "proficiency": "Native or bilingual proficiency" }
  ],
  "volunteer": [
    {
      "role": "Volunteer Developer",
      "organization": "SMC Kegalle Devs Team",
      "duration": "2022 – Present"
    }
  ],
  "honors": [
    {
      "title": "IT Club President Selection",
      "issuer": "St. Mary's College, Kegalle",
      "date": "2021"
    }
  ],
  "recommendations": [
    {
      "recommender": "Jane Doe",
      "title": "Senior Engineer at Google",
      "text": "I had the pleasure of working with..."
    }
  ],
  "profile_url": "https://www.linkedin.com/in/beliwaththa",
  "scraped_at": "2026-06-30T10:15:00.000000"
}
```

---

## 🔧 Module Reference

### `app.py` — Flask Server & Orchestrator

The central application entry point (2500+ lines). Manages all HTTP routes, controls the scraper instance, handles file persistence, runs the Task Bucket worker, and broadcasts SSE events.

**Key Components:**

| Component | Description |
|-----------|-------------|
| `scraper` (global) | Single shared `LinkedInScraper` instance, reused across requests |
| `_bg_loop` | Dedicated `asyncio` event loop running in a daemon thread for non-blocking Playwright operations |
| `run_async(coro)` | Helper to submit async coroutines to the background loop and wait for results |
| `_sse_subscribers` | List of SSE subscriber queues for real-time admin dashboard updates |
| `_broadcast_sse()` | Pushes events to all connected admin browsers |
| Task Bucket Worker | Infinite-loop coroutine that processes queued tasks one by one with rest periods |

**Thread Safety:** Three `threading.Lock` instances protect concurrent access:
- `api_scrape_lock` — guards per-job file writes
- `db_lock` — guards master database reads/writes
- `bucket_lock` — guards task queue file access

---

### `core.py` — LinkedIn Scraper Engine

The heart of the system (1055 lines). Contains the `LinkedInScraper` class that uses Playwright to control a real Chromium browser.

**Extraction Strategy (V4 — Detail Sub-Page Navigation):**

Unlike earlier versions that parsed the main profile page text, V4 navigates to each dedicated detail sub-page:

| Detail Page | URL Pattern | Data Extracted |
|-------------|-------------|----------------|
| Experience | `/details/experience/` | Job titles, companies, durations, locations |
| Education | `/details/education/` | Institutions, degrees, dates |
| Skills | `/details/skills/` | Skill names, endorsement counts |
| Certifications | `/details/certifications/` | Cert names, issuers, dates |
| Honors | `/details/honors/` | Award titles, issuers, dates |
| Languages | `/details/languages/` | Language names, proficiency levels |
| Volunteer | `/details/volunteering-experiences/` | Roles, organizations, durations |
| Recommendations | `/details/recommendations/` | Recommenders, titles, text |

**Anti-Detection Measures:**
- Realistic Chrome 134 user agent string
- `navigator.webdriver` property hidden via init script
- Persistent browser context (not fresh sessions)
- Human-like scrolling with randomized delays

**UI Noise Filtering:**
A comprehensive noise filter (`_is_noise()`) removes 50+ known LinkedIn UI elements (navigation labels, expand buttons, sidebar text, connection badges) from the raw text before parsing.

---

### `ranker.py` — Profile Scoring & Ranking

A weighted scoring model (363 lines) that ranks LinkedIn profiles on a 0–150 point scale:

**Profile Strength (0–100 points):**

| Component | Max Points | Scoring Logic |
|-----------|-----------|---------------|
| Headline | 12 | 8 pts for presence + up to 4 pts for length |
| About | 14 | 8 pts for presence + up to 6 pts for length |
| Experience Count | 15 | 3 pts per experience (max 15) |
| Experience Quality | 8 | Description richness + duration presence |
| Education | 8 | 4 pts per entry (max 8) |
| Skills | 10 | 1 pt per skill (max 10) |
| Certifications | 8 | 2 pts per cert (max 8) |
| Featured | 5 | Binary (has featured content or not) |
| Connections | 6 | Proportional to 500 connections |
| Profile Photo | 4 | Baseline bonus |
| Recommendations | 5 | 2.5 pts each (max 5) |
| Volunteer | 3 | Binary |
| Languages | 2 | 1 pt per language (max 2) |

**Field-Aligned Follower Score (0–50 points):**

Combines connection count (60% weight) with field keyword density (40% weight) across 11 industry categories:

`Software & IT` · `Data & Analytics` · `Finance & Banking` · `Marketing & Sales` · `Healthcare & Medicine` · `Education & Research` · `Engineering & Manufacturing` · `Design & Creative` · `Legal & Compliance` · `Management & Leadership` · `HR & People`

**Tier Labels:**

| Score | Tier | Color |
|-------|------|-------|
| 120+ | 👑 Elite | Purple |
| 100–119 | ⭐ Expert | Green |
| 80–99 | 👍 Strong | Blue |
| 60–79 | 📈 Moderate | Amber |
| < 60 | 🌱 Beginner | Gray |

> **Note:** The ranker currently geo-filters for Sri Lankan profiles only. Profiles without Sri Lanka in their location/headline/about are excluded from ranking results.

---

### `llm_parser.py` — AI Parser (Optional)

An optional AI-powered parsing layer (57 lines). When enabled with an OpenAI API key, it sends raw HTML to GPT-3.5-turbo for structured extraction. Disabled by default (`use_ai=False`). Gracefully degrades if the `openai` package is not installed.

---

### `session_manager.py` — Browser Session Persistence

Handles saving/loading LinkedIn browser session cookies to/from `.pkl` files (52 lines). Allows exporting a logged-in session from one machine and importing it on another.

---

## ⚙ Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | No | OpenAI API key for the optional AI parser |

### Task Bucket Configuration

Configure via `POST /api/bucket/config`:

```json
{ "rest_seconds": 30 }
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `rest_seconds` | `30` | Seconds to wait between processing tasks (rate limiting) |

### Scraper Initialization Options

Passed via `POST /api/scraper/init`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `headless` | `false` | Run browser without visible window |
| `browser_type` | `chromium` | Browser engine (only Chromium supported) |
| `session_name` | `default` | Subfolder inside `browser_data/` for persistent profile |

---

## ⚠ Known Limitations

| Limitation | Description |
|-----------|-------------|
| **LinkedIn Login Required** | A valid, logged-in LinkedIn account is required. Anonymous access returns minimal data. |
| **Rate Limiting** | LinkedIn may temporarily restrict your account if you scrape too many profiles in quick succession. The configurable rest period in the Task Bucket helps, but is not a guarantee. |
| **Contact Info Visibility** | Email, phone, and website are only visible if the profile owner has shared them with your connection level. |
| **LinkedIn DOM Changes** | LinkedIn periodically updates its HTML structure. Selectors may need updating if LinkedIn pushes UI changes. |
| **Section Ordering** | The text parser relies on section headers appearing in a consistent order. A/B tests by LinkedIn may occasionally affect parsing accuracy. |
| **Geo-Filter in Ranker** | The ranking module currently only scores profiles geo-located in Sri Lanka. Non-Sri Lankan profiles are filtered out. |
| **Single Browser Instance** | Only one scraper instance runs at a time. Concurrent scrape requests are queued, not parallelized. |
| **No CAPTCHA Handling** | If LinkedIn presents a CAPTCHA challenge, the scraper will fail. Manual intervention is required. |

---

## 📝 License

This project is for **educational and research purposes only**. Scraping LinkedIn may violate their [Terms of Service](https://www.linkedin.com/legal/user-agreement). Use responsibly and at your own risk.

---

<p align="center">
  <strong>Built with ❤️ using Python, Flask, and Playwright</strong>
</p>
