"""
Background Task Bucket Worker Subsystem
=======================================
Asynchronous queue consumer that processes pending scraping jobs sequentially.
Features:
  - Single-worker queue execution to prevent concurrent LinkedIn bans
  - Dynamic session authentication check and auto-recovery
  - Anti-ban randomized rest intervals between tasks
  - Automatic consolidation of bulk scrape batches
  - Full error isolation and crash recovery
"""

import sys
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from datetime import datetime
import os
import random
import re
from typing import Any, Dict, List, Optional
import uuid

from async_bridge import get_scraper_loop, get_scraper_lock
from core import LinkedInScraper
from cleaner import clean_profile
from storage import (
    API_SCRAPES_DIR,
    load_bucket_config,
    load_bucket_queue,
    pop_next_pending_task,
    save_scraped_data_formats,
    save_to_master_db,
    update_bucket_task,
    update_job_status,
    update_name_cache,
)

# ── Worker Global State ──────────────────────────────────────────────────────
_worker_task: Optional[asyncio.Task] = None
_worker_running: bool = False
_worker_paused: bool = False
_active_scraper: Optional[LinkedInScraper] = None


def get_scraper_instance() -> Optional[LinkedInScraper]:
    """Return the global active scraper instance if initialized."""
    return _active_scraper


def set_scraper_instance(scraper: Optional[LinkedInScraper]) -> None:
    """Set or reset the global scraper instance."""
    global _active_scraper
    _active_scraper = scraper


def is_worker_running() -> bool:
    return _worker_running


def is_worker_paused() -> bool:
    return _worker_paused


def pause_worker() -> None:
    global _worker_paused
    _worker_paused = True


def resume_worker() -> None:
    global _worker_paused
    _worker_paused = False
    ensure_worker_running()


def _check_and_finalize_bulk_job(bulk_return_code: str) -> None:
    """Check if all tasks belonging to bulk_return_code are done. If so, consolidate data and update jobs.json."""
    if not bulk_return_code:
        return

    tasks = load_bucket_queue()
    related = [t for t in tasks if t.get("bulk_return_code") == bulk_return_code]
    if not related:
        return

    unfinished = [t for t in related if t.get("status") in ("pending", "in_progress")]
    if unfinished:
        return  # Tasks still running

    # All related tasks are finished! Collect profiles from completed tasks.
    scraped_profiles: List[Dict[str, Any]] = []
    errors: List[str] = []

    for t in related:
        t_id = t.get("id")
        if t.get("status") == "failed":
            if t.get("error"):
                errors.append(f"{t.get('query')}: {t.get('error')}")
        elif t.get("status") == "completed" and t_id:
            json_path = API_SCRAPES_DIR / f"{t_id}.json"
            if json_path.exists():
                try:
                    import json
                    with open(json_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, dict) and "profiles" in raw:
                        scraped_profiles.extend(raw["profiles"])
                    elif isinstance(raw, list):
                        scraped_profiles.extend(raw)
                    elif isinstance(raw, dict):
                        scraped_profiles.append(raw)
                except Exception:
                    pass

    # Save consolidated bulk JSON and CSV
    scraped_at = datetime.now().isoformat()
    save_scraped_data_formats(scraped_profiles, bulk_return_code)

    final_status = "completed" if scraped_profiles or not errors else "failed"
    err_str = "; ".join(errors) if errors else None
    update_job_status(bulk_return_code, final_status, scraped_at=scraped_at, error=err_str)
    print(f"[Worker] Bulk job '{bulk_return_code}' finalized: status={final_status} ({len(scraped_profiles)} profiles)")


async def _ensure_authenticated_scraper() -> LinkedInScraper:
    """Ensure a valid, logged-in LinkedInScraper instance exists."""
    global _active_scraper

    is_linux = sys.platform != "win32"
    env_headless = os.environ.get("HEADLESS", "true" if is_linux else "false").lower() in ("true", "1", "yes")
    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")
    li_at = os.environ.get("LINKEDIN_LI_AT", "")

    if not _active_scraper:
        s = LinkedInScraper(headless=env_headless, browser_type="chromium", session_name="default")
        await s.initialize()
        _active_scraper = s
    else:
        # If already authenticated (cookie pre-injected), skip check_auth which would navigate to /feed/
        if not _active_scraper.is_authenticated:
            try:
                is_ok = await _active_scraper.check_auth()
                if not is_ok:
                    print("[Worker] Scraper session invalid/disconnected. Re-initializing...")
                    try:
                        await _active_scraper.close()
                    except Exception:
                        pass
                    _active_scraper = None
                    s = LinkedInScraper(headless=env_headless, browser_type="chromium", session_name="default")
                    await s.initialize()
                    _active_scraper = s
            except Exception:
                _active_scraper = None
                s = LinkedInScraper(headless=env_headless, browser_type="chromium", session_name="default")
                await s.initialize()
                _active_scraper = s

    if not _active_scraper.is_authenticated:
        if li_at:
            print("[Worker] Authenticating via LINKEDIN_LI_AT cookie...")
            await _active_scraper.login_with_cookie(li_at)
        elif email and password:
            print(f"[Worker] Authenticating via credentials for {email}...")
            await _active_scraper.login(email, password)
    else:
        print("[Worker] Session already authenticated (li_at cookie active).")

    return _active_scraper


async def _bucket_worker_loop() -> None:
    """Main background loop processing queue tasks sequentially (one scraped after one)."""
    global _worker_running, _worker_paused, _active_scraper

    print("[Worker] Background task processor started")
    _worker_running = True

    try:
        while True:
            if _worker_paused:
                await asyncio.sleep(2)
                continue

            task = pop_next_pending_task()
            if not task:
                await asyncio.sleep(3)
                continue

            task_id = task["id"]
            query = task["query"]
            task_type = task.get("type", "name")
            bulk_rc = task.get("bulk_return_code")

            print(f"[Worker] Processing task {task_id} ({task_type}): '{query}'")

            try:
                scrape_lock = get_scraper_lock()
                async with scrape_lock:
                    scraper = await _ensure_authenticated_scraper()

                    # 1. Direct URL task
                    if task_type == "url" or query.startswith("http"):
                        target_url = task.get("result_url") or query
                        profile = await scraper.extract_profile(target_url)
                        if "error" in profile and not profile.get("name"):
                            raise ValueError(profile.get("error", "Profile extraction failed."))

                        completed_time = datetime.now().isoformat()
                        profile["scraped_at"] = completed_time
                        save_to_master_db(profile)
                        save_scraped_data_formats(profile, task_id)

                        is_prem = bool(profile.get("is_premium", False))
                        update_bucket_task(
                            task_id,
                            status="completed",
                            completed_at=completed_time,
                            result_name=profile.get("name", query),
                            result_url=target_url,
                            profiles_found=1,
                            error=None
                        )
                        update_job_status(task_id, "completed", scraped_at=completed_time)
                        print(f"[Worker] Task {task_id} completed: {profile.get('name', query)} (Premium: {is_prem})")

                    # 2. Direct Username Handle / Slug with Search Fallback
                    elif task_type == "username_or_search":
                        slug = task.get("username") or query.lstrip('@')
                        direct_url = f"https://www.linkedin.com/in/{slug}"
                        print(f"[Worker] Checking direct username URL: {direct_url}")
                        profile = await scraper.extract_profile(direct_url)
                        
                        if profile and not profile.get("error") and profile.get("name"):
                            completed_time = datetime.now().isoformat()
                            profile["scraped_at"] = completed_time
                            save_to_master_db(profile)
                            save_scraped_data_formats(profile, task_id)

                            is_prem = bool(profile.get("is_premium", False))
                            update_bucket_task(
                                task_id,
                                status="completed",
                                completed_at=completed_time,
                                result_name=profile.get("name", slug),
                                result_url=direct_url,
                                profiles_found=1,
                                error=None
                            )
                            update_job_status(task_id, "completed", scraped_at=completed_time)
                            print(f"[Worker] Task {task_id} completed via username URL: {profile.get('name', slug)} (Premium: {is_prem})")
                        else:
                            # Fallback to search if direct slug failed
                            print(f"[Worker] Direct username URL failed. Searching for candidate '{slug}'...")
                            sp = task.get("search_params", {})
                            fn = sp.get("first_name", slug)
                            ln = sp.get("last_name", "")
                            co = sp.get("company", "")
                            search_results = await scraper.search_people(fn, ln, co, max_results=1)
                            if not search_results:
                                raise ValueError(f"No profile found for username/name: {slug}")
                            
                            extracted = []
                            for idx, sr in enumerate(search_results):
                                p = await scraper.extract_profile(sr["profile_url"])
                                if p and not p.get("error") and p.get("name"):
                                    p["scraped_at"] = datetime.now().isoformat()
                                    save_to_master_db(p)
                                    extracted.append(p)
                                if idx < len(search_results) - 1:
                                    await asyncio.sleep(4)

                            if not extracted:
                                raise ValueError(f"Could not extract profile for username: {slug}")
                            
                            save_scraped_data_formats(extracted, task_id)
                            completed_time = datetime.now().isoformat()
                            update_bucket_task(
                                task_id,
                                status="completed",
                                completed_at=completed_time,
                                result_name=extracted[0].get("name", slug),
                                result_url=extracted[0].get("profile_url", ""),
                                profiles_found=len(extracted),
                                error=None
                            )
                            update_job_status(task_id, "completed", scraped_at=completed_time)

                    # 3. Structured Search (First Name, Last Name, Company) - Sequential (One-by-One)
                    elif task_type == "search":
                        sp = task.get("search_params", {})
                        fn = sp.get("first_name", query)
                        ln = sp.get("last_name", "")
                        co = sp.get("company", "")
                        mx = max(1, int(sp.get("max_results", 1)))

                        print(f"[Worker] Searching people: '{fn} {ln}' company='{co}' max={mx}")
                        search_results = []
                        try:
                            search_results = await scraper.search_people(fn, ln, co, max_results=mx)
                        except Exception as se:
                            print(f"[Worker] Search people warning: {se}")

                        extracted: List[Dict[str, Any]] = []
                        if search_results:
                            print(f"[Worker] Found {len(search_results)} match(es), extracting sequentially one-by-one...")
                            for idx, sr in enumerate(search_results):
                                try:
                                    print(f"[Worker] Extracting profile {idx+1}/{len(search_results)}: {sr.get('name')} ({sr.get('profile_url')})")
                                    profile = await scraper.extract_profile(sr["profile_url"])
                                    if "error" not in profile and profile.get("name"):
                                        profile["scraped_at"] = datetime.now().isoformat()
                                        save_to_master_db(profile)
                                        extracted.append(profile)
                                    if idx < len(search_results) - 1:
                                        await asyncio.sleep(4)  # Safe delay between sequential profiles
                                except Exception as pe:
                                    print(f"[Worker] Profile extract error for {sr['profile_url']}: {pe}")

                        if not extracted:
                            raise ValueError(f"No matching profile found on LinkedIn for: '{query}'")

                        client_name = task.get("_client_name") or query
                        scraped_urls = [p.get("profile_url") for p in extracted if p.get("profile_url")]
                        if scraped_urls:
                            update_name_cache(client_name, scraped_urls)

                        names = ", ".join(p.get("name", "") for p in extracted[:3])
                        if len(extracted) > 3:
                            names += f" +{len(extracted)-3} more"

                        save_scraped_data_formats(extracted, task_id)
                        completed_time = datetime.now().isoformat()
                        update_bucket_task(
                            task_id,
                            status="completed",
                            completed_at=completed_time,
                            result_name=names or query,
                            result_url=extracted[0].get("profile_url", ""),
                            profiles_found=len(extracted),
                            error=None
                        )
                        update_job_status(task_id, "completed", scraped_at=completed_time)
                        print(f"[Worker] Task {task_id} completed: {len(extracted)} profile(s) scraped (Premium detected: {any(p.get('is_premium') for p in extracted)})")

                    # 4. Fallback Generic Single Task
                    else:
                        profile = await scraper.extract_profile(query)
                        if "error" in profile and not profile.get("name"):
                            raise ValueError(profile.get("error", "Failed to extract profile."))
                        completed_time = datetime.now().isoformat()
                        profile["scraped_at"] = completed_time
                        save_to_master_db(profile)
                        save_scraped_data_formats(profile, task_id)
                        update_bucket_task(
                            task_id,
                            status="completed",
                            completed_at=completed_time,
                            result_name=profile.get("name", query),
                            result_url=query,
                            profiles_found=1,
                            error=None
                        )
                        update_job_status(task_id, "completed", scraped_at=completed_time)
                        print(f"[Worker] Task {task_id} completed: {profile.get('name', query)}")

            except Exception as exc:
                err = str(exc)
                print(f"[Worker] Task {task_id} failed: {err}")

                # Browser crash or context disconnect recovery
                if any(k in err.lower() for k in ["target page", "closed", "crashed", "disconnected", "context"]):
                    print("[Worker] Browser crash/disconnect detected. Resetting scraper...")
                    try:
                        if _active_scraper:
                            await _active_scraper.close()
                    except Exception:
                        pass
                    _active_scraper = None

                completed_time = datetime.now().isoformat()
                update_bucket_task(
                    task_id,
                    status="failed",
                    completed_at=completed_time,
                    error=err
                )
                update_job_status(task_id, "failed", scraped_at=completed_time, error=err)

            # Finalize parent bulk job if applicable
            if bulk_rc:
                _check_and_finalize_bulk_job(bulk_rc)

            # Anti-ban rest timer
            cfg = load_bucket_config()
            base_rest = int(cfg.get("rest_seconds", 30))
            if base_rest > 0:
                rest = random.randint(max(10, base_rest), max(20, base_rest + 15))
                print(f"[Worker] Resting {rest}s before next queue item...")
                elapsed = 0
                while elapsed < rest:
                    await asyncio.sleep(min(2, rest - elapsed))
                    elapsed += 2
                    if _worker_paused:
                        break

    except asyncio.CancelledError:
        print("[Worker] Background task processor received cancellation")
    finally:
        _worker_running = False
        print("[Worker] Background task processor stopped")


def ensure_worker_running() -> None:
    """Ensure the background worker coroutine is scheduled on the dedicated Playwright Proactor loop."""
    global _worker_task, _worker_running
    if not _worker_running or _worker_task is None or _worker_task.done():
        loop = get_scraper_loop()
        _worker_task = asyncio.run_coroutine_threadsafe(_bucket_worker_loop(), loop)


async def shutdown_worker() -> None:
    """Gracefully cancel worker and close active scraper."""
    global _worker_task, _active_scraper
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    if _active_scraper:
        try:
            loop = get_scraper_loop()
            fut = asyncio.run_coroutine_threadsafe(_active_scraper.close(), loop)
            await asyncio.wrap_future(fut)
        except Exception:
            pass
        _active_scraper = None
