# 🏗 System Architecture

> Comprehensive architecture documentation for the Persona platform covering component design, data flow, threading model, and system interactions.

---

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [Component Diagram](#component-diagram)
- [Request Flow Diagrams](#request-flow-diagrams)
  - [Single Profile Scrape Flow](#single-profile-scrape-flow)
  - [Client Search Flow](#client-search-flow)
  - [Task Bucket Processing Flow](#task-bucket-processing-flow)
- [Threading & Concurrency Model](#threading--concurrency-model)
- [Data Flow Diagram](#data-flow-diagram)
- [File System Layout](#file-system-layout)
- [SSE Event System](#sse-event-system)
- [Module Dependency Graph](#module-dependency-graph)

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        CP["Client Portal<br/>(client.html)"]
        AD["Admin Dashboard<br/>(index.html)"]
    end

    subgraph "Application Layer"
        FL["Flask Web Server<br/>(app.py)"]
        BW["Task Bucket Worker<br/>(async coroutine)"]
        SSE["SSE Broadcaster"]
    end

    subgraph "Engine Layer"
        SC["LinkedInScraper<br/>(core.py)"]
        RK["Profile Ranker<br/>(ranker.py)"]
        LP["LLM Parser<br/>(llm_parser.py)"]
        SM["Session Manager<br/>(session_manager.py)"]
    end

    subgraph "Browser Layer"
        PW["Playwright Engine"]
        CR["Chromium Browser"]
        LI["LinkedIn.com"]
    end

    subgraph "Storage Layer"
        MDB["Master JSON DB"]
        CSV["Master CSV"]
        JB["Jobs Registry"]
        TQ["Task Queue"]
        NC["Name Cache"]
        BD["Browser Data"]
    end

    CP -->|HTTP| FL
    AD -->|HTTP + SSE| FL
    FL --> SC
    FL --> RK
    FL --> BW
    FL --> SSE
    SSE -->|Server-Sent Events| AD
    BW --> SC
    SC --> PW
    SC --> SM
    PW --> CR
    CR --> LI
    FL --> MDB
    FL --> CSV
    FL --> JB
    FL --> NC
    BW --> TQ
    SC --> BD

    style CP fill:#3b82f6,color:#fff
    style AD fill:#8b5cf6,color:#fff
    style FL fill:#10b981,color:#fff
    style SC fill:#f59e0b,color:#fff
    style RK fill:#ef4444,color:#fff
    style CR fill:#6366f1,color:#fff
```

---

## Component Diagram

```mermaid
classDiagram
    class FlaskApp {
        +scraper: LinkedInScraper
        +_bg_loop: asyncio.EventLoop
        +api_scrape_lock: Lock
        +db_lock: Lock
        +bucket_lock: Lock
        +run_async(coro, timeout)
        +save_to_persistent_db(profile)
        +save_scraped_data_formats(profile, code)
        +_broadcast_sse(event_type, data)
    }

    class LinkedInScraper {
        +headless: bool
        +browser_type: str
        +session_name: str
        +is_authenticated: bool
        +stats: dict
        +page: Page
        +context: BrowserContext
        +initialize()
        +login(email, password)
        +extract_profile(url, _retry)
        +search_people(first, last, company, max)
        +search_and_extract(first, last, company)
        +close()
        -_clean_lines(text)
        -_strip_posts(text)
        -_parse_about(text)
        -_parse_experience(text)
        -_parse_all_experiences(text)
        -_parse_education(text)
        -_parse_certifications(text)
        -_parse_skills(text)
        -_parse_languages(text)
        -_parse_volunteer(text)
        -_parse_honors(text)
        -_parse_recommendations(text)
    }

    class ProfileRanker {
        +rank_sri_lankan_profiles(profiles)
        +score_profile(profile)
        +get_score_tier(score)
        +detect_field_category(profile)
        +is_sri_lankan(profile)
    }

    class LLMParser {
        +use_ai: bool
        +client: OpenAI
        +parse_profile_html(html)
    }

    class SessionManager {
        +sessions_dir: Path
        +save_session(name, cookies)
        +load_session(name)
        +list_sessions()
        +delete_session(name)
    }

    class TaskBucketWorker {
        +_bucket_worker_running: bool
        +_bucket_worker_paused: bool
        +_bucket_worker()
        +_ensure_worker_running()
        +_load_bucket_queue()
        +_save_bucket_queue(tasks)
        +_update_bucket_task(id, kwargs)
    }

    class PDF {
        +header()
        +footer()
    }

    FlaskApp --> LinkedInScraper : controls
    FlaskApp --> ProfileRanker : uses
    FlaskApp --> TaskBucketWorker : manages
    FlaskApp --> PDF : generates
    LinkedInScraper --> LLMParser : optional fallback
    LinkedInScraper --> SessionManager : cookie persistence
    TaskBucketWorker --> LinkedInScraper : uses for scraping
```

---

## Request Flow Diagrams

### Single Profile Scrape Flow

```mermaid
sequenceDiagram
    participant Admin as Admin Browser
    participant Flask as Flask Server
    participant BG as Background Loop
    participant Scraper as LinkedInScraper
    participant LinkedIn as LinkedIn.com
    participant DB as File Storage

    Admin->>Flask: POST /api/scraper/init
    Flask->>BG: run_async(init())
    BG->>Scraper: initialize()
    Scraper->>LinkedIn: Navigate to /feed/
    Scraper-->>BG: Authenticated ✓
    BG-->>Flask: success
    Flask-->>Admin: {"success": true}

    Admin->>Flask: POST /api/scraper/search<br/>{"first_name": "John"}
    Flask->>BG: run_async(search_people())
    BG->>Scraper: search_people("John", "")
    Scraper->>LinkedIn: Navigate to search URL
    Scraper->>LinkedIn: Scroll & extract results
    Scraper-->>BG: [{profile_url, name, ...}]
    BG-->>Flask: results
    Flask-->>Admin: {"results": [...]}

    Admin->>Flask: POST /api/scraper/search-and-extract
    Flask->>BG: background_search_and_extract()
    Flask-->>Admin: {"status": "started"} (202)
    
    BG->>Scraper: search_people()
    Scraper->>LinkedIn: Search results
    
    loop For each found profile
        BG->>Scraper: extract_profile(url)
        Scraper->>LinkedIn: Navigate to profile
        Scraper->>LinkedIn: Visit /details/experience/
        Scraper->>LinkedIn: Visit /details/education/
        Scraper->>LinkedIn: Visit /details/skills/
        Scraper->>LinkedIn: Visit other detail pages
        Scraper-->>BG: Structured profile data
        BG->>DB: save_to_persistent_db()
        BG->>Flask: _broadcast_sse("new_scrape")
        Flask-->>Admin: SSE: new profile scraped
    end

    BG->>DB: Update name_cache.json
    BG->>DB: Update jobs.json → completed
```

### Client Search Flow

```mermaid
sequenceDiagram
    participant Client as Client Browser
    participant Flask as Flask Server
    participant Cache as Name Cache
    participant Bucket as Task Bucket
    participant Worker as Bucket Worker
    participant Scraper as LinkedInScraper
    participant DB as Master DB

    Client->>Flask: POST /api/client/scrape<br/>{"name": "Jane Smith"}
    Flask->>Cache: Check name_cache.json
    
    alt Cache HIT
        Cache-->>Flask: Cached URLs found
        Flask->>DB: Load matching profiles
        DB-->>Flask: Profile data
        Flask-->>Client: {"cached": true, "profiles": [...]}
    else Cache MISS
        Flask->>Bucket: Add task to queue.json
        Flask->>Worker: _ensure_worker_running()
        Flask-->>Client: {"status": "queued", "reference_number": "abc-123"}
        
        Client->>Flask: GET /api/client/scrape-status?task_id=abc-123
        Flask-->>Client: {"status": "pending"}
        
        Worker->>Bucket: Pick next pending task
        Worker->>Scraper: search_people() + extract_profile()
        Scraper-->>Worker: Profile data
        Worker->>DB: save_to_persistent_db()
        Worker->>Cache: Update name_cache.json
        Worker->>Bucket: Mark task completed
        
        Client->>Flask: GET /api/client/scrape-status?task_id=abc-123
        Flask->>DB: Load profiles by cached URLs
        Flask-->>Client: {"status": "completed", "profiles": [...]}
    end
```

### Task Bucket Processing Flow

```mermaid
flowchart TD
    A[Task Added to Queue] --> B{Worker Running?}
    B -->|No| C[Start Worker Coroutine]
    B -->|Yes| D{Worker Paused?}
    C --> D
    D -->|Yes| E[Sleep 2s & Recheck]
    E --> D
    D -->|No| F{Pending Tasks?}
    F -->|No| G[Sleep 3s & Recheck]
    G --> F
    F -->|Yes| H[Pick First Pending Task]
    
    H --> I{Task Type?}
    
    I -->|search| J["Search LinkedIn<br/>Extract all found profiles"]
    I -->|url| K["Extract profile<br/>from specific URL"]
    I -->|name| L["Search by name<br/>Extract first match"]
    
    J --> M{Success?}
    K --> M
    L --> M
    
    M -->|Yes| N["Save to DB<br/>Update cache<br/>Update jobs.json<br/>Broadcast SSE"]
    M -->|No| O["Mark task failed<br/>Log error<br/>Broadcast SSE"]
    
    N --> P[Rest Period<br/>Default: 30 seconds]
    O --> P
    
    P --> D

    style A fill:#3b82f6,color:#fff
    style N fill:#10b981,color:#fff
    style O fill:#ef4444,color:#fff
    style P fill:#f59e0b,color:#fff
```

---

## Threading & Concurrency Model

```mermaid
graph LR
    subgraph "Main Thread"
        FT["Flask HTTP Handler<br/>(synchronous)"]
    end
    
    subgraph "Background Thread"
        BL["asyncio Event Loop<br/>(_bg_loop.run_forever)"]
    end
    
    subgraph "Async Coroutines (on _bg_loop)"
        PW["Playwright Operations<br/>(browser, page)"]
        BK["Bucket Worker<br/>(_bucket_worker)"]
        BS["Background Scrapes<br/>(perform_background_scrape)"]
    end

    FT -->|"run_async(coro)"| BL
    FT -->|"asyncio.run_coroutine_threadsafe()"| BL
    BL --> PW
    BL --> BK
    BL --> BS

    style FT fill:#3b82f6,color:#fff
    style BL fill:#10b981,color:#fff
    style PW fill:#f59e0b,color:#fff
    style BK fill:#8b5cf6,color:#fff
```

### How It Works

1. **Flask runs on the main thread** — handles all HTTP requests synchronously
2. **A dedicated asyncio event loop** (`_bg_loop`) runs in a daemon thread started at module load
3. **`run_async(coro, timeout)`** submits a coroutine to `_bg_loop` and blocks until the result is ready (for synchronous API responses)
4. **`asyncio.run_coroutine_threadsafe(coro, _bg_loop)`** fires and forgets a coroutine (for background operations that return 202 immediately)
5. **Three locks** protect shared state:

| Lock | Protects | Used By |
|------|----------|---------|
| `api_scrape_lock` | Per-job JSON/CSV files, jobs.json | save_scraped_data_formats, create_job, update_job_status |
| `db_lock` | Master database (all_scraped_profiles.json/csv), name_cache.json | save_to_persistent_db, client search endpoints |
| `bucket_lock` | Task queue (queue.json) | _load_bucket_queue, _save_bucket_queue |

---

## Data Flow Diagram

```mermaid
flowchart TD
    subgraph "Input Sources"
        A1["Admin: Single URL"]
        A2["Admin: Bulk URLs"]
        A3["Client: Name Search"]
        A4["Bucket: Name/URL Task"]
        A5["API: Persona Bulk"]
    end

    subgraph "Processing"
        S1["LinkedInScraper.search_people()"]
        S2["LinkedInScraper.extract_profile()"]
        S3["Detail Page Navigation<br/>(8 sub-pages)"]
        S4["Section Parsers<br/>(11 parsers)"]
    end

    subgraph "Storage"
        D1["exports/all_scraped_profiles.json<br/>(Master JSON)"]
        D2["exports/all_scraped_profiles.csv<br/>(Master CSV)"]
        D3["exports/api_scrapes/{id}.json<br/>(Per-job JSON)"]
        D4["exports/api_scrapes/{id}.csv<br/>(Per-job CSV)"]
        D5["exports/name_cache.json<br/>(Search cache)"]
        D6["exports/api_scrapes/jobs.json<br/>(Job registry)"]
        D7["exports/task_bucket/queue.json<br/>(Task queue)"]
    end

    subgraph "Output"
        O1["JSON API Response"]
        O2["CSV Download"]
        O3["PDF Report"]
        O4["SSE Live Update"]
    end

    A1 --> S2
    A2 --> S2
    A3 --> S1
    A4 --> S1
    A5 --> S2
    S1 --> S2
    S2 --> S3
    S3 --> S4
    S4 --> D1
    S4 --> D2
    S4 --> D3
    S4 --> D4
    A3 --> D5
    A4 --> D7
    S4 --> D6
    D1 --> O1
    D3 --> O1
    D1 --> O2
    D3 --> O3
    D6 --> O4

    style S2 fill:#f59e0b,color:#fff
    style D1 fill:#3b82f6,color:#fff
    style O4 fill:#8b5cf6,color:#fff
```

---

## File System Layout

```mermaid
graph TD
    ROOT["persona/"] --> SRC["Source Files"]
    ROOT --> TMPL["templates/"]
    ROOT --> EXP["exports/ (runtime)"]
    ROOT --> BD["browser_data/ (runtime)"]
    ROOT --> TB["exports/task_bucket/ (runtime)"]

    SRC --> APP["app.py<br/>2522 lines"]
    SRC --> CORE["core.py<br/>1055 lines"]
    SRC --> RANK["ranker.py<br/>363 lines"]
    SRC --> LLM["llm_parser.py<br/>57 lines"]
    SRC --> SESS["session_manager.py<br/>52 lines"]
    SRC --> REQ["req.txt"]

    TMPL --> IDX["index.html<br/>Admin Dashboard<br/>1672 lines"]
    TMPL --> CLI["client.html<br/>Client Portal"]

    EXP --> APJ["all_scraped_profiles.json"]
    EXP --> APC["all_scraped_profiles.csv"]
    EXP --> NC["name_cache.json"]
    EXP --> API["api_scrapes/"]

    API --> JOBS["jobs.json"]
    API --> IDJS["{id}.json"]
    API --> IDCSV["{id}.csv"]

    TB --> QJ["queue.json"]
    TB --> CFG["config.json"]

    BD --> DEF["default/<br/>Chromium cookies & storage"]

    style ROOT fill:#6366f1,color:#fff
    style APP fill:#10b981,color:#fff
    style CORE fill:#f59e0b,color:#fff
    style IDX fill:#3b82f6,color:#fff
```

---

## SSE Event System

The admin dashboard receives real-time updates via Server-Sent Events. The server maintains a list of subscriber queues and broadcasts events to all connected clients.

```mermaid
sequenceDiagram
    participant Browser1 as Admin Browser 1
    participant Browser2 as Admin Browser 2
    participant Flask as Flask Server
    participant Worker as Task Bucket Worker

    Browser1->>Flask: GET /api/admin/events
    Note over Flask: Create queue, add to _sse_subscribers
    Flask-->>Browser1: SSE: {"type": "connected"}

    Browser2->>Flask: GET /api/admin/events
    Flask-->>Browser2: SSE: {"type": "connected"}

    Worker->>Flask: _broadcast_sse("bucket_update", {...})
    Flask-->>Browser1: SSE: {"type": "bucket_update", ...}
    Flask-->>Browser2: SSE: {"type": "bucket_update", ...}

    Worker->>Flask: _broadcast_sse("new_scrape", {...})
    Flask-->>Browser1: SSE: {"type": "new_scrape", ...}
    Flask-->>Browser2: SSE: {"type": "new_scrape", ...}

    Note over Flask: Every 25s: keepalive ping
    Flask-->>Browser1: : ping
    Flask-->>Browser2: : ping
```

### SSE Event Types

| Event Type | Payload | Trigger |
|-----------|---------|---------|
| `connected` | `{}` | Browser connects to SSE endpoint |
| `request_started` | `{name}` | New search-and-extract request begins |
| `new_scrape` | `{name, count}` | A profile was successfully scraped |
| `bucket_tasks_added` | `{count, query}` | New tasks added to the bucket |
| `bucket_update` | `{task_id, status, query, ...}` | Task status changed |
| `bucket_rest` | `{seconds}` | Worker entering rest period |
| `bucket_paused` | `{}` | Worker paused |
| `bucket_resumed` | `{}` | Worker resumed |
| `bucket_cleared` | `{removed}` | Completed/failed tasks cleared |

---

## Module Dependency Graph

```mermaid
graph TD
    APP["app.py"] --> CORE["core.py"]
    APP --> RANK["ranker.py"]
    APP --> FLASK["flask"]
    APP --> ASYNCIO["asyncio"]
    APP --> THREADING["threading"]
    APP --> FPDF["fpdf (PDF class)"]
    APP --> JSON["json"]
    APP --> CSV["csv"]

    CORE --> PW["playwright"]
    CORE --> ASYNCIO
    CORE --> RE["re"]
    CORE --> PATHLIB["pathlib"]

    RANK --> RE

    LLM["llm_parser.py"] --> OPENAI["openai (optional)"]
    LLM --> JSON

    SESS["session_manager.py"] --> PICKLE["pickle"]
    SESS --> PATHLIB

    style APP fill:#10b981,color:#fff
    style CORE fill:#f59e0b,color:#fff
    style RANK fill:#ef4444,color:#fff
    style PW fill:#6366f1,color:#fff
```

> **Note:** `llm_parser.py` and `session_manager.py` are not currently imported by `app.py` in V4 but remain available as utilities. The scraper engine (`core.py`) handles browser persistence directly via Playwright's persistent context.
