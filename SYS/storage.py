"""
Persistent Storage and Registry Subsystem
=========================================
Thread-safe and async-compatible disk persistence for:
  - Master scraped profiles database (JSON & CSV)
  - Search name-to-URL cache
  - Job execution registry (jobs.json)
  - Individual job artifacts ({id}.json, {id}.csv)
  - Task Bucket queue (bucket_queue.json)
  - Task Bucket configuration (bucket_config.json)
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import csv
import json
import threading

from cleaner import (
    clean_profile,
    format_certifications_for_csv,
    format_current_job_for_csv,
    format_education_for_csv,
    format_experience_for_csv,
    format_skills_for_csv,
)

# ── Directory Layout ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
EXPORTS_DIR = BASE_DIR / "exports"
API_SCRAPES_DIR = EXPORTS_DIR / "api_scrapes"

EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
API_SCRAPES_DIR.mkdir(parents=True, exist_ok=True)

# ── File Paths ──────────────────────────────────────────────────────────────
ALL_PROFILES_JSON = EXPORTS_DIR / "all_scraped_profiles.json"
ALL_PROFILES_CSV = EXPORTS_DIR / "all_scraped_profiles.csv"
NAME_CACHE_FILE = EXPORTS_DIR / "name_cache.json"
JOBS_FILE = API_SCRAPES_DIR / "jobs.json"
MASTER_CSV_FILE = API_SCRAPES_DIR / "scraped_profiles.csv"
BUCKET_QUEUE_FILE = EXPORTS_DIR / "bucket_queue.json"
BUCKET_CONFIG_FILE = EXPORTS_DIR / "bucket_config.json"

# ── Concurrency Locks ───────────────────────────────────────────────────────
_db_lock = threading.Lock()
_jobs_lock = threading.Lock()
_queue_lock = threading.Lock()
_config_lock = threading.Lock()


# ── Initialization ──────────────────────────────────────────────────────────
def _init_storage() -> None:
    """Initialize empty files if they do not already exist."""
    if not NAME_CACHE_FILE.exists():
        with open(NAME_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)

    if not JOBS_FILE.exists():
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)

    if not BUCKET_QUEUE_FILE.exists():
        with open(BUCKET_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    if not BUCKET_CONFIG_FILE.exists():
        with open(BUCKET_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"rest_seconds": 30}, f)


_init_storage()


# ── Master Profile Database ─────────────────────────────────────────────────
def save_to_master_db(profile: Dict[str, Any]) -> None:
    """
    Save or update a cleaned profile in the master JSON and CSV databases.
    Deduplicates by profile_url.
    """
    if not profile or "error" in profile:
        return

    cleaned_p = clean_profile(profile)
    with _db_lock:
        try:
            profiles = []
            if ALL_PROFILES_JSON.exists():
                try:
                    with open(ALL_PROFILES_JSON, "r", encoding="utf-8") as f:
                        profiles = [clean_profile(p) for p in json.load(f)]
                except Exception:
                    profiles = []

            url = cleaned_p.get("profile_url")
            updated = False
            for i, p in enumerate(profiles):
                if p.get("profile_url") and p.get("profile_url") == url:
                    profiles[i] = cleaned_p
                    updated = True
                    break
            if not updated:
                profiles.append(cleaned_p)

            with open(ALL_PROFILES_JSON, "w", encoding="utf-8") as f:
                json.dump(profiles, f, indent=2, ensure_ascii=False)

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
                for p in profiles:
                    cp = clean_profile(p)
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
        except Exception as e:
            print(f"[Storage] Error saving to master database: {e}")


def get_all_master_profiles() -> List[Dict[str, Any]]:
    """Retrieve all profiles from the master database."""
    with _db_lock:
        if ALL_PROFILES_JSON.exists():
            try:
                with open(ALL_PROFILES_JSON, "r", encoding="utf-8") as f:
                    return [clean_profile(p) for p in json.load(f)]
            except Exception:
                pass
    return []


def clear_master_db() -> None:
    """Clear master JSON, CSV, and name cache."""
    with _db_lock:
        try:
            if ALL_PROFILES_JSON.exists():
                with open(ALL_PROFILES_JSON, "w", encoding="utf-8") as f:
                    json.dump([], f)
            if ALL_PROFILES_CSV.exists():
                with open(ALL_PROFILES_CSV, "w", encoding="utf-8") as f:
                    f.write("")
            if NAME_CACHE_FILE.exists():
                with open(NAME_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
        except Exception as e:
            print(f"[Storage] Error clearing master database: {e}")


# ── Name Cache ──────────────────────────────────────────────────────────────
def get_name_cache() -> Dict[str, List[str]]:
    """Retrieve the name cache mapping."""
    with _db_lock:
        if NAME_CACHE_FILE.exists():
            try:
                with open(NAME_CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def update_name_cache(name: str, profile_urls: List[str]) -> None:
    """Update cache mapping for a search name."""
    if not name or not profile_urls:
        return
    with _db_lock:
        cache_data = {}
        if NAME_CACHE_FILE.exists():
            try:
                with open(NAME_CACHE_FILE, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
            except Exception:
                pass
        cache_data[name] = profile_urls
        try:
            with open(NAME_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            print(f"[Storage] Error writing name cache: {e}")


# ── Jobs Registry ───────────────────────────────────────────────────────────
def get_jobs_data() -> Dict[str, Any]:
    """Load all jobs from jobs.json."""
    with _jobs_lock:
        if JOBS_FILE.exists():
            try:
                with open(JOBS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def create_job(return_code: str, profile_url: str, person_name: str = "", is_bulk: bool = False, profile_urls: Optional[List[str]] = None) -> None:
    """Create a new job in jobs.json."""
    with _jobs_lock:
        data = {}
        if JOBS_FILE.exists():
            try:
                with open(JOBS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        if not person_name and "/in/" in profile_url:
            person_name = profile_url.split("/in/")[1].strip("/").split("?")[0]

        job_info: Dict[str, Any] = {
            "profile_url": profile_url,
            "person_name": person_name,
            "status": "in_progress",
            "requested_at": datetime.now().isoformat(),
            "scraped_at": None,
            "error": None,
        }
        if is_bulk:
            job_info["is_bulk"] = True
            job_info["profile_urls"] = profile_urls or []

        data[return_code] = job_info
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def update_job_status(return_code: str, status: str, scraped_at: Optional[str] = None, error: Optional[str] = None, profile_url: Optional[str] = None) -> None:
    """Update status, error, and timestamps of a job."""
    with _jobs_lock:
        data = {}
        if JOBS_FILE.exists():
            try:
                with open(JOBS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        if return_code in data:
            data[return_code]["status"] = status
            if scraped_at:
                data[return_code]["scraped_at"] = scraped_at
            if error:
                data[return_code]["error"] = error
            if profile_url:
                data[return_code]["profile_url"] = profile_url
            with open(JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)


# ── Individual and Batch Export Formats ─────────────────────────────────────
def save_scraped_data_formats(data_input: Any, return_code: str) -> None:
    """Save cleaned JSON and CSV files for a specific job return_code."""
    if isinstance(data_input, list):
        profiles = [clean_profile(p) for p in data_input if p and "error" not in p]
    elif isinstance(data_input, dict) and "profiles" in data_input:
        profiles = [clean_profile(p) for p in data_input["profiles"] if p and "error" not in p]
    elif isinstance(data_input, dict):
        profiles = [clean_profile(data_input)]
    else:
        profiles = []

    if not profiles:
        return

    # 1. Save JSON
    json_path = API_SCRAPES_DIR / f"{return_code}.json"
    json_data = {"profiles": profiles} if len(profiles) > 1 else profiles[0]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    # 2. Save individual CSV
    csv_path = API_SCRAPES_DIR / f"{return_code}.csv"
    headers = [
        "Name", "Headline", "Location",
        "Current Position",
        "Experience", "Education / Qualifications",
        "Skills", "Certifications",
        "About", "Profile URL", "Scraped At", "Return Code"
    ]

    rows_data = []
    for cp in profiles:
        rows_data.append([
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
            cp.get("scraped_at", ""),
            return_code
        ])

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows_data:
            writer.writerow(row)

    # 3. Append to master CSV
    master_exists = MASTER_CSV_FILE.exists()
    with open(MASTER_CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not master_exists:
            writer.writerow(headers)
        for row in rows_data:
            writer.writerow(row)


# ── Task Bucket Queue & Config ──────────────────────────────────────────────
def load_bucket_queue() -> List[Dict[str, Any]]:
    """Load all tasks in the bucket queue."""
    with _queue_lock:
        if BUCKET_QUEUE_FILE.exists():
            try:
                with open(BUCKET_QUEUE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return []


def save_bucket_queue(tasks: List[Dict[str, Any]]) -> None:
    """Save tasks to the bucket queue."""
    with _queue_lock:
        with open(BUCKET_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)


def update_bucket_task(task_id: str, **kwargs: Any) -> None:
    """Update fields for a specific task in the queue."""
    with _queue_lock:
        tasks = []
        if BUCKET_QUEUE_FILE.exists():
            try:
                with open(BUCKET_QUEUE_FILE, "r", encoding="utf-8") as f:
                    tasks = json.load(f)
            except Exception:
                pass
        for t in tasks:
            if t["id"] == task_id:
                t.update(kwargs)
                break
        with open(BUCKET_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)


def pop_next_pending_task() -> Optional[Dict[str, Any]]:
    """Atomically find the first pending task, mark it as in_progress, and return it."""
    with _queue_lock:
        tasks = []
        if BUCKET_QUEUE_FILE.exists():
            try:
                with open(BUCKET_QUEUE_FILE, "r", encoding="utf-8") as f:
                    tasks = json.load(f)
            except Exception:
                pass

        for t in tasks:
            if t.get("status") == "pending":
                t["status"] = "in_progress"
                t["started_at"] = datetime.now().isoformat()
                with open(BUCKET_QUEUE_FILE, "w", encoding="utf-8") as f:
                    json.dump(tasks, f, indent=2)
                return t
    return None


def load_bucket_config() -> Dict[str, Any]:
    """Load configuration for the task bucket worker."""
    with _config_lock:
        if BUCKET_CONFIG_FILE.exists():
            try:
                with open(BUCKET_CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {"rest_seconds": 30}


def save_bucket_config(cfg: Dict[str, Any]) -> None:
    """Save configuration for the task bucket worker."""
    with _config_lock:
        with open(BUCKET_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
