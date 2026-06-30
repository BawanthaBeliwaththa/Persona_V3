# 🌐 Client Portal Guide

> Documentation for the client-facing profile portal (`client.html`).

---

## Table of Contents

- [Overview](#overview)
- [Accessing the Portal](#accessing-the-portal)
- [Features](#features)
  - [Name Search](#name-search)
  - [Profile Cards](#profile-cards)
  - [Detail Modal](#detail-modal)
  - [Reference Number Lookup](#reference-number-lookup)
  - [Export & Download](#export--download)
- [User Flow Diagrams](#user-flow-diagrams)
  - [First-Time Search Flow](#first-time-search-flow)
  - [Cached Search Flow](#cached-search-flow)
  - [Reference Lookup Flow](#reference-lookup-flow)
- [How Caching Works](#how-caching-works)
- [Status Messages](#status-messages)

---

## Overview

The Client Portal is a clean, read-only interface designed for end-users who need to search and view LinkedIn profiles without needing access to the admin dashboard.

**Key differences from the Admin Dashboard:**
- No scraper controls (can't init/close browser)
- No database management
- No task queue controls
- Simplified search-only interface
- Reference number based tracking

---

## Accessing the Portal

**URL:** `http://localhost:5000` (root URL)

The client page is served by the Flask route:

```python
@app.route('/')
def client_page():
    return render_template('client.html')
```

---

## Features

### Name Search

The primary feature — search for a person by name.

```mermaid
flowchart LR
    A["Enter Name"] --> B["Click Search"]
    B --> C{Cached?}
    C -->|Yes| D["Instant Results<br/>(< 1 second)"]
    C -->|No| E["Queued to Task Bucket<br/>(Reference # issued)"]
    E --> F["Poll Status<br/>(auto-refresh)"]
    F --> G["Results Displayed"]
```

**Input:** Person's name (e.g., "John Doe")

**Behavior:**
1. If the name was previously searched and cached → **instant results**
2. If not cached → task is queued to the Task Bucket, reference number is returned
3. Client polls `/api/client/scrape-status` until results are ready
4. Results are displayed as profile cards

---

### Profile Cards

Search results are displayed as visual profile cards:

| Element | Content |
|---------|---------|
| **Avatar** | Profile picture (or placeholder) |
| **Name** | Full name in bold |
| **Headline** | Professional headline |
| **Location** | Geographic location with icon |
| **View Button** | Opens detailed modal |

---

### Detail Modal

Clicking "View" on any profile card opens a full-screen modal with:

| Section | Content |
|---------|---------|
| **Header** | Large photo, name, headline, location |
| **About** | Full "About" text |
| **Current Position** | Current job title, company, duration |
| **Experience** | All work experience entries |
| **Education** | All education entries |
| **Skills** | Skills list with endorsement counts |
| **Certifications** | Certification names, issuers, dates |
| **Languages** | Languages with proficiency levels |
| **Volunteer** | Volunteer roles and organizations |
| **Honors & Awards** | Award titles, issuers, dates |
| **Recommendations** | Recommender names, titles, and text |

---

### Reference Number Lookup

Every scrape request is assigned a reference number. Users can retrieve results later using this reference.

**Input:** Reference number (e.g., `a1b2c3d4-e5f6-7890-abcd-ef1234567890`)

**Behavior:**
1. Client sends reference number to `/api/client/lookup-by-reference`
2. If completed → displays results
3. If in progress → shows "still scraping" message
4. If not found → shows error

---

### Export & Download

From the detail modal, users can:
- **Download JSON** — full structured profile data
- **Download PDF** — professionally formatted profile report

---

## User Flow Diagrams

### First-Time Search Flow

```mermaid
sequenceDiagram
    participant User as Client User
    participant Portal as Client Portal
    participant API as Flask API
    participant Cache as Name Cache
    participant Bucket as Task Bucket
    participant Worker as Bucket Worker

    User->>Portal: Enter "Jane Smith" → Click Search
    Portal->>API: POST /api/client/scrape {"name": "Jane Smith"}
    API->>Cache: Check name_cache.json
    Cache-->>API: Not found
    API->>Bucket: Add search task
    API-->>Portal: {"status": "queued", "reference_number": "abc-123"}
    
    Portal->>Portal: Show "Queued" message + reference #

    loop Poll every 3 seconds
        Portal->>API: GET /api/client/scrape-status?task_id=abc-123
        API-->>Portal: {"status": "pending"}
        Portal->>Portal: Show "Waiting in queue..."
    end

    Note over Worker: Worker picks task and scrapes

    Portal->>API: GET /api/client/scrape-status?task_id=abc-123
    API-->>Portal: {"status": "completed", "profiles": [...]}
    
    Portal->>Portal: Display profile cards
    
    User->>Portal: Click "View" on a card
    Portal->>Portal: Show detail modal
```

### Cached Search Flow

```mermaid
sequenceDiagram
    participant User as Client User
    participant Portal as Client Portal
    participant API as Flask API
    participant Cache as Name Cache
    participant DB as Master DB

    User->>Portal: Enter "Jane Smith" → Click Search
    Portal->>API: POST /api/client/scrape {"name": "Jane Smith"}
    API->>Cache: Check name_cache.json
    Cache-->>API: Found URLs
    API->>DB: Load profiles by URLs
    DB-->>API: Profile data
    API-->>Portal: {"cached": true, "profiles": [...], "total": 2}
    
    Portal->>Portal: Instantly display profile cards
    
    Note over Portal: Response time: < 500ms
```

### Reference Lookup Flow

```mermaid
sequenceDiagram
    participant User as Client User
    participant Portal as Client Portal
    participant API as Flask API
    participant Bucket as Task Bucket
    participant Jobs as Jobs Registry

    User->>Portal: Enter reference # → Click Lookup
    Portal->>API: GET /api/client/lookup-by-reference?reference_number=abc-123
    
    API->>Bucket: Search queue.json for task_id=abc-123
    
    alt Found in Task Bucket
        alt Status: completed
            API->>API: Load profiles from DB/cache
            API-->>Portal: {"status": "completed", "profiles": [...]}
        else Status: pending/in_progress
            API-->>Portal: {"status": "in_progress", "message": "Still scraping..."}
        end
    else Not in Bucket
        API->>Jobs: Search jobs.json
        alt Found in Jobs
            API->>API: Load per-job file
            API-->>Portal: {"status": "completed", "profiles": [...]}
        else Not Found
            API-->>Portal: {"success": false, "error": "Reference not found"}
        end
    end
```

---

## How Caching Works

```mermaid
graph TD
    subgraph "Write Path (during scrape)"
        S["Scrape completes"] --> W1["Save profile to master DB"]
        S --> W2["Update name_cache.json<br/>name → [profile_urls]"]
    end

    subgraph "Read Path (client search)"
        R["Client searches 'John Doe'"] --> C{Cache hit?}
        C -->|Yes| L["Load profiles by cached URLs<br/>from master DB"]
        L --> RS["Return instantly"]
        C -->|No| Q["Queue to Task Bucket"]
    end

    style RS fill:#10b981,color:#fff
    style Q fill:#f59e0b,color:#fff
```

### Cache File Format

**File:** `exports/name_cache.json`

```json
{
  "Jane Smith": [
    "https://www.linkedin.com/in/janesmith",
    "https://www.linkedin.com/in/jsmith-google"
  ],
  "John Doe": [
    "https://www.linkedin.com/in/johndoe"
  ]
}
```

---

## Status Messages

| Status | Message Shown | User Action |
|--------|--------------|-------------|
| `cached` | Results displayed instantly | Browse profiles |
| `queued` | "Task queued. Reference: ABC-123" | Wait or note reference # |
| `pending` | "Waiting in queue…" | Wait (auto-polls) |
| `in_progress` | "Currently scraping…" | Wait (auto-polls) |
| `completed` | Profile cards displayed | Browse/export |
| `failed` | "No profile found for: ..." | Try different name |
| `error` | "Connection error" | Check server status |
