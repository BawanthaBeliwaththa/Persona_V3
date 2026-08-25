"""
PERSONA V3 — Core Microservice API
==================================
High-performance ASGI Backend powered by FastAPI and Uvicorn.
Provides dedicated endpoints for Zoho CRM / Zoho Flow integration:
  - Search & Single Scrapes
  - Real-Time Tracking & Reference Lookups
  - Bulk Search & Batch Retrieval
  - Task Bucket / Basket Queue Management
  - Scraper Session & Authentication Control
"""

import sys
import asyncio

# On Windows, Playwright subprocesses require ProactorEventLoop
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from contextlib import asynccontextmanager
from datetime import datetime
import io
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

from async_bridge import run_scraper_coro
from cleaner import (
    clean_profile,
    format_certifications_for_csv,
    format_current_job_for_csv,
    format_education_for_csv,
    format_experience_for_csv,
    format_skills_for_csv,
    sanitize_profile,
)
from core import LinkedInScraper
from ranker import rank_sri_lankan_profiles, score_profile
from storage import (
    ALL_PROFILES_CSV,
    ALL_PROFILES_JSON,
    API_SCRAPES_DIR,
    EXPORTS_DIR,
    NAME_CACHE_FILE,
    clear_master_db,
    create_job,
    get_all_master_profiles,
    get_jobs_data,
    get_name_cache,
    load_bucket_config,
    load_bucket_queue,
    save_bucket_config,
    save_bucket_queue,
    save_to_master_db,
    update_bucket_task,
    update_job_status,
)
from worker import (
    ensure_worker_running,
    get_scraper_instance,
    is_worker_paused,
    is_worker_running,
    pause_worker,
    resume_worker,
    set_scraper_instance,
    shutdown_worker,
)


# ── Lifespan Manager ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    print("==================================================")
    print("  PERSONA V3 — FastAPI / Uvicorn Backend Starting ")
    print("==================================================")

    # Reset any tasks stuck as 'in_progress' from a previous crashed session.
    # These will never complete without the worker, so mark them failed on startup.
    try:
        from storage import load_bucket_queue, save_bucket_queue
        q = load_bucket_queue()
        stale = [t for t in q if t.get("status") == "in_progress"]
        if stale:
            for t in stale:
                t["status"] = "failed"
                t["error"] = "Stale: server was restarted while task was running"
            save_bucket_queue(q)
            print(f"[Startup] Reset {len(stale)} stale in_progress task(s) to failed.")
    except Exception as e:
        print(f"[Startup] Stale task cleanup notice: {e}")

    ensure_worker_running()
    yield
    print("[Shutdown] Terminating background workers and browser sessions...")
    await shutdown_worker()
    print("[Shutdown] Completed cleanly.")


# ── FastAPI App Setup ───────────────────────────────────────────────────────
app = FastAPI(
    title="Persona V3 — LinkedIn Intelligence API",
    description="Dedicated ASGI backend service for Zoho CRM / Zoho Flow integration.",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for Zoho CRM, Zoho Creator, and external origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Request Schemas ─────────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    name: Optional[str] = Field(None, description="Candidate name (e.g. 'Bawantha Beliwaththa'), username handle (e.g. 'beliwaththa'), or general query")
    username: Optional[str] = Field(None, description="Direct LinkedIn handle / username (e.g. 'beliwaththa')")
    first_name: Optional[str] = Field(None, description="Candidate first name")
    last_name: Optional[str] = Field(None, description="Candidate last name")
    company: Optional[str] = Field(None, description="Company filter (e.g. 'TechCorp')")
    profile_url: Optional[str] = Field(None, description="Direct LinkedIn profile URL")


def normalize_client_scrape_query(req: ScrapeRequest) -> Dict[str, Any]:
    """
    Intelligently determines whether the input is a direct URL, a username slug,
    or a structured first/last name search with optional company.
    """
    # 1. Direct profile URL
    if req.profile_url and req.profile_url.strip():
        url = req.profile_url.strip()
        if not url.startswith("http"):
            url = f"https://www.linkedin.com/in/{url.lstrip('/')}"
        return {
            "type": "url",
            "url": url,
            "query": url,
            "username": "",
            "search_params": {},
            "display_name": url
        }

    # 2. Direct username field
    if req.username and req.username.strip():
        slug = req.username.strip().lstrip('@').replace('linkedin.com/in/', '').strip('/')
        url = f"https://www.linkedin.com/in/{slug}"
        return {
            "type": "url",
            "url": url,
            "query": f"@{slug}",
            "username": slug,
            "search_params": {},
            "display_name": f"@{slug}"
        }

    # 3. Explicit first_name / last_name / company
    if (req.first_name and req.first_name.strip()) or (req.last_name and req.last_name.strip()):
        fn = (req.first_name or "").strip()
        ln = (req.last_name or "").strip()
        co = (req.company or "").strip()
        query_str = f"{fn} {ln}".strip()
        return {
            "type": "search",
            "url": "",
            "query": query_str,
            "username": "",
            "search_params": {"first_name": fn, "last_name": ln, "company": co, "max_results": 1},
            "display_name": f"{query_str} ({co})" if co else query_str
        }

    # 4. Parse from generic 'name' field
    raw_name = (req.name or "").strip()
    if not raw_name:
        return {}

    # Is it a direct profile URL?
    if raw_name.startswith("http") or "linkedin.com/in/" in raw_name:
        url = raw_name if raw_name.startswith("http") else f"https://{raw_name}"
        return {
            "type": "url",
            "url": url,
            "query": url,
            "username": "",
            "search_params": {},
            "display_name": url
        }

    # Treat name queries as structured search for the primary matching candidate
    clean_name = raw_name.lstrip('@')
    parts = clean_name.split()
    fn = parts[0] if parts else ""
    ln = " ".join(parts[1:]) if len(parts) > 1 else ""
    co = (req.company or "").strip()
    return {
        "type": "search",
        "url": "",
        "query": clean_name,
        "username": "",
        "search_params": {"first_name": fn, "last_name": ln, "company": co, "max_results": 1},
        "display_name": f"{clean_name} ({co})" if co else clean_name
    }


class SearchRequest(BaseModel):
    first_name: Optional[str] = Field("", description="First name")
    last_name: Optional[str] = Field("", description="Last name")
    company: Optional[str] = Field("", description="Target company")
    max_results: Optional[int] = Field(1, description="Maximum number of search results to return (default 1)")


class ContactInfoRequest(BaseModel):
    profile_url: str = Field(..., description="LinkedIn profile URL to fetch contact info for")


class BulkScrapeRequest(BaseModel):
    profile_urls: List[str] = Field(..., description="List of profile URLs or names to scrape")
    return_code: str = Field(..., description="Unique tracking reference for this bulk job")


class BucketAddRequest(BaseModel):
    query: Optional[str] = Field(None, description="Single query or profile URL")
    queries: Optional[List[str]] = Field(None, description="List of queries or profile URLs")
    type: Optional[str] = Field("name", description="'name' or 'url'")


class BucketAddSearchRequest(BaseModel):
    first_name: Optional[str] = Field("", description="First name")
    last_name: Optional[str] = Field("", description="Last name")
    company: Optional[str] = Field("", description="Target company")
    max_results: Optional[int] = Field(5, description="Maximum results to scrape")


class BucketConfigRequest(BaseModel):
    rest_seconds: int = Field(30, ge=0, description="Rest period in seconds between tasks")


class BucketRemoveRequest(BaseModel):
    task_id: str = Field(..., description="ID of pending task to remove")


class BucketClearRequest(BaseModel):
    all: Optional[bool] = Field(False, description="Clear all tasks if True, otherwise only completed and failed")


class ReferenceLookupRequest(BaseModel):
    reference_number: str = Field(..., description="Job reference number or task ID")


class ScraperLoginRequest(BaseModel):
    email: str = Field(..., description="LinkedIn email")
    password: str = Field(..., description="LinkedIn password")


class ScraperCookieLoginRequest(BaseModel):
    cookie_value: str = Field(..., description="Value of li_at cookie")


class ScraperPinRequest(BaseModel):
    pin: str = Field(..., description="Verification PIN code received via email/SMS")


# ── Root & Health ───────────────────────────────────────────────────────────
@app.get("/", tags=["System"])
async def root():
    return {
        "service": "Persona V3 Intelligence API",
        "status": "online",
        "worker_running": is_worker_running(),
        "worker_paused": is_worker_paused(),
        "docs": "/docs",
        "guide": "/guide",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/guide", response_class=FileResponse, tags=["System"])
async def interactive_guide():
    """Serve the complete interactive HTML technical manual & guide."""
    guide_path = Path(__file__).parent / "guide.html"
    if guide_path.exists():
        return FileResponse(guide_path, media_type="text/html")
    raise HTTPException(status_code=404, detail="Guide HTML file not found.")


# ============================================================================
# 1. SEARCH & SCRAPE ENDPOINTS
# ============================================================================

@app.api_route("/api/client/scrape", methods=["GET", "POST"], status_code=status.HTTP_202_ACCEPTED, tags=["Search"])
async def client_scrape(
    request: Request,
    req: Optional[ScrapeRequest] = None,
    name: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    candidate_name: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    first_name: Optional[str] = Query(None),
    last_name: Optional[str] = Query(None),
    company: Optional[str] = Query(None),
    profile_url: Optional[str] = Query(None),
    url: Optional[str] = Query(None),
):
    """
    Primary Zoho integration endpoint.
    Supports both POST (JSON / form-data) and GET (query params).
    Accepts candidate name, username handle, first/last name with optional company, or direct profile URL.
    1. If GET request has no params, returns API service status & endpoint directory.
    2. Normalizes input and checks cache for instant return.
    3. Enqueues to Task Bucket queue and returns reference_number.
    """
    # If GET request with no parameters, return informative status & documentation overview
    if request.method == "GET" and not any([name, query, candidate_name, username, first_name, last_name, company, profile_url, url]):
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Persona V3 Scrape API is online and operational.",
                "service": "FastAPI / Uvicorn ASGI Backend",
                "endpoints": {
                    "scrape": "POST /api/client/scrape (or GET with ?name=...)",
                    "scrape_status": "GET /api/client/scrape-status?task_id={reference_number}",
                    "retrieve_profile": "GET/POST /api/client/retrieve?return_code={reference_number}",
                    "lookup_by_reference": "GET/POST /api/client/lookup-by-reference?reference_number={reference_number}",
                    "bulk_scrape": "POST /api/persona/bulk-scrape",
                    "bulk_retrieve": "GET/POST /api/persona/bulk-retrieve?return_code={return_code}",
                    "docs": "/docs",
                    "guide": "/guide",
                },
                "example_usage": {
                    "curl_post": "curl -X POST http://localhost:8000/api/client/scrape -H 'Content-Type: application/json' -d '{\"name\": \"Bawantha Beliwaththa\", \"company\": \"TechCorp\"}'",
                    "browser_get": "http://localhost:8000/api/client/scrape?name=Bawantha+Beliwaththa"
                }
            }
        )

    # Build or parse ScrapeRequest
    if req is None:
        if request.method == "POST":
            try:
                body = await request.json()
                req = ScrapeRequest(**body)
            except Exception:
                pass

    if req is None:
        req = ScrapeRequest(
            name=name or query or candidate_name,
            username=username,
            first_name=first_name,
            last_name=last_name,
            company=company,
            profile_url=profile_url or url,
        )

    parsed = normalize_client_scrape_query(req)
    if not parsed:
        raise HTTPException(status_code=400, detail="Please provide a valid 'name', 'username', 'first_name', or 'profile_url'.")

    query_str = parsed["query"]
    query_lower = query_str.lower()
    task_type = parsed["type"]
    url_target = parsed.get("url", "")
    username_slug = parsed.get("username", "")
    search_params = parsed.get("search_params", {})
    display_name = parsed.get("display_name", query_str)

    # 1. Check name cache first
    name_cache = get_name_cache()
    matched_key = next((k for k in name_cache.keys() if k.lower() == query_lower or (username_slug and k.lower() == username_slug.lower())), None)
    if matched_key:
        cached_urls = name_cache[matched_key]
        master_profiles = get_all_master_profiles()
        results = [p for p in master_profiles if p.get("profile_url") in cached_urls]
        if results:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "cached": True,
                    "status": "completed",
                    "profiles": results,
                    "total": len(results),
                    "reference_number": f"cached_{matched_key}",
                }
            )

    # 2. Check if already queued or in progress
    existing_tasks = load_bucket_queue()
    for t in existing_tasks:
        t_q = (t.get("query") or "").lower()
        if (t_q == query_lower or (username_slug and t_q == f"@{username_slug}".lower())) and t.get("status") in ("pending", "in_progress"):
            return JSONResponse(
                status_code=202,
                content={
                    "success": True,
                    "status": t["status"],
                    "reference_number": t["id"],
                    "message": "Already queued in the bucket. Check back soon.",
                }
            )

    # 3. Add new task to bucket queue
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "query": query_str,
        "type": task_type,
        "username": username_slug,
        "search_params": search_params,
        "status": "pending",
        "added_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "result_name": "",
        "result_url": url_target,
        "profiles_found": 0,
        "error": None,
        "_client_name": display_name,
    }

    existing_tasks.append(task)
    save_bucket_queue(existing_tasks)
    ensure_worker_running()

    return {
        "success": True,
        "status": "queued",
        "reference_number": task_id,
        "message": f"Task queued for {display_name}. The worker will process it sequentially.",
    }


@app.post("/api/scraper/search", tags=["Search"])
async def scraper_search(req: SearchRequest):
    """Direct search for people profiles on LinkedIn."""
    scraper = get_scraper_instance()
    if not scraper or not scraper.is_authenticated:
        raise HTTPException(status_code=400, detail="Scraper is not authenticated. Please initialize and login.")

    max_res = max(1, req.max_results or 1)
    results = await run_scraper_coro(scraper.search_people(
        first_name=req.first_name or "",
        last_name=req.last_name or "",
        company=req.company or "",
        max_results=max_res,
    ), locked=True)
    return {"success": True, "results": results, "total": len(results)}


@app.post("/api/scraper/search-and-extract", tags=["Search"])
async def scraper_search_and_extract(req: SearchRequest):
    """Direct search and immediate profile extraction for top matches, processed strictly one-by-one."""
    scraper = get_scraper_instance()
    if not scraper or not scraper.is_authenticated:
        raise HTTPException(status_code=400, detail="Scraper is not authenticated. Please initialize and login.")

    max_res = max(1, req.max_results or 1)
    results = await run_scraper_coro(scraper.search_people(
        first_name=req.first_name or "",
        last_name=req.last_name or "",
        company=req.company or "",
        max_results=max_res,
    ), locked=True)
    if not results:
        return {"success": False, "error": "No matching profiles found."}

    extracted_profiles = []
    for idx, sr in enumerate(results):
        print(f"[Search & Extract] Scraping profile {idx+1}/{len(results)}: {sr.get('name')} ({sr.get('profile_url')})")
        profile = await run_scraper_coro(scraper.extract_profile(sr["profile_url"]), locked=True)
        if "error" not in profile and profile.get("name"):
            profile["scraped_at"] = datetime.now().isoformat()
            save_to_master_db(profile)
            extracted_profiles.append(profile)
        if idx < len(results) - 1:
            await asyncio.sleep(4)  # Safe delay between sequential profile extractions

    return {"success": bool(extracted_profiles), "profiles": extracted_profiles, "total": len(extracted_profiles)}


@app.post("/api/scraper/search-contact-info", tags=["Search"])
async def scraper_search_contact_info(req: ContactInfoRequest):
    """Direct extraction of contact information for a profile URL."""
    scraper = get_scraper_instance()
    if not scraper or not scraper.is_authenticated:
        raise HTTPException(status_code=400, detail="Scraper is not authenticated.")

    contact_info = await run_scraper_coro(scraper.extract_contact_info(req.profile_url), locked=True)
    return {"success": True, "profile_url": req.profile_url, "contact_info": contact_info}


# ============================================================================
# 2. TRACK & STATUS ENDPOINTS
# ============================================================================

@app.get("/api/client/scrape-status", tags=["Track"])
async def client_scrape_status(
    task_id: Optional[str] = Query(None, description="Task ID or Reference Number"),
    name: Optional[str] = Query(None, description="Candidate name")
):
    """
    Poll the bucket queue for a task by task_id or name (100% Case-Insensitive).
    Returns real-time queue position or completed profile data.
    """
    if not task_id and not name:
        raise HTTPException(status_code=400, detail="task_id or name is required.")

    task_id_lower = task_id.strip().lower() if task_id else ""
    name_lower = name.strip().lower() if name else ""

    tasks = load_bucket_queue()
    task = None
    if task_id_lower:
        task = next((t for t in tasks if t["id"].lower() == task_id_lower), None)
    if not task and name_lower:
        task = next((t for t in tasks if (t.get("_client_name") or t.get("query") or "").lower() == name_lower), None)

    if not task:
        # Check master DB & name cache
        all_profiles = get_all_master_profiles()
        name_cache = get_name_cache()
        matched_key = next((k for k in name_cache.keys() if k.lower() == name_lower), None) if name_lower else None
        if matched_key:
            cached_urls = name_cache[matched_key]
            results = [p for p in all_profiles if p.get("profile_url") in cached_urls]
            if results:
                return {"success": True, "status": "completed", "profiles": results, "total": len(results)}

        raise HTTPException(status_code=404, detail="Task not found in queue or cache.")

    current_status = task["status"]

    if current_status in ("pending", "in_progress"):
        pending_or_active = [t for t in tasks if t["status"] in ("pending", "in_progress")]
        queue_total = len(pending_or_active)
        queue_position = 0
        for i, t in enumerate(pending_or_active):
            if t["id"].lower() == task["id"].lower():
                queue_position = i + 1
                break

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "success": True,
                "status": current_status,
                "queue_position": queue_position,
                "queue_total": queue_total,
                "message": "Queued in Task Bucket" if current_status == "pending" else "Currently scraping LinkedIn profile...",
            }
        )

    if current_status == "failed":
        return {
            "success": False,
            "status": "failed",
            "error": task.get("error", "Scraping failed."),
        }

    if current_status == "completed":
        t_id = task.get("id")
        if t_id:
            json_path = API_SCRAPES_DIR / f"{t_id}.json"
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, dict) and "profiles" in raw:
                        t_profiles = raw["profiles"]
                    elif isinstance(raw, list):
                        t_profiles = raw
                    elif isinstance(raw, dict):
                        t_profiles = [raw]
                    else:
                        t_profiles = []
                    if t_profiles:
                        return {"success": True, "status": "completed", "profiles": t_profiles, "total": len(t_profiles)}
                except Exception:
                    pass

        # Fallback to master DB
        search_name = task.get("_client_name") or task.get("query", name or "")
        search_lower = search_name.lower()
        all_profiles = get_all_master_profiles()
        results = [p for p in all_profiles if search_lower in (p.get("name") or "").lower()]
        return {"success": True, "status": "completed", "profiles": results, "total": len(results)}

    return {"success": False, "status": current_status, "error": "Unknown status"}


@app.api_route("/api/client/lookup-by-reference", methods=["GET", "POST"], tags=["Track"])
async def client_lookup_by_reference(
    request: Request,
    reference_number: Optional[str] = Query(None)
):
    """Lookup scraped profile by reference number (supports both GET and POST)."""
    ref = reference_number
    if request.method == "POST":
        try:
            body = await request.json()
            ref = body.get("reference_number") or ref
        except Exception:
            pass

    if not ref:
        raise HTTPException(status_code=400, detail="reference_number is required.")

    ref = ref.strip().lstrip("#")

    # 1. Check jobs registry
    jobs = get_jobs_data()
    if ref in jobs:
        job = jobs[ref]
        st = job.get("status")
        if st == "in_progress":
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "success": False,
                    "status": "in_progress",
                    "reference_number": ref,
                    "person_name": job.get("person_name", ""),
                    "message": "Profile is still being scraped.",
                }
            )
        elif st == "failed":
            return {
                "success": False,
                "status": "failed",
                "reference_number": ref,
                "error": job.get("error", "Job failed."),
            }
        elif st == "completed":
            json_path = API_SCRAPES_DIR / f"{ref}.json"
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                    profiles_list = raw_data.get("profiles", [raw_data]) if isinstance(raw_data, dict) else raw_data
                    return {
                        "success": True,
                        "status": "completed",
                        "reference_number": ref,
                        "profiles": profiles_list,
                        "total": len(profiles_list),
                    }
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Error reading profile data: {e}")

    # 2. Check bucket tasks
    tasks = load_bucket_queue()
    task = next((t for t in tasks if t["id"] == ref), None)
    if task:
        st = task.get("status", "pending")
        if st == "completed":
            json_path = API_SCRAPES_DIR / f"{ref}.json"
            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                profiles_list = raw_data.get("profiles", [raw_data]) if isinstance(raw_data, dict) else raw_data
                return {
                    "success": True,
                    "status": "completed",
                    "reference_number": ref,
                    "profiles": profiles_list,
                    "total": len(profiles_list),
                }
        elif st == "failed":
            return {"success": False, "status": "failed", "reference_number": ref, "error": task.get("error")}
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"success": False, "status": st, "reference_number": ref, "message": f"Task is currently {st}."}
        )

    raise HTTPException(status_code=404, detail="No scrape request found for the provided reference number.")


@app.api_route("/api/client/retrieve", methods=["GET", "POST"], tags=["Track"])
async def client_retrieve(
    request: Request,
    return_code: Optional[str] = Query(None)
):
    """Retrieve single job result by return_code."""
    rc = return_code
    if request.method == "POST":
        try:
            body = await request.json()
            rc = body.get("return_code") or rc
        except Exception:
            pass

    if not rc:
        raise HTTPException(status_code=400, detail="return_code is required.")

    jobs = get_jobs_data()
    if rc not in jobs:
        raise HTTPException(status_code=404, detail="No job found for the given return_code.")

    job = jobs[rc]
    st = job.get("status")
    if st == "in_progress":
        return {"success": False, "status": "in_progress", "message": "Scrape in progress."}
    elif st == "failed":
        return {"success": False, "status": "failed", "error": job.get("error", "Job failed.")}
    elif st == "completed":
        json_path = API_SCRAPES_DIR / f"{rc}.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail="Output file not found.")
        with open(json_path, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
        return {
            "success": True,
            "status": "completed",
            "profile": profile_data,
            "csv_url": f"/api/client/download/csv?return_code={rc}",
        }
    return {"success": False, "status": st}


@app.get("/api/scraper/stats", tags=["Track"])
async def scraper_stats():
    """Retrieve scraper browser and queue stats."""
    scraper = get_scraper_instance()
    is_auth = scraper.is_authenticated if scraper else False
    tasks = load_bucket_queue()
    summary = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0, "total": len(tasks)}
    for t in tasks:
        s = t.get("status", "pending")
        summary[s] = summary.get(s, 0) + 1

    return {
        "success": True,
        "scraper_initialized": scraper is not None,
        "scraper_authenticated": is_auth,
        "worker_running": is_worker_running(),
        "worker_paused": is_worker_paused(),
        "queue_summary": summary,
    }


# ============================================================================
# 3. BULK SEARCH & RETRIEVAL ENDPOINTS
# ============================================================================

@app.post("/api/persona/bulk-scrape", status_code=status.HTTP_202_ACCEPTED, tags=["Bulk Search"])
@app.post("/api/bulk/scrape", status_code=status.HTTP_202_ACCEPTED, tags=["Bulk Search"])
async def bulk_scrape(req: BulkScrapeRequest):
    """
    Queue multiple LinkedIn URLs or candidate names for bulk extraction.
    Links all items to the provided return_code.
    """
    if not req.profile_urls or not req.return_code:
        raise HTTPException(status_code=400, detail="profile_urls (list) and return_code are required.")

    # Create job in registry
    create_job(
        return_code=req.return_code,
        profile_url=req.profile_urls[0] if req.profile_urls else "",
        is_bulk=True,
        profile_urls=req.profile_urls,
    )

    tasks = load_bucket_queue()
    added_count = 0
    for u in req.profile_urls:
        item = str(u).strip()
        if not item:
            continue
        task = {
            "id": str(uuid.uuid4()),
            "query": item,
            "type": "url" if item.startswith("http") else "name",
            "status": "pending",
            "added_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result_name": "",
            "result_url": item if item.startswith("http") else "",
            "error": None,
            "bulk_return_code": req.return_code,
        }
        tasks.append(task)
        added_count += 1

    save_bucket_queue(tasks)
    ensure_worker_running()

    return {
        "success": True,
        "message": f"Bulk scrape request with {added_count} items queued.",
        "return_code": req.return_code,
        "status": "in_progress",
    }


@app.api_route("/api/persona/bulk-retrieve", methods=["GET", "POST"], tags=["Bulk Search"])
@app.api_route("/api/bulk/retrieve", methods=["GET", "POST"], tags=["Bulk Search"])
async def bulk_retrieve(
    request: Request,
    return_code: Optional[str] = Query(None)
):
    """Retrieve consolidated results of a bulk scrape job."""
    rc = return_code
    if request.method == "POST":
        try:
            body = await request.json()
            rc = body.get("return_code") or rc
        except Exception:
            pass

    if not rc:
        raise HTTPException(status_code=400, detail="return_code is required.")

    jobs = get_jobs_data()
    if rc not in jobs:
        raise HTTPException(status_code=404, detail="No bulk scrape job found for this return_code.")

    job = jobs[rc]
    st = job.get("status")

    if st == "in_progress":
        return {"success": False, "status": "in_progress", "message": "Bulk scraping is still in progress."}
    elif st == "failed":
        return {"success": False, "status": "failed", "error": job.get("error", "Bulk scraping failed.")}
    elif st == "completed":
        json_path = API_SCRAPES_DIR / f"{rc}.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail="Bulk output file not found on disk.")
        with open(json_path, "r", encoding="utf-8") as f:
            bulk_data = json.load(f)
        profiles = bulk_data.get("profiles", []) if isinstance(bulk_data, dict) else bulk_data
        return {
            "success": True,
            "status": "completed",
            "return_code": rc,
            "profiles": profiles,
            "total": len(profiles),
            "csv_url": f"/api/client/download/csv?return_code={rc}",
            "json_url": f"/api/client/download/json?return_code={rc}",
        }

    return {"success": False, "status": st}


@app.get("/api/client/download/csv", tags=["Bulk Search"])
async def download_csv(return_code: str = Query(..., description="Job return code")):
    """Download individual or bulk job results as a CSV file."""
    csv_path = API_SCRAPES_DIR / f"{return_code}.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="CSV file does not exist for this return_code.")
    return FileResponse(csv_path, media_type="text/csv", filename=f"{return_code}.csv")


@app.get("/api/client/download/json", tags=["Bulk Search"])
async def download_json(return_code: str = Query(..., description="Job return code")):
    """Download individual or bulk job results as a JSON file."""
    json_path = API_SCRAPES_DIR / f"{return_code}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="JSON file does not exist for this return_code.")
    return FileResponse(json_path, media_type="application/json", filename=f"{return_code}.json")


# ============================================================================
# 4. BASKET / BUCKET ENDPOINTS
# ============================================================================

@app.post("/api/bucket/add", status_code=status.HTTP_201_CREATED, tags=["Basket / Bucket"])
async def bucket_add(req: BucketAddRequest):
    """Add one or more queries/URLs to the task bucket queue."""
    raw_queries = req.queries or ([req.query] if req.query else [])
    if not raw_queries:
        raise HTTPException(status_code=400, detail="queries (list) or query (string) is required.")

    tasks = load_bucket_queue()
    added = []
    for raw in raw_queries:
        q = str(raw).strip()
        if not q:
            continue
        task = {
            "id": str(uuid.uuid4()),
            "query": q,
            "type": "url" if q.startswith("http") else (req.type or "name"),
            "status": "pending",
            "added_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result_name": "",
            "result_url": "",
            "error": None,
        }
        tasks.append(task)
        added.append(task)

    save_bucket_queue(tasks)
    ensure_worker_running()
    return {"success": True, "added": len(added), "tasks": added}


@app.post("/api/bucket/add-search", status_code=status.HTTP_201_CREATED, tags=["Basket / Bucket"])
async def bucket_add_search(req: BucketAddSearchRequest):
    """Add a structured person search task to the bucket."""
    fn = (req.first_name or "").strip()
    ln = (req.last_name or "").strip()
    co = (req.company or "").strip()

    if not fn and not ln:
        raise HTTPException(status_code=400, detail="first_name or last_name is required.")

    label = " ".join(filter(None, [fn, ln]))
    if co:
        label += f" @ {co}"

    task = {
        "id": str(uuid.uuid4()),
        "query": label,
        "type": "search",
        "search_params": {
            "first_name": fn,
            "last_name": ln,
            "company": co,
            "max_results": max(1, req.max_results or 5),
        },
        "status": "pending",
        "added_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "result_name": "",
        "result_url": "",
        "profiles_found": 0,
        "error": None,
    }

    tasks = load_bucket_queue()
    tasks.append(task)
    save_bucket_queue(tasks)
    ensure_worker_running()

    return {"success": True, "task": task}


@app.post("/api/bucket/upload", status_code=status.HTTP_201_CREATED, tags=["Basket / Bucket"])
async def bucket_upload(file: UploadFile = File(...)):
    """Upload a CSV or JSON file of leads/names/URLs into the task bucket."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    filename_lower = file.filename.lower()
    queries_to_add: List[str] = []

    if filename_lower.endswith(".csv"):
        try:
            text = content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1", errors="replace")

        import csv
        reader = list(csv.reader(io.StringIO(text)))
        if not reader:
            raise HTTPException(status_code=400, detail="CSV file contains no rows.")

        possible_headers = {
            "query", "queries", "name", "full_name", "fullname", "person_name",
            "username", "url", "profile", "profile_url", "linkedin_url", "link",
            "linkedin", "search", "user", "profile link", "linkedin profile"
        }

        first_row = True
        col_idx = 0
        for row in reader:
            if not row:
                continue
            cleaned_row = [str(c).strip() for c in row if c is not None]
            if not any(cleaned_row):
                continue
            if first_row:
                first_row = False
                lower_cols = [c.lower() for c in cleaned_row]
                found_idx = -1
                for idx, col in enumerate(lower_cols):
                    if col in possible_headers or any(h in col for h in ("profile", "url", "linkedin", "name", "query")):
                        found_idx = idx
                        break
                if found_idx != -1:
                    col_idx = found_idx
                    continue
                else:
                    col_idx = 0
            if col_idx < len(cleaned_row) and cleaned_row[col_idx]:
                queries_to_add.append(cleaned_row[col_idx])

    elif filename_lower.endswith(".json"):
        try:
            text = content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1", errors="replace")
        json_data = json.loads(text)
        items = []
        if isinstance(json_data, list):
            items = json_data
        elif isinstance(json_data, dict):
            for key in ("queries", "profiles", "urls", "data", "items", "list", "names"):
                if key in json_data and isinstance(json_data[key], list):
                    items = json_data[key]
                    break
            if not items:
                items = [json_data]
        for item in items:
            if isinstance(item, str) and item.strip():
                queries_to_add.append(item.strip())
            elif isinstance(item, dict):
                for key in ("query", "url", "profile_url", "linkedin_url", "link", "name", "full_name", "person_name"):
                    if key in item and item[key]:
                        queries_to_add.append(str(item[key]).strip())
                        break
    else:
        raise HTTPException(status_code=400, detail="Only .csv and .json files are supported.")

    if not queries_to_add:
        raise HTTPException(status_code=400, detail="No valid names or URLs found in file.")

    tasks = load_bucket_queue()
    added = []
    for q in queries_to_add:
        task = {
            "id": str(uuid.uuid4()),
            "query": q,
            "type": "url" if q.startswith("http") else "name",
            "status": "pending",
            "added_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "result_name": "",
            "result_url": "",
            "error": None,
        }
        tasks.append(task)
        added.append(task)

    save_bucket_queue(tasks)
    ensure_worker_running()

    return {"success": True, "added": len(added), "message": f"Successfully queued {len(added)} items."}


@app.get("/api/bucket/status", tags=["Basket / Bucket"])
async def bucket_status():
    """Get full bucket queue status and task counts."""
    tasks = load_bucket_queue()
    cfg = load_bucket_config()
    summary = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0, "total": len(tasks)}
    for t in tasks:
        s = t.get("status", "pending")
        summary[s] = summary.get(s, 0) + 1

    return {
        "success": True,
        "worker_running": is_worker_running(),
        "worker_paused": is_worker_paused(),
        "rest_seconds": cfg.get("rest_seconds", 30),
        "summary": summary,
        "tasks": tasks,
    }


@app.post("/api/bucket/pause", tags=["Basket / Bucket"])
async def bucket_pause():
    """Pause bucket worker."""
    pause_worker()
    return {"success": True, "paused": True}


@app.post("/api/bucket/resume", tags=["Basket / Bucket"])
async def bucket_resume():
    """Resume bucket worker."""
    resume_worker()
    return {"success": True, "paused": False}


@app.post("/api/bucket/clear", tags=["Basket / Bucket"])
async def bucket_clear(req: BucketClearRequest = BucketClearRequest()):
    """Clear completed and failed tasks (or all if all=True)."""
    tasks = load_bucket_queue()
    if req.all:
        kept = []
    else:
        kept = [t for t in tasks if t["status"] not in ("completed", "failed")]
    save_bucket_queue(kept)
    removed = len(tasks) - len(kept)
    return {"success": True, "removed": removed, "remaining": len(kept)}


@app.post("/api/bucket/remove", tags=["Basket / Bucket"])
async def bucket_remove(req: BucketRemoveRequest):
    """Remove a pending task from the bucket queue."""
    tasks = load_bucket_queue()
    original_len = len(tasks)
    tasks = [t for t in tasks if not (t["id"] == req.task_id and t["status"] == "pending")]
    if len(tasks) == original_len:
        raise HTTPException(status_code=404, detail="Task not found or not in pending state.")
    save_bucket_queue(tasks)
    return {"success": True, "task_id": req.task_id}


@app.post("/api/bucket/config", tags=["Basket / Bucket"])
async def bucket_config(req: BucketConfigRequest):
    """Update bucket rest interval configuration."""
    cfg = load_bucket_config()
    cfg["rest_seconds"] = req.rest_seconds
    save_bucket_config(cfg)
    return {"success": True, "config": cfg}


# ============================================================================
# 5. SCRAPER SESSION & AUTHENTICATION ENDPOINTS
# ============================================================================

@app.post("/api/scraper/init", tags=["Scraper Session"])
async def scraper_init(headless: Optional[bool] = Query(None)):
    """Initialize or reset Playwright Chromium browser."""
    scraper = get_scraper_instance()
    if scraper:
        try:
            await run_scraper_coro(scraper.close(), locked=True)
        except Exception:
            pass

    is_linux = sys.platform != "win32"
    h_mode = headless if headless is not None else os.environ.get("HEADLESS", "true" if is_linux else "false").lower() in ("true", "1", "yes")
    s = LinkedInScraper(headless=h_mode, browser_type="chromium", session_name="default")
    await run_scraper_coro(s.initialize(), locked=True)
    set_scraper_instance(s)
    return {"success": True, "initialized": True, "headless": h_mode}


@app.post("/api/scraper/login", tags=["Scraper Session"])
async def scraper_login(req: ScraperLoginRequest):
    """Authenticate LinkedIn session via email and password."""
    scraper = get_scraper_instance()
    if not scraper:
        is_linux = sys.platform != "win32"
        s = LinkedInScraper(headless=os.environ.get("HEADLESS", "true" if is_linux else "false").lower() in ("true", "1", "yes"), browser_type="chromium", session_name="default")
        await run_scraper_coro(s.initialize(), locked=True)
        scraper = s
        set_scraper_instance(s)

    login_ok = await run_scraper_coro(scraper.login(req.email, req.password), locked=True)
    return {"success": login_ok, "authenticated": scraper.is_authenticated}


@app.post("/api/scraper/login-cookie", tags=["Scraper Session"])
async def scraper_login_cookie(req: ScraperCookieLoginRequest):
    """Authenticate LinkedIn session via li_at session cookie."""
    scraper = get_scraper_instance()
    if not scraper:
        is_linux = sys.platform != "win32"
        s = LinkedInScraper(headless=os.environ.get("HEADLESS", "true" if is_linux else "false").lower() in ("true", "1", "yes"), browser_type="chromium", session_name="default")
        await run_scraper_coro(s.initialize(), locked=True)
        scraper = s
        set_scraper_instance(s)

    login_ok = await run_scraper_coro(scraper.login_with_cookie(req.cookie_value), locked=True)
    return {"success": login_ok, "authenticated": scraper.is_authenticated}


@app.post("/api/scraper/submit-pin", tags=["Scraper Session"])
async def scraper_submit_pin(req: ScraperPinRequest):
    """Submit 2FA PIN code during login checkpoint."""
    scraper = get_scraper_instance()
    if not scraper:
        raise HTTPException(status_code=400, detail="Scraper not initialized.")
    pin_ok = await run_scraper_coro(scraper.submit_pin(req.pin), locked=True)
    return {"success": pin_ok, "authenticated": scraper.is_authenticated}


@app.post("/api/scraper/close", tags=["Scraper Session"])
async def scraper_close():
    """Safely close active scraper session."""
    scraper = get_scraper_instance()
    if scraper:
        try:
            await run_scraper_coro(scraper.close(), locked=True)
        except Exception:
            pass
        set_scraper_instance(None)
    return {"success": True, "message": "Scraper session closed successfully."}


@app.post("/api/scraper/kill-browser", tags=["Scraper Session"])
async def scraper_kill_browser():
    """Force terminate and kill any orphan browser processes."""
    scraper = get_scraper_instance()
    if scraper:
        try:
            await run_scraper_coro(scraper.close(), locked=True)
        except Exception:
            pass
        set_scraper_instance(None)
    from core import LinkedInScraper as _CLS
    _CLS._kill_orphan_chromium("browser_data/default")
    return {"success": True, "message": "Browser processes killed."}


@app.post("/api/scraper/export", tags=["Exports"])
async def export_scraper_data(request: Request):
    """
    Export scraped profile data (single or bulk) as JSON or CSV file.
    Accepts JSON body:
      {
        "data": { "profiles": [...] } OR { "profile": {...} } OR [...],
        "format": "json" | "csv"
      }
    """
    try:
        req_data = await request.json()
    except Exception:
        req_data = {}

    fmt = (req_data.get("format") or "json").lower()
    data_obj = req_data.get("data") or {}

    profiles = []
    if isinstance(data_obj, dict):
        if "profiles" in data_obj and isinstance(data_obj["profiles"], list):
            profiles = data_obj["profiles"]
        elif "profile" in data_obj and isinstance(data_obj["profile"], dict):
            profiles = [data_obj["profile"]]
        elif data_obj:
            profiles = [data_obj]
    elif isinstance(data_obj, list):
        profiles = data_obj

    if not profiles:
        if "profiles" in req_data and isinstance(req_data["profiles"], list):
            profiles = req_data["profiles"]
        elif "profile" in req_data and isinstance(req_data["profile"], dict):
            profiles = [req_data["profile"]]

    if not profiles:
        raise HTTPException(status_code=400, detail="No profiles found to export.")

    cleaned_profiles = [clean_profile(p) for p in profiles]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "json":
        filename = f"linkedin_export_{timestamp}.json"
        filepath = EXPORTS_DIR / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"profiles": cleaned_profiles}, f, indent=2, ensure_ascii=False)
        return FileResponse(filepath, media_type="application/json", filename=filename)
    elif fmt == "csv":
        filename = f"linkedin_export_{timestamp}.csv"
        filepath = EXPORTS_DIR / filename
        headers = [
            "Name", "Headline", "Location",
            "Current Position",
            "Experience", "Education / Qualifications",
            "Skills", "Certifications",
            "About", "Profile URL", "Scraped At"
        ]
        import csv
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for p in cleaned_profiles:
                writer.writerow([
                    p.get("name", ""),
                    p.get("headline", ""),
                    p.get("location", ""),
                    format_current_job_for_csv(p.get("current_job")),
                    format_experience_for_csv(p.get("experiences") or p.get("experience")),
                    format_education_for_csv(p.get("qualifications") or p.get("education")),
                    format_skills_for_csv(p.get("skills")),
                    format_certifications_for_csv(p.get("certifications")),
                    (p.get("about") or "")[:2000],
                    p.get("profile_url", ""),
                    p.get("scraped_at", "")
                ])
        return FileResponse(filepath, media_type="text/csv", filename=filename)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported export format '{fmt}'. Use 'json' or 'csv'.")


# ============================================================================
# 6. DATABASE MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/api/admin/db-profiles", tags=["Database Management"])
async def admin_db_profiles(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None)
):
    """Retrieve paginated master database profiles with optional search."""
    profiles = get_all_master_profiles()
    if search:
        s_lower = search.strip().lower()
        profiles = [
            p for p in profiles
            if s_lower in (p.get("name") or "").lower()
            or s_lower in (p.get("headline") or "").lower()
            or s_lower in (p.get("location") or "").lower()
        ]

    total = len(profiles)
    start = (page - 1) * limit
    end = start + limit
    paginated = profiles[start:end]

    return {
        "success": True,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
        "profiles": paginated,
    }


@app.get("/api/admin/download-db/json", tags=["Database Management"])
async def admin_download_db_json():
    """Download full master profile database as JSON."""
    if not ALL_PROFILES_JSON.exists():
        raise HTTPException(status_code=404, detail="Master JSON database file not found.")
    return FileResponse(ALL_PROFILES_JSON, media_type="application/json", filename="all_scraped_profiles.json")


@app.get("/api/admin/download-db/csv", tags=["Database Management"])
async def admin_download_db_csv():
    """Download full master profile database as CSV."""
    if not ALL_PROFILES_CSV.exists() or ALL_PROFILES_CSV.stat().st_size == 0:
        profiles = get_all_master_profiles()
        if not profiles:
            raise HTTPException(status_code=404, detail="Master CSV database is empty.")
        import csv
        headers = [
            "Name", "Headline", "Location",
            "Current Position",
            "Experience", "Education / Qualifications",
            "Skills", "Certifications",
            "About", "Profile URL", "Scraped At"
        ]
        with open(ALL_PROFILES_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for cp in profiles:
                writer.writerow([
                    cp.get("name", ""),
                    cp.get("headline", ""),
                    cp.get("location", ""),
                    format_current_job_for_csv(cp.get("current_job")),
                    format_experience_for_csv(cp.get("experiences") or cp.get("experience")),
                    format_education_for_csv(cp.get("qualifications") or cp.get("education")),
                    format_skills_for_csv(cp.get("skills")),
                    format_certifications_for_csv(cp.get("certifications")),
                    (cp.get("about") or "")[:2000],
                    cp.get("profile_url", ""),
                    cp.get("scraped_at", "")
                ])
    return FileResponse(ALL_PROFILES_CSV, media_type="text/csv", filename="all_scraped_profiles.csv")


@app.post("/api/admin/destroy-db", tags=["Database Management"])
async def admin_destroy_db():
    """Wipe and reset master database and search cache."""
    clear_master_db()
    return {"success": True, "message": "Master database and cache destroyed successfully."}


# ── Standalone Uvicorn Runner ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    reload = os.environ.get("RELOAD", "false").lower() in ("true", "1", "yes")
    print(f"Starting Persona V3 API on http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=reload, loop="asyncio")
