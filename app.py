#Required Imports
from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_cors import CORS
import asyncio
import threading
import os
import sys
import json
from datetime import datetime
from pathlib import Path
import csv
import io
import queue
import time
import requests
import tempfile

# SSE subscriber queues for live admin updates
_sse_subscribers: list = []
_sse_lock = threading.Lock()

def _broadcast_sse(event_type: str, data: dict):
    """Push an SSE event to all connected admin browsers."""
    payload = json.dumps({'type': event_type, **data})
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)

# Ensure current directory is in sys.path for module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Local module imports
from core import LinkedInScraper
from ranker import rank_sri_lankan_profiles, get_score_tier

# Flask App Initialization
app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

scraper = None

# Background event loop for Playwright operations (Chronium processes)
_bg_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
threading.Thread(target=_bg_loop.run_forever, daemon=True, name="playwright-loop").start()

# Helper function to run async coroutines in the background loop and wait for results
def run_async(coro, timeout: int = 300):
    future = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return future.result(timeout=timeout)

#Main App - Client Portal
@app.route('/')
def index():
    return render_template('client.html')

#Admin App Dashboard
@app.route('/admin')
def admin_index():
    return render_template('index.html')

#SCrapper Initial
@app.route('/api/scraper/init', methods=['POST'])
def init_scraper():
    global scraper
    try:
        if scraper:
            try:
                run_async(scraper.close())
            except:
                pass
            scraper = None
        data = request.json or {}
        async def init():
            global scraper
            scraper = LinkedInScraper(
                headless=data.get('headless', False),
                browser_type=data.get('browser_type', 'chromium'),
                session_name=data.get('session_name', 'default')
            )
            await scraper.initialize()
            return {'success': True, 'message': 'Browser initialized'}
        result = run_async(init())
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# Scrapper Login
@app.route('/api/scraper/login', methods=['POST'])
def login():
    global scraper
    if not scraper:
        return jsonify({'success': False, 'error': 'Not initialized'}), 400
    try:
        data = request.json
        email = data.get('email', '').strip()
        password = data.get('password', '')
        if not email or not password:
            return jsonify({'success': False, 'error': 'Email and password required'}), 400
        async def do_login():
            return await scraper.login(email, password)
        success = run_async(do_login())
        return jsonify({'success': success, 'message': 'Login successful!' if success else 'Login failed'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

#Search through the scrapper
@app.route('/api/scraper/search', methods=['POST'])
def search():
    global scraper
    if not scraper or not scraper.is_authenticated:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        data = request.json
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        company = data.get('company', '').strip()
        max_results = data.get('max_results', 10)
        if not first_name and not last_name:
            return jsonify({'success': False, 'error': 'Name required'}), 400
        async def do_search():
            return await scraper.search_people(first_name, last_name, company, max_results)
        results = run_async(do_search())
        return jsonify({'success': True, 'results': results, 'total': len(results)})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500



#Combined search and extract
@app.route('/api/scraper/search-and-extract', methods=['POST'])
def search_and_extract():
    try:
        data = request.json
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        company = data.get('company', '').strip()
        if not first_name and not last_name:
            return jsonify({'success': False, 'error': 'Name required'}), 400
            
        global scraper
        if not scraper or not scraper.is_authenticated:
            return jsonify({'success': False, 'error': 'Scraper not initialized or not authenticated. Please init and login first.'}), 401
            
        # Combine name for cache
        name = " ".join(filter(None, [first_name, last_name]))
        
        # Check cache
        with db_lock:
            cache_data = {}
            if NAME_CACHE_FILE.exists():
                try:
                    with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                except Exception:
                    pass
                    
        if name in cache_data:
            cached_urls = cache_data[name]
            all_profiles = []
            if ALL_PROFILES_JSON.exists():
                try:
                    with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                        all_profiles = json.load(f)
                except Exception:
                    pass
                    
            results = [p for p in all_profiles if p.get('profile_url') in cached_urls]
            if results:
                return jsonify({
                    'success': True,
                    'cached': True,
                    'profiles': results,
                    'total': len(results)
                }), 200

        # Check if already in progress
        jobs = get_jobs_data()
        for jid, j in jobs.items():
            if j.get('person_name') == name and j.get('status') == 'in_progress':
                return jsonify({'success': True, 'status': 'in_progress', 'message': 'Scraping is still running...', 'total': 0, 'profiles': []}), 202

        # Create a job to track this
        request_id = "BULK_" + str(int(time.time())) + "_" + os.urandom(4).hex()
        create_job(request_id, profile_url="Multi-Profile Search", person_name=name)
        _broadcast_sse('request_started', {'name': name})

        # Run async in background loop without blocking
        async def background_search_and_extract():
            try:
                res = await scraper.search_and_extract(first_name=first_name, last_name=last_name, company=company)
                if res.get('success'):
                    profiles = res.get('profiles', [])
                    scraped_urls = []
                    for profile in profiles:
                        if 'error' not in profile:
                            save_to_persistent_db(profile)
                            scraped_urls.append(profile.get('profile_url'))
                    if scraped_urls:
                        with db_lock:
                            cache_data[name] = scraped_urls
                            with open(NAME_CACHE_FILE, 'w', encoding='utf-8') as f:
                                json.dump(cache_data, f, indent=2)
                    _broadcast_sse('new_scrape', {'name': name, 'count': len(profiles)})
                    update_job_status(request_id, 'completed', scraped_at=datetime.now().isoformat())
                else:
                    update_job_status(request_id, 'failed', error=res.get('error', 'Unknown error'))
            except Exception as e:
                import traceback
                traceback.print_exc()
                update_job_status(request_id, 'failed', error=str(e))

        asyncio.run_coroutine_threadsafe(background_search_and_extract(), _bg_loop)
        
        return jsonify({
            'success': True,
            'status': 'started',
            'message': 'Scraping started in background. Please check back later.'
        }), 202
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

#Get scrapper stats (Health and ETC)
@app.route('/api/scraper/stats', methods=['GET'])
def stats():
    global scraper
    if not scraper:
        return jsonify({'success': False, 'error': 'Not initialized'})
    try:
        async def get_stats():
            return await scraper.get_stats()
        stats_data = run_async(get_stats())
        return jsonify({'success': True, 'stats': stats_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

#Close the scrapper and free resources (Chromium processes and ETC)
@app.route('/api/scraper/close', methods=['POST'])
def close():
    global scraper
    try:
        if scraper:
            run_async(scraper.close())
            scraper = None
        return jsonify({'success': True, 'message': 'Closed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Profile Ranking Endpoint [Still Under Construction - Not Fully Functional]
@app.route('/api/rank', methods=['POST'])
def rank_profiles():
    try:
        data = request.json or {}
        profiles = data.get('profiles', [])
        if not profiles:
            return jsonify({'success': False, 'error': 'No profiles provided'}), 400
        ranked = rank_sri_lankan_profiles(profiles)
        for item in ranked:
            item['tier'] = get_score_tier(item['scoring']['total_score'])
        return jsonify({
            'success': True,
            'total_input': len(profiles),
            'sri_lankan_count': len(ranked),
            'non_sri_lankan_filtered': len(profiles) - len(ranked),
            'ranked': ranked
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

#Data Export Endpoint (Supports JSON and CSV)
@app.route('/api/scraper/export', methods=['POST'])
def export_data():
    try:
        data = request.json
        export_payload = data.get('data', {})
        format_type = data.get('format', 'json')
        if not export_payload:
            return jsonify({'success': False, 'error': 'No data'}), 400
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path("exports").mkdir(exist_ok=True)
        if format_type == 'json':
            filename = f"linkedin_export_{timestamp}.json"
            filepath = Path("exports") / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_payload, f, indent=2, ensure_ascii=False)
            return send_file(filepath, as_attachment=True, download_name=filename)
        elif format_type == 'csv':
            from flask import make_response
            filename = f"linkedin_export_{timestamp}.csv"
            output = io.StringIO()
            writer = csv.writer(output)
            profiles = export_payload.get('profiles', [])
            if not profiles:
                return jsonify({'success': False, 'error': 'No profiles in data'}), 400
            writer.writerow(['Name', 'Profile Picture', 'About', 'Job Title', 'Company', 'Qualifications', 'Certifications', 'Profile URL', 'Scraped At'])
            for p in profiles:
                job = p.get('current_job', {}) or {}
                quals = '; '.join([f"{q.get('institution','')} - {q.get('degree','')}" for q in (p.get('qualifications') or [])])
                certs = '; '.join([f"{c.get('name','')} - {c.get('issuer','')}" for c in (p.get('certifications') or [])])
                writer.writerow([
                    p.get('name', ''),
                    p.get('profile_picture', ''),
                    (p.get('about', '') or '')[:2000],
                    job.get('title', ''),
                    job.get('company', ''),
                    quals,
                    certs,
                    p.get('profile_url', ''),
                    p.get('scraped_at', '')
                ])
            output.seek(0)
            resp = make_response(output.getvalue())
            resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
            resp.headers['Content-Disposition'] = f'attachment; filename={filename}'
            return resp
        return jsonify({'success': False, 'error': 'Invalid format'}), 400
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

#Export text data as PDF (For Full Profile Text Export)
@app.route('/api/export-text-pdf', methods=['POST'])
def export_text_pdf():
    try:
        from fpdf import FPDF
        data = request.json
        text = data.get('text', '')
        if not text:
            return jsonify({'success': False, 'error': 'No text provided'}), 400
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path("exports").mkdir(exist_ok=True)
        filename = f"linkedin_full_profile_{timestamp}.pdf"
        filepath = Path("exports") / filename
        
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=10)
        for line in text.split('\n'):
            safe_line = line.encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 5, safe_line, ln=True)
        pdf.output(str(filepath))
        return send_file(filepath, as_attachment=True, download_name=filename)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# =====================================================================
# CLIENT API SYSTEM (Two-Step Background Scrape & 1-Min Retrieval Delay)
# =====================================================================

# Lock for thread safety on API registry files
api_scrape_lock = threading.Lock()

# Directory settings
API_SCRAPES_DIR = Path("exports/api_scrapes")
API_SCRAPES_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE = API_SCRAPES_DIR / "jobs.json"
MASTER_CSV_FILE = API_SCRAPES_DIR / "scraped_profiles.csv"

# Persistent database settings
db_lock = threading.Lock()
ALL_PROFILES_JSON = Path("exports/all_scraped_profiles.json")
ALL_PROFILES_CSV = Path("exports/all_scraped_profiles.csv")
NAME_CACHE_FILE = Path("exports/name_cache.json")

if not NAME_CACHE_FILE.exists():
    NAME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(NAME_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f)

def save_to_persistent_db(profile):
    if not profile or 'error' in profile:
        return
        
    with db_lock:
        try:
            # Ensure parent directories exist
            ALL_PROFILES_JSON.parent.mkdir(parents=True, exist_ok=True)
            # 1. Update master JSON database
            profiles = []
            if ALL_PROFILES_JSON.exists():
                try:
                    with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                        profiles = json.load(f)
                except Exception:
                    profiles = []
                    
            # Avoid duplicate profile URLs in the master database (update if exists, otherwise append)
            url = profile.get('profile_url')
            updated = False
            for i, p in enumerate(profiles):
                if p.get('profile_url') == url:
                    profiles[i] = profile
                    updated = True
                    break
            if not updated:
                profiles.append(profile)
                
            with open(ALL_PROFILES_JSON, 'w', encoding='utf-8') as f:
                json.dump(profiles, f, indent=2, ensure_ascii=False)
                
            # 2. Rewrite master CSV database
            headers = [
                'name', 'headline', 'location', 'profile_picture', 'about', 
                'current_job', 'experience', 'qualifications', 'certifications', 
                'profile_url', 'scraped_at'
            ]
            
            with open(ALL_PROFILES_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for p in profiles:
                    writer.writerow([
                        p.get('name', ''),
                        p.get('headline', ''),
                        p.get('location', ''),
                        p.get('profile_picture', ''),
                        p.get('about', ''),
                        json.dumps(p.get('current_job', {})),
                        json.dumps(p.get('experience', [])),
                        json.dumps(p.get('qualifications', [])),
                        json.dumps(p.get('certifications', [])),
                        p.get('profile_url', ''),
                        p.get('scraped_at', '')
                    ])
        except Exception as e:
            print(f"Error saving to master database: {e}")

# Initialize jobs.json if not present
if not JOBS_FILE.exists():
    with open(JOBS_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f)

# API Key validation logic has been removed as per the automated system requirements.

def get_jobs_data():
    with api_scrape_lock:
        try:
            if JOBS_FILE.exists():
                with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
    return {}

def update_job_status(return_code, status, scraped_at=None, error=None):
    with api_scrape_lock:
        try:
            data = {}
            if JOBS_FILE.exists():
                with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            if return_code in data:
                data[return_code]['status'] = status
                if scraped_at:
                    data[return_code]['scraped_at'] = scraped_at
                if error:
                    data[return_code]['error'] = error
                with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error updating job status: {e}")

def create_job(return_code, profile_url, person_name=''):
    with api_scrape_lock:
        try:
            data = {}
            if JOBS_FILE.exists():
                with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            # Extract person_name from URL if not provided
            if not person_name and '/in/' in profile_url:
                person_name = profile_url.split('/in/')[1].strip('/').split('?')[0]
            data[return_code] = {
                'profile_url': profile_url,
                'person_name': person_name,
                'status': 'in_progress',
                'requested_at': datetime.now().isoformat(),
                'scraped_at': None,
                'error': None
            }
            with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error creating job: {e}")

def save_scraped_data_formats(profile, return_code):
    # Save JSON file
    json_path = API_SCRAPES_DIR / f"{return_code}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        
    # Save CSV file (headers matching JSON keys)
    csv_path = API_SCRAPES_DIR / f"{return_code}.csv"
    headers = [
        'name', 'headline', 'location', 'profile_picture', 'about', 
        'current_job', 'experience', 'qualifications', 'certifications', 
        'profile_url', 'scraped_at', 'return_code'
    ]
    
    row_data = [
        profile.get('name', ''),
        profile.get('headline', ''),
        profile.get('location', ''),
        profile.get('profile_picture', ''),
        profile.get('about', ''),
        json.dumps(profile.get('current_job', {})),
        json.dumps(profile.get('experience', [])),
        json.dumps(profile.get('qualifications', [])),
        json.dumps(profile.get('certifications', [])),
        profile.get('profile_url', ''),
        profile.get('scraped_at', ''),
        return_code
    ]
    
    # Save individual CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(row_data)
        
    # Append to master CSV file
    master_exists = MASTER_CSV_FILE.exists()
    with open(MASTER_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not master_exists:
            writer.writerow(headers)
        writer.writerow(row_data)

async def perform_background_scrape(profile_url, return_code):
    global scraper
    try:
        if not scraper:
            print("Auto-initializing scraper for background API request...")
            scraper = LinkedInScraper(headless=True, browser_type='chromium', session_name='default')
            await scraper.initialize()
            
        profile = await scraper.extract_profile(profile_url)
        
        if 'error' in profile:
            update_job_status(return_code, 'failed', error=profile['error'])
            print(f"Background scrape failed for {return_code}: {profile['error']}")
        else:
            scraped_at = datetime.now().isoformat()
            profile['scraped_at'] = scraped_at
            
            with api_scrape_lock:
                save_scraped_data_formats(profile, return_code)
                
            save_to_persistent_db(profile)
            update_job_status(return_code, 'completed', scraped_at=scraped_at)
            print(f"Background scrape succeeded for {return_code}")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job_status(return_code, 'failed', error=str(e))
        print(f"Background scrape exception for {return_code}: {e}")

async def perform_background_scrape_by_name(person_name, return_code):
    global scraper
    try:
        if not scraper:
            print("Auto-initializing scraper for background name-based request...")
            scraper = LinkedInScraper(headless=True, browser_type='chromium', session_name='default')
            await scraper.initialize()
            
        if person_name.startswith('http'):
            profile_url = person_name
            print(f"Direct URL provided: {profile_url}. Starting extraction...")
        else:
            print(f"Searching for person: '{person_name}'")
            results = await scraper.search_people(person_name, '', max_results=1, force_search=True)
            if not results:
                error_msg = f"No profile found for name: {person_name}"
                update_job_status(return_code, 'failed', error=error_msg)
                print(error_msg)
                return
                
            profile_url = results[0]['profile_url']
            print(f"Found profile URL for {person_name}: {profile_url}. Starting extraction...")
        
        with api_scrape_lock:
            try:
                data = {}
                if JOBS_FILE.exists():
                    with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                if return_code in data:
                    data[return_code]['profile_url'] = profile_url
                    with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)
            except Exception as e:
                print(f"Error updating job profile_url: {e}")
                
        profile = await scraper.extract_profile(profile_url)
        
        if 'error' in profile:
            update_job_status(return_code, 'failed', error=profile['error'])
            print(f"Background scrape failed for {return_code}: {profile['error']}")
        else:
            scraped_at = datetime.now().isoformat()
            profile['scraped_at'] = scraped_at
            
            with api_scrape_lock:
                save_scraped_data_formats(profile, return_code)
                
            save_to_persistent_db(profile)
            update_job_status(return_code, 'completed', scraped_at=scraped_at)
            print(f"Background scrape succeeded for {return_code}")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job_status(return_code, 'failed', error=str(e))
        print(f"Background scrape exception for {return_code}: {e}")

@app.route('/api/client/scrape', methods=['POST'])
def client_scrape():
    """
    Client search endpoint — routes ALL scrape requests through the Task Bucket.
    Returns the bucket task_id as the reference number immediately.
    The client polls /api/client/scrape-status?task_id=... to watch progress.
    """
    data = request.json or {}
    name = data.get('name', '').strip()

    if not name:
        return jsonify({'success': False, 'error': 'name is required'}), 400

    # --- Check cache first (instant return if already scraped) ---
    with db_lock:
        cache_data = {}
        if NAME_CACHE_FILE.exists():
            try:
                with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            except Exception:
                pass

    if name in cache_data:
        cached_urls = cache_data[name]
        all_profiles = []
        if ALL_PROFILES_JSON.exists():
            try:
                with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                    all_profiles = json.load(f)
            except Exception:
                pass
        results = [p for p in all_profiles if p.get('profile_url') in cached_urls]
        if results:
            return jsonify({
                'success': True, 'cached': True,
                'profiles': results, 'total': len(results),
                'reference_number': 'cached_' + name
            }), 200

    # --- Check if this name is already in the bucket (pending or in_progress) ---
    existing_tasks = _load_bucket_queue()
    for t in existing_tasks:
        if t.get('query') == name and t['status'] in ('pending', 'in_progress'):
            return jsonify({
                'success': True, 'status': t['status'],
                'reference_number': t['id'],
                'message': 'Already queued. Check back soon.'
            }), 202

    # --- Add to Task Bucket ---
    task = {
        'id': str(_uuid.uuid4()),
        'query': name,
        'type': 'search',
        'search_params': {
            'first_name': name,
            'last_name': '',
            'company': '',
            'max_results': 5,
        },
        'status': 'pending',
        'added_at': datetime.now().isoformat(),
        'started_at': None,
        'completed_at': None,
        'result_name': '',
        'result_url': '',
        'profiles_found': 0,
        'error': None,
        # Track which name this maps to for status look-ups
        '_client_name': name,
    }
    tasks = _load_bucket_queue()
    tasks.append(task)
    _save_bucket_queue(tasks)
    _broadcast_sse('bucket_tasks_added', {'count': 1, 'query': name})
    _ensure_worker_running()

    return jsonify({
        'success': True,
        'status': 'queued',
        'reference_number': task['id'],
        'message': 'Task queued in the bucket. The worker will process it automatically.'
    }), 202


@app.route('/api/client/scrape-status', methods=['GET'])
def client_scrape_status():
    """
    Poll the bucket queue for a task by its id (reference_number) or by name.
    Returns profiles from the master DB when the task is complete.
    """
    task_id = request.args.get('task_id', '').strip()
    name    = request.args.get('name', '').strip()

    if not task_id and not name:
        return jsonify({'success': False, 'error': 'task_id or name is required'}), 400

    tasks = _load_bucket_queue()

    # Find by task_id first, then by name
    task = None
    if task_id:
        task = next((t for t in tasks if t['id'] == task_id), None)
    if not task and name:
        # Try _client_name field, then query
        task = next((t for t in tasks if t.get('_client_name') == name or t.get('query') == name), None)

    if not task:
        # Maybe it already completed and was cleared from queue — check master DB
        all_profiles = []
        if ALL_PROFILES_JSON.exists():
            try:
                with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                    all_profiles = json.load(f)
            except Exception:
                pass
        # Check name cache
        with db_lock:
            cache_data = {}
            if NAME_CACHE_FILE.exists():
                try:
                    with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                except Exception:
                    pass
        if name and name in cache_data:
            cached_urls = cache_data[name]
            results = [p for p in all_profiles if p.get('profile_url') in cached_urls]
            if results:
                return jsonify({'success': True, 'status': 'completed', 'profiles': results, 'total': len(results)}), 200
        return jsonify({'success': False, 'error': 'Task not found'}), 404

    status = task['status']

    if status in ('pending', 'in_progress'):
        return jsonify({
            'success': True,
            'status': status,
            'message': 'Queued in Task Bucket — the worker will process it automatically.' if status == 'pending'
                       else 'Currently scraping LinkedIn profiles…'
        }), 202

    if status == 'failed':
        return jsonify({
            'success': False,
            'status': 'failed',
            'error': task.get('error', 'Unknown error')
        }), 200

    # Completed — load profiles from master DB
    if status == 'completed':
        search_name = task.get('_client_name') or task.get('query', name)
        all_profiles = []
        if ALL_PROFILES_JSON.exists():
            try:
                with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                    all_profiles = json.load(f)
            except Exception:
                pass

        # Check name cache
        with db_lock:
            cache_data = {}
            if NAME_CACHE_FILE.exists():
                try:
                    with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                except Exception:
                    pass

        if search_name in cache_data:
            cached_urls = cache_data[search_name]
            results = [p for p in all_profiles if p.get('profile_url') in cached_urls]
            if results:
                return jsonify({'success': True, 'status': 'completed', 'profiles': results, 'total': len(results)}), 200

        # Fallback: return most recently scraped profiles whose name matches
        results = [p for p in all_profiles if search_name.lower() in (p.get('name') or '').lower()]
        if results:
            return jsonify({'success': True, 'status': 'completed', 'profiles': results[:10], 'total': len(results)}), 200

        return jsonify({
            'success': True, 'status': 'completed',
            'profiles': [], 'total': 0,
            'message': 'Task completed but no matching profiles were found in the database.'
        }), 200

    return jsonify({'success': False, 'error': f'Unknown status: {status}'}), 500


@app.route('/api/client/retrieve', methods=['GET', 'POST'])
def client_retrieve():
    # Support both GET query parameters and POST JSON body
    if request.method == 'POST':
        data = request.json or {}
        return_code = data.get('return_code', '').strip()
    else:
        return_code = request.args.get('return_code', '').strip()
        
    if not return_code:
        return jsonify({'success': False, 'error': 'return_code is required'}), 400
        
    jobs = get_jobs_data()
    if return_code not in jobs:
        approvals = get_approvals_data()
        if return_code in approvals:
            return jsonify({
                'success': False,
                'status': 'pending',
                'message': 'Waiting for admin approval or scrape to start'
            })
        return jsonify({'success': False, 'error': 'No scrape request found for the provided return_code'}), 404
        
    job = jobs[return_code]
    
    status = job.get('status')
    if status == 'in_progress':
        return jsonify({
            'success': False,
            'status': 'in_progress',
            'message': 'Profile is still being scraped. Please try again later.'
        })

    elif status == 'failed':
        return jsonify({
            'success': False,
            'status': 'failed',
            'error': job.get('error', 'Unknown scraping error')
        })
    elif status == 'completed':
        scraped_at_str = job.get('scraped_at')
        if not scraped_at_str:
            return jsonify({'success': False, 'error': 'Invalid job state (missing completion time)'}), 500
            
        # Load and return JSON profile data
        json_path = API_SCRAPES_DIR / f"{return_code}.json"
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)
            return jsonify({
                'success': True,
                'status': 'completed',
                'profile': profile_data,
                'csv_url': f"/api/client/download/csv?return_code={return_code}"
            })
        except Exception as e:
            return jsonify({'success': False, 'error': f'Error loading profile data: {str(e)}'}), 500

# Route to download the specific CSV file
@app.route('/api/client/download/csv', methods=['GET'])
def client_download_csv():
    return_code = request.args.get('return_code', '').strip()
    if not return_code:
        return jsonify({'success': False, 'error': 'return_code is required'}), 400
        
    jobs = get_jobs_data()
    if return_code not in jobs:
        return jsonify({'success': False, 'error': 'No scrape request found for the provided return_code'}), 404
        
    job = jobs[return_code]
        
    status = job.get('status')
    if status != 'completed':
        return jsonify({'success': False, 'error': f'Cannot download CSV. Job is in state: {status}'}), 400
        
    csv_path = API_SCRAPES_DIR / f"{return_code}.csv"
    if not csv_path.exists():
        return jsonify({'success': False, 'error': 'CSV file does not exist on disk'}), 404
        
    return send_file(csv_path, as_attachment=True, download_name=f"{return_code}.csv", mimetype='text/csv')

# Route to download the specific JSON file
@app.route('/api/client/download/json', methods=['GET'])
def client_download_json():
    return_code = request.args.get('return_code', '').strip()
    if not return_code:
        return jsonify({'success': False, 'error': 'return_code is required'}), 400
        
    jobs = get_jobs_data()
    if return_code not in jobs:
        return jsonify({'success': False, 'error': 'No scrape request found for the provided return_code'}), 404
        
    job = jobs[return_code]
        
    status = job.get('status')
    if status != 'completed':
        return jsonify({'success': False, 'error': f'Cannot download JSON. Job is in state: {status}'}), 400
        
    json_path = API_SCRAPES_DIR / f"{return_code}.json"
    if not json_path.exists():
        return jsonify({'success': False, 'error': 'JSON file does not exist on disk'}), 404
        
    return send_file(json_path, as_attachment=True, download_name=f"{return_code}.json", mimetype='application/json')

# Route to download the specific PDF file
import re
import urllib.request
import tempfile
from fpdf import FPDF

def strip_emojis(text):
    if not text:
        return ""
    emoji_pattern = re.compile(
        "["
        "\U00010000-\U0010ffff"
        "\u2600-\u27BF"
        "\u2000-\u32FF"
        "]+", flags=re.UNICODE
    )
    return emoji_pattern.sub(r"", text)

def make_pdf_safe(text):
    if not text:
        return "N/A"
    clean = strip_emojis(text)
    return clean.encode('latin-1', 'replace').decode('latin-1')

def download_profile_pic(url):
    try:
        import tempfile
        import os
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"profile_{os.urandom(4).hex()}.jpg")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.linkedin.com/'
        }
        response = requests.get(url, headers=headers, stream=True, timeout=10)
        response.raise_for_status()
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return temp_path
    except Exception as e:
        print(f"Failed to download image from {url}: {e}")
        return None

class PDF(FPDF):
    def header(self):
        # Banner background
        self.set_fill_color(10, 102, 194) # LinkedIn Blue
        self.rect(0, 0, 210, 35, 'F')
        
        # Title text
        self.set_text_color(255, 255, 255)
        self.set_font("Arial", 'B', 18)
        self.cell(0, 15, "LINKEDIN PROFILE REPORT", ln=True, align='L')
        self.ln(10)
        
    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def build_profile_pdf(pdf, p):
    image_path = None
    if p.get('profile_picture'):
        image_path = download_profile_pic(p['profile_picture'])
        
    pdf.set_y(40)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 16)
    name_line = make_pdf_safe(p.get('name', 'Unknown Name'))
    pdf.cell(130, 8, name_line, ln=True)
    
    pdf.set_font("Arial", size=10)
    pdf.set_text_color(80, 80, 80)
    headline_line = make_pdf_safe(p.get('headline', 'N/A'))
    pdf.multi_cell(130, 5, headline_line)
    pdf.ln(2)
    
    location_line = make_pdf_safe(f"Location: {p.get('location', 'N/A')}")
    pdf.cell(130, 5, location_line, ln=True)
    
    url_line = make_pdf_safe(f"URL: {p.get('profile_url', 'N/A')}")
    pdf.cell(130, 5, url_line, ln=True)
    
    if p.get('connections'):
        conn_line = make_pdf_safe(f"Connections: {p.get('connections')}")
        pdf.cell(130, 5, conn_line, ln=True)
        
    pdf.ln(5)
    if image_path:
        try:
            pdf.image(image_path, x=15, y=pdf.get_y(), w=40, h=40)
            pdf.ln(45)
        except Exception as e:
            print(f"Error embedding image: {e}")
            
    current_y = pdf.get_y()
    if current_y < 85 and not image_path:
        pdf.set_y(85)
    
    # --- ABOUT ---
    if p.get('about'):
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "ABOUT", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(30, 30, 30)
        about_text = make_pdf_safe(p.get('about', ''))
        pdf.multi_cell(0, 5, about_text)
        pdf.ln(5)
        
    # --- EXPERIENCE ---
    exp_list = p.get('experiences', []) or p.get('experience', [])
    if exp_list:
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "EXPERIENCE", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        for exp in exp_list:
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            title = make_pdf_safe(exp.get('title', 'N/A'))
            company = make_pdf_safe(exp.get('company', 'N/A'))
            duration = make_pdf_safe(exp.get('duration', ''))
            loc = make_pdf_safe(exp.get('location', ''))
            
            pdf.multi_cell(0, 5, f"{title} at {company}")
            pdf.set_font("Arial", 'I', 9)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 5, f"{duration} | {loc}" if loc else duration, ln=True)
            pdf.ln(3)
        pdf.ln(2)

    # --- EDUCATION ---
    edu_list = p.get('education', []) or p.get('qualifications', [])
    if edu_list:
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "EDUCATION / QUALIFICATIONS", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        for edu in edu_list:
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            inst = make_pdf_safe(edu.get('institution', 'N/A'))
            deg = make_pdf_safe(edu.get('degree', 'N/A'))
            dates = make_pdf_safe(edu.get('dates', ''))
            
            pdf.multi_cell(0, 5, f"{inst} - {deg}")
            pdf.set_font("Arial", 'I', 9)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 5, dates, ln=True)
            pdf.ln(3)
        pdf.ln(2)

    # --- SKILLS ---
    skills_list = p.get('skills', [])
    if skills_list:
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "SKILLS", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(30, 30, 30)
        skills_formatted = []
        for s in skills_list:
            if isinstance(s, dict):
                skill_name = s.get('skill', '')
                ends = s.get('endorsements', '')
                skills_formatted.append(f"{skill_name} ({ends})" if ends else skill_name)
            else:
                skills_formatted.append(str(s))
        
        pdf.multi_cell(0, 5, make_pdf_safe(", ".join(skills_formatted)))
        pdf.ln(5)

    # --- CERTIFICATIONS ---
    cert_list = p.get('certifications', [])
    if cert_list:
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "CERTIFICATIONS", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        for cert in cert_list:
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            cname = make_pdf_safe(cert.get('name', 'N/A'))
            issuer = make_pdf_safe(cert.get('issuer', 'N/A'))
            date = make_pdf_safe(cert.get('date', ''))
            
            pdf.cell(0, 5, f"{cname} - {issuer} ({date})", ln=True)
            pdf.ln(2)
        pdf.ln(2)

    # --- LANGUAGES ---
    lang_list = p.get('languages', [])
    if lang_list:
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "LANGUAGES", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(30, 30, 30)
        langs_formatted = []
        for l in lang_list:
            if isinstance(l, dict):
                lang_name = l.get('language', '')
                prof = l.get('proficiency', '')
                langs_formatted.append(f"{lang_name} ({prof})" if prof else lang_name)
            else:
                langs_formatted.append(str(l))
        pdf.multi_cell(0, 5, make_pdf_safe(", ".join(langs_formatted)))
        pdf.ln(5)

    # --- VOLUNTEER EXPERIENCE ---
    vol_list = p.get('volunteer', [])
    if vol_list:
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "VOLUNTEER EXPERIENCE", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        for vol in vol_list:
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            role = make_pdf_safe(vol.get('role', 'N/A'))
            org = make_pdf_safe(vol.get('organization', 'N/A'))
            dur = make_pdf_safe(vol.get('duration', ''))
            
            pdf.multi_cell(0, 5, f"{role} at {org}")
            if dur:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 5, dur, ln=True)
            pdf.ln(3)
        pdf.ln(2)

    # --- HONORS & AWARDS ---
    hon_list = p.get('honors', [])
    if hon_list:
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "HONORS & AWARDS", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        for hon in hon_list:
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            title = make_pdf_safe(hon.get('title', 'N/A'))
            issuer = make_pdf_safe(hon.get('issuer', 'N/A'))
            date = make_pdf_safe(hon.get('date', ''))
            
            pdf.multi_cell(0, 5, f"{title} - {issuer}" if issuer else title)
            if date:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 5, date, ln=True)
            pdf.ln(3)
        pdf.ln(2)

    # --- RECOMMENDATIONS ---
    rec_list = p.get('recommendations', [])
    if rec_list:
        pdf.set_font("Arial", 'B', 12)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(0, 6, "RECOMMENDATIONS", ln=True)
        pdf.set_fill_color(10, 102, 194)
        pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
        pdf.ln(3)
        
        for rec in rec_list:
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            recommender = make_pdf_safe(rec.get('recommender', 'N/A'))
            title = make_pdf_safe(rec.get('title', 'N/A'))
            text_val = make_pdf_safe(rec.get('text', 'N/A'))
            
            pdf.cell(0, 5, f"Recommender: {recommender} ({title})", ln=True)
            pdf.set_font("Arial", 'I', 9)
            pdf.set_text_color(50, 50, 50)
            pdf.multi_cell(0, 4, text_val)
            pdf.ln(3)
        pdf.ln(2)

    if image_path and os.path.exists(image_path):
        try:
            os.remove(image_path)
        except:
            pass

@app.route('/api/client/download/pdf', methods=['GET'])
def client_download_pdf():
    return_code = request.args.get('return_code', '').strip()
    if not return_code:
        return jsonify({'success': False, 'error': 'return_code is required'}), 400
        
    jobs = get_jobs_data()
    if return_code not in jobs:
        return jsonify({'success': False, 'error': 'No scrape request found for the provided return_code'}), 404
        
    job = jobs[return_code]
    status = job.get('status')
    if status != 'completed':
        return jsonify({'success': False, 'error': f'Cannot download PDF. Job is in state: {status}'}), 400
        
    json_path = API_SCRAPES_DIR / f"{return_code}.json"
    if not json_path.exists():
        return jsonify({'success': False, 'error': 'Data file does not exist on disk'}), 404
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            p = json.load(f)
            
        pdf_path = API_SCRAPES_DIR / f"{return_code}.pdf"
        pdf = PDF()
        pdf.add_page()
        pdf.set_margins(15, 40, 15)
        pdf.set_auto_page_break(True, margin=15)
        
        build_profile_pdf(pdf, p)
        
        pdf.output(str(pdf_path))
        return send_file(pdf_path, as_attachment=True, download_name=f"{return_code}.pdf", mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': f'Error generating PDF: {str(e)}'}), 500

@app.route('/api/export-profile-pdf', methods=['POST'])
def export_profile_pdf():
    try:
        data = request.json or {}
        p = data.get('profile')
        if not p:
            return jsonify({'success': False, 'error': 'profile data is required'}), 400
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path("exports").mkdir(exist_ok=True)
        filename = f"linkedin_profile_{timestamp}.pdf"
        filepath = Path("exports") / filename
        
        pdf = PDF()
        pdf.add_page()
        pdf.set_margins(15, 40, 15)
        pdf.set_auto_page_break(True, margin=15)
        
        build_profile_pdf(pdf, p)
        
        pdf.output(str(filepath))
        return send_file(filepath, as_attachment=True, download_name=filename, mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': f'Error exporting PDF: {str(e)}'}), 500

@app.route('/api/export-bulk-pdf', methods=['POST'])
def export_bulk_pdf():
    try:
        data = request.json or {}
        profiles = data.get('profiles', [])
        if not profiles:
            return jsonify({'success': False, 'error': 'profiles list is required'}), 400
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path("exports").mkdir(exist_ok=True)
        filename = f"linkedin_bulk_profiles_{timestamp}.pdf"
        filepath = Path("exports") / filename
        
        pdf = PDF()
        pdf.set_margins(15, 40, 15)
        pdf.set_auto_page_break(True, margin=15)
        
        for p in profiles:
            pdf.add_page()
            build_profile_pdf(pdf, p)
            
        pdf.output(str(filepath))
        return send_file(filepath, as_attachment=True, download_name=filename, mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': f'Error exporting bulk PDF: {str(e)}'}), 500

# =====================================================================
# API REQUESTS MONITORING & PERSONA BULK SCRAPER
# =====================================================================

# Legacy approvals file — kept for backward compatibility if it exists
APPROVALS_FILE = API_SCRAPES_DIR / "approvals.json"
if not APPROVALS_FILE.exists():
    with open(APPROVALS_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f)

def get_approvals_data():
    """Legacy helper — kept for backward compat. Returns empty dict."""
    return {}

# Admin: List all scrape requests (monitoring dashboard — reads from jobs.json and task bucket queue)
@app.route('/api/admin/approvals', methods=['GET'])
def admin_list_approvals():
    jobs = get_jobs_data()
    tasks = _load_bucket_queue()
    
    requests_list = []
    seen_ids = set()

    # Add items from task bucket queue
    for task in tasks:
        task_id = task.get('id')
        seen_ids.add(task_id)
        
        status = task.get('status', 'unknown')
        if status == 'completed':
            status = 'completed'
        elif status == 'in_progress':
            status = 'in_progress'
        elif status == 'failed':
            status = 'failed'
        else:
            status = 'pending'

        requests_list.append({
            'request_id': task_id,
            'reference_number': task_id,
            'person_name': task.get('query', ''),
            'profile_url': task.get('result_url', ''),
            'status': status,
            'requested_at': task.get('added_at', ''),
            'scraped_at': task.get('completed_at', ''),
            'error': task.get('error', '')
        })

    # Add items from jobs.json (only if not already added from the bucket)
    for job_id, job in jobs.items():
        if job_id in seen_ids:
            continue
        requests_list.append({
            'request_id': job_id,
            'reference_number': job_id,
            'person_name': job.get('person_name', job.get('profile_url', '')),
            'profile_url': job.get('profile_url', ''),
            'status': job.get('status', 'unknown'),
            'requested_at': job.get('requested_at', ''),
            'scraped_at': job.get('scraped_at', ''),
            'error': job.get('error', '')
        })

    # Sort newest first
    requests_list.sort(key=lambda x: x.get('requested_at', ''), reverse=True)
    return jsonify({'success': True, 'approvals': requests_list})


# Admin: Retry/re-scrape a failed or stalled request
@app.route('/api/admin/approve', methods=['POST'])
def admin_approve():
    """Repurposed: now triggers a re-scrape for a failed/stalled job or task bucket item."""
    try:
        data = request.get_json(force=True)
        request_id = data.get('request_id')
        if not request_id:
            return jsonify({'success': False, 'error': 'Missing request_id'}), 400

        # Check in task bucket first
        tasks = _load_bucket_queue()
        task = next((t for t in tasks if t['id'] == request_id), None)
        if task:
            # Reset task state to pending
            _update_bucket_task(request_id, status='pending', started_at=None, completed_at=None, error=None)
            _broadcast_sse('bucket_update', {'task_id': request_id, 'status': 'pending', 'query': task.get('query', '')})
            _ensure_worker_running()
            return jsonify({'success': True, 'message': f'Re-scrape triggered in Task Bucket for request {request_id}.'})

        jobs = get_jobs_data()
        if request_id not in jobs:
            return jsonify({'success': False, 'error': 'No job found for the provided ID'}), 404

        job = jobs[request_id]
        profile_url = job.get('profile_url')
        person_name = job.get('person_name', '')

        # Reset job status to in_progress and restart scrape
        update_job_status(request_id, 'in_progress')

        if profile_url:
            asyncio.run_coroutine_threadsafe(
                perform_background_scrape(profile_url, request_id),
                _bg_loop
            )
        else:
            asyncio.run_coroutine_threadsafe(
                perform_background_scrape_by_name(person_name, request_id),
                _bg_loop
            )

        return jsonify({'success': True, 'message': f'Re-scrape triggered for request {request_id}.'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# Admin: Scrape a requested person name using the active scraper session
@app.route('/api/admin/scrape-requested-name', methods=['POST'])
def admin_scrape_requested_name():
    global scraper
    if not scraper or not scraper.is_authenticated:
        return jsonify({'success': False, 'error': 'Scraper is not initialized or logged in.'}), 400
        
    try:
        data = request.get_json(force=True)
        person_name = data.get('person_name', '').strip()
        request_id = data.get('request_id', '').strip()
        
        if not person_name or not request_id:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
            
        # Search and extract
        async def do_search_and_extract():
            if person_name.startswith('http'):
                profile_url = person_name
            else:
                results = await scraper.search_people(person_name, '', max_results=1, force_search=True)
                if not results:
                    return {'success': False, 'error': f"No profile found for name: {person_name}"}
                profile_url = results[0]['profile_url']
                
            profile = await scraper.extract_profile(profile_url)
            return {'success': True, 'profile': profile, 'profile_url': profile_url}
            
        result = run_async(do_search_and_extract())
        if not result['success']:
            return jsonify({'success': False, 'error': result['error']}), 404
            
        profile = result['profile']
        profile_url = result['profile_url']
        
        if 'error' in profile:
            return jsonify({'success': False, 'error': profile['error']}), 500
            
        scraped_at = datetime.now().isoformat()
        profile['scraped_at'] = scraped_at
        
        with api_scrape_lock:
            save_scraped_data_formats(profile, request_id)
            
        save_to_persistent_db(profile)
        
        with api_scrape_lock:
            # Create job in jobs.json
            jobs_data = {}
            if JOBS_FILE.exists():
                with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                    jobs_data = json.load(f)
            jobs_data[request_id] = {
                'request_id': request_id,
                'profile_url': profile_url,
                'person_name': person_name,
                'status': 'completed',
                'requested_at': datetime.now().isoformat(),
                'scraped_at': scraped_at,
                'error': None
            }
            with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                json.dump(jobs_data, f, indent=2)
                
            # Update approvals.json
            data_store = {}
            if APPROVALS_FILE.exists():
                with open(APPROVALS_FILE, 'r', encoding='utf-8') as f:
                    data_store = json.load(f)
            if request_id in data_store:
                data_store[request_id]['status'] = 'approved'
                with open(APPROVALS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data_store, f, indent=2)
                    
        return jsonify({'success': True, 'profile': profile})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# Admin: download master JSON database
@app.route('/api/admin/download-db/json', methods=['GET'])
def admin_download_db_json():
    if not ALL_PROFILES_JSON.exists():
        return jsonify({'success': False, 'error': 'Database is empty or does not exist yet.'}), 404
    try:
        return send_file(ALL_PROFILES_JSON, as_attachment=True, download_name="all_scraped_profiles.json", mimetype='application/json')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Admin: download master CSV database
@app.route('/api/admin/download-db/csv', methods=['GET'])
def admin_download_db_csv():
    if not ALL_PROFILES_CSV.exists():
        return jsonify({'success': False, 'error': 'Database is empty or does not exist yet.'}), 404
    try:
        return send_file(ALL_PROFILES_CSV, as_attachment=True, download_name="all_scraped_profiles.csv", mimetype='text/csv')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Admin: get all master database profiles
@app.route('/api/admin/db-profiles', methods=['GET'])
def admin_db_profiles():
    profiles = []
    if ALL_PROFILES_JSON.exists():
        with db_lock:
            try:
                with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
            except Exception as e:
                return jsonify({'success': False, 'error': f'Error reading database: {str(e)}'}), 500
    return jsonify({'success': True, 'profiles': profiles})

# Admin: destroy master database
@app.route('/api/admin/destroy-db', methods=['POST'])
def destroy_db():
    try:
        with db_lock:
            if ALL_PROFILES_JSON.exists():
                ALL_PROFILES_JSON.unlink()
            if ALL_PROFILES_CSV.exists():
                ALL_PROFILES_CSV.unlink()
        with api_scrape_lock:
            if JOBS_FILE.exists():
                JOBS_FILE.unlink()
            if API_SCRAPES_DIR.exists():
                for f in API_SCRAPES_DIR.glob('*'):
                    if f.is_file():
                        try:
                            f.unlink()
                        except Exception:
                            pass
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Background Bulk scraping worker
async def perform_background_bulk_scrape(profile_urls, return_code):
    global scraper
    try:
        if not scraper:
            print("Auto-initializing scraper for background bulk API request...")
            scraper = LinkedInScraper(headless=True, browser_type='chromium', session_name='default')
            await scraper.initialize()
            
        scraped_profiles = []
        errors = []
        
        for idx, url in enumerate(profile_urls):
            print(f"Bulk scraping {idx+1}/{len(profile_urls)}: {url}")
            profile = await scraper.extract_profile(url)
            if 'error' in profile:
                errors.append(f"{url}: {profile['error']}")
            else:
                scraped_profiles.append(profile)
            
            if idx < len(profile_urls) - 1:
                await asyncio.sleep(4)
        
        scraped_at = datetime.now().isoformat()
        
        with api_scrape_lock:
            # Save JSON containing list of profiles
            json_path = API_SCRAPES_DIR / f"{return_code}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({'profiles': scraped_profiles}, f, indent=2, ensure_ascii=False)
                
            # Save CSV file containing all scraped profiles
            csv_path = API_SCRAPES_DIR / f"{return_code}.csv"
            headers = [
                'name', 'headline', 'location', 'profile_picture', 'about', 
                'current_job', 'experience', 'qualifications', 'certifications', 
                'profile_url', 'scraped_at', 'return_code'
            ]
            
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for profile in scraped_profiles:
                    profile['scraped_at'] = scraped_at
                    writer.writerow([
                        profile.get('name', ''),
                        profile.get('headline', ''),
                        profile.get('location', ''),
                        profile.get('profile_picture', ''),
                        profile.get('about', ''),
                        json.dumps(profile.get('current_job', {})),
                        json.dumps(profile.get('experience', [])),
                        json.dumps(profile.get('qualifications', [])),
                        json.dumps(profile.get('certifications', [])),
                        profile.get('profile_url', ''),
                        profile.get('scraped_at', ''),
                        return_code
                    ])
            
            # Append each to master CSV
            master_exists = MASTER_CSV_FILE.exists()
            with open(MASTER_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not master_exists:
                    writer.writerow(headers)
                for profile in scraped_profiles:
                    writer.writerow([
                        profile.get('name', ''),
                        profile.get('headline', ''),
                        profile.get('location', ''),
                        profile.get('profile_picture', ''),
                        profile.get('about', ''),
                        json.dumps(profile.get('current_job', {})),
                        json.dumps(profile.get('experience', [])),
                        json.dumps(profile.get('qualifications', [])),
                        json.dumps(profile.get('certifications', [])),
                        profile.get('profile_url', ''),
                        profile.get('scraped_at', ''),
                        return_code
                    ])
                    
        for profile in scraped_profiles:
            save_to_persistent_db(profile)
        
        if not scraped_profiles and errors:
            update_job_status(return_code, 'failed', error="All profile scrapes failed: " + "; ".join(errors))
        else:
            update_job_status(return_code, 'completed', scraped_at=scraped_at, error="; ".join(errors) if errors else None)
            
        print(f"Background bulk scrape completed for {return_code}")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job_status(return_code, 'failed', error=str(e))
        print(f"Background bulk scrape exception for {return_code}: {e}")

# Bulk Scraper Route (Branded as PERSONA)
@app.route('/api/persona/bulk-scrape', methods=['POST'])
def persona_bulk_scrape():
        
    data = request.json or {}
    profile_urls = data.get('profile_urls', [])
    return_code = data.get('return_code', '').strip()
    
    if not profile_urls or not return_code:
        return jsonify({'success': False, 'error': 'profile_urls (list) and return_code are required'}), 400
        
    if not isinstance(profile_urls, list):
        return jsonify({'success': False, 'error': 'profile_urls must be a list of URLs'}), 400
        
    jobs = get_jobs_data()
    if return_code in jobs:
        status = jobs[return_code].get('status')
        if status in ['in_progress', 'completed']:
            return jsonify({
                'success': True,
                'message': f'Bulk scrape job is already {status}',
                'return_code': return_code,
                'status': status
            })
            
    with api_scrape_lock:
        try:
            data_store = {}
            if JOBS_FILE.exists():
                with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                    data_store = json.load(f)
            data_store[return_code] = {
                'profile_url': profile_urls[0] if profile_urls else "",
                'profile_urls': profile_urls,
                'is_bulk': True,
                'status': 'in_progress',
                'requested_at': datetime.now().isoformat(),
                'scraped_at': None,
                'error': None
            }
            with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data_store, f, indent=2)
        except Exception as e:
            return jsonify({'success': False, 'error': f'Error creating bulk job: {str(e)}'}), 500
            
    asyncio.run_coroutine_threadsafe(perform_background_bulk_scrape(profile_urls, return_code), _bg_loop)
    
    return jsonify({
        'success': True,
        'message': 'Bulk scrape request queued successfully in background.',
        'return_code': return_code,
        'status': 'in_progress'
    }), 202

# Bulk Retrieval Route (Branded as PERSONA)
@app.route('/api/persona/bulk-retrieve', methods=['GET', 'POST'])
def persona_bulk_retrieve():
        
    if request.method == 'POST':
        data = request.json or {}
        return_code = data.get('return_code', '').strip()
    else:
        return_code = request.args.get('return_code', '').strip()
        
    if not return_code:
        return jsonify({'success': False, 'error': 'return_code is required'}), 400
        
    jobs = get_jobs_data()
    if return_code not in jobs:
        return jsonify({'success': False, 'error': 'No bulk scrape request found for the provided return_code'}), 404
        
    job = jobs[return_code]
        
    status = job.get('status')
    if status == 'in_progress':
        return jsonify({
            'success': False,
            'status': 'in_progress',
            'message': 'Bulk profile scraping is still in progress. Please try again later.'
        })
    elif status == 'failed':
        return jsonify({
            'success': False,
            'status': 'failed',
            'error': job.get('error', 'Unknown scraping error')
        })
    elif status == 'completed':
        scraped_at_str = job.get('scraped_at')
        if not scraped_at_str:
            return jsonify({'success': False, 'error': 'Invalid job state (missing completion time)'}), 500
            
        scraped_time = datetime.fromisoformat(scraped_at_str)
        elapsed_seconds = (datetime.now() - scraped_time).total_seconds()
        
        if elapsed_seconds < 60:
            remaining = 60 - elapsed_seconds
            return jsonify({
                'success': False,
                'status': 'waiting_delay',
                'message': f'Bulk scrape completed, but data cannot be retrieved yet. Under the 1-minute delay policy, you must wait another {int(remaining)} seconds.',
                'remaining_seconds': int(remaining)
            })
            
        json_path = API_SCRAPES_DIR / f"{return_code}.json"
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                bulk_data = json.load(f)
            return jsonify({
                'success': True,
                'status': 'completed',
                'profiles': bulk_data.get('profiles', []),
                'csv_url': f"/api/client/download/csv?return_code={return_code}",
                'pdf_url': f"/api/client/download/pdf?return_code={return_code}"
            })
        except Exception as e:
            return jsonify({'success': False, 'error': f'Error loading bulk profile data: {str(e)}'}), 500


# =====================================================================
# REFERENCE NUMBER LOOKUP — Client-facing endpoint
# =====================================================================

@app.route('/api/client/lookup-by-reference', methods=['GET', 'POST'])
def client_lookup_by_reference():
    """
    Allow clients to retrieve scraped profile data using a reference number
    (the job/request_id shown in the admin panel and returned when a scrape starts).
    Supports both GET (?reference_number=...) and POST (JSON body).
    """
    if request.method == 'POST':
        data = request.json or {}
        reference_number = data.get('reference_number', '').strip()
    else:
        reference_number = request.args.get('reference_number', '').strip()

    if not reference_number:
        return jsonify({'success': False, 'error': 'reference_number is required'}), 400

    # Normalise: strip leading '#' if user copied it from the admin UI
    if reference_number.startswith('#'):
        reference_number = reference_number[1:].strip()

    jobs = get_jobs_data()
    if reference_number not in jobs:
        return jsonify({
            'success': False,
            'error': 'No scrape request found for the provided reference number. '
                     'Please check the number and try again.'
        }), 404

    job = jobs[reference_number]
    status = job.get('status')

    if status == 'in_progress':
        return jsonify({
            'success': False,
            'status': 'in_progress',
            'reference_number': reference_number,
            'person_name': job.get('person_name', ''),
            'requested_at': job.get('requested_at', ''),
            'message': 'This profile is still being scraped. Please try again in a few seconds.'
        }), 202

    elif status == 'failed':
        return jsonify({
            'success': False,
            'status': 'failed',
            'reference_number': reference_number,
            'person_name': job.get('person_name', ''),
            'error': job.get('error', 'The scrape job failed. Please contact the admin.')
        }), 200

    elif status == 'completed':
        # Try to load individual JSON file first (single-profile scrape)
        json_path = API_SCRAPES_DIR / f"{reference_number}.json"
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)

                # Handle bulk scrape format {'profiles': [...]}
                if isinstance(raw, dict) and 'profiles' in raw:
                    profiles = raw['profiles']
                    return jsonify({
                        'success': True,
                        'status': 'completed',
                        'reference_number': reference_number,
                        'person_name': job.get('person_name', ''),
                        'scraped_at': job.get('scraped_at', ''),
                        'is_bulk': True,
                        'profiles': profiles,
                        'total': len(profiles)
                    })
                else:
                    # Single profile
                    return jsonify({
                        'success': True,
                        'status': 'completed',
                        'reference_number': reference_number,
                        'person_name': job.get('person_name', ''),
                        'scraped_at': job.get('scraped_at', ''),
                        'is_bulk': False,
                        'profiles': [raw],
                        'total': 1
                    })
            except Exception as e:
                return jsonify({'success': False, 'error': f'Error reading profile data: {str(e)}'}), 500

        # Fallback: search the master JSON database by name cache
        person_name = job.get('person_name', '')
        if person_name:
            with db_lock:
                cache_data = {}
                if NAME_CACHE_FILE.exists():
                    try:
                        with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                    except Exception:
                        pass
            if person_name in cache_data:
                cached_urls = cache_data[person_name]
                all_profiles = []
                if ALL_PROFILES_JSON.exists():
                    try:
                        with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                            all_profiles = json.load(f)
                    except Exception:
                        pass
                results = [p for p in all_profiles if p.get('profile_url') in cached_urls]
                if results:
                    return jsonify({
                        'success': True,
                        'status': 'completed',
                        'reference_number': reference_number,
                        'person_name': person_name,
                        'scraped_at': job.get('scraped_at', ''),
                        'is_bulk': len(results) > 1,
                        'profiles': results,
                        'total': len(results)
                    })

        return jsonify({
            'success': False,
            'error': 'Profile data file not found on server. It may have been cleared.'
        }), 404

    return jsonify({'success': False, 'error': f'Unknown job status: {status}'}), 500


# SSE endpoint for admin live updates — streams events to connected admin dashboards
@app.route('/api/admin/events', methods=['GET'])
def admin_events():
    q = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_subscribers.append(q)

    def event_stream():
        try:
            # Send a heartbeat first so the browser knows we're connected
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = q.get(timeout=25)
                    yield f'data: {payload}\n\n'
                except queue.Empty:
                    # Send keepalive ping every 25 s so connection stays open
                    yield ': ping\n\n'
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                try:
                    _sse_subscribers.remove(q)
                except ValueError:
                    pass

    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )

# =====================================================================
# TASK BUCKET — Persistent queue processed one-by-one with rest periods
# =====================================================================

import uuid as _uuid

# ── Storage ─────────────────────────────────────────────────────────────────
BUCKET_DIR = Path("exports/task_bucket")
BUCKET_DIR.mkdir(parents=True, exist_ok=True)
BUCKET_QUEUE_FILE = BUCKET_DIR / "queue.json"
BUCKET_CONFIG_FILE = BUCKET_DIR / "config.json"

bucket_lock = threading.Lock()

# ── Worker state ─────────────────────────────────────────────────────────────
_bucket_worker_paused = False
_bucket_worker_running = False  # True while worker coroutine is alive


def _load_bucket_queue():
    """Return list of task dicts from queue.json."""
    with bucket_lock:
        if BUCKET_QUEUE_FILE.exists():
            try:
                with open(BUCKET_QUEUE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return []


def _save_bucket_queue(tasks: list):
    with bucket_lock:
        BUCKET_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(BUCKET_QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)


def _load_bucket_config():
    try:
        if BUCKET_CONFIG_FILE.exists():
            with open(BUCKET_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {'rest_seconds': 30}


def _save_bucket_config(cfg: dict):
    with open(BUCKET_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


def _update_bucket_task(task_id: str, **kwargs):
    """Atomically update fields on a task by id."""
    tasks = _load_bucket_queue()
    for t in tasks:
        if t['id'] == task_id:
            t.update(kwargs)
            break
    _save_bucket_queue(tasks)


# ── Background worker ─────────────────────────────────────────────────────────
async def _bucket_worker():
    """
    Infinite loop that picks the next pending task, executes it,
    waits rest_seconds, then repeats. Respects the pause flag.
    Handles task types:
      - 'search'  : search by name then extract all found profiles
      - 'url'     : extract a specific profile URL
      - 'name'    : search by name string and extract first result
    """
    global _bucket_worker_running, _bucket_worker_paused, scraper
    _bucket_worker_running = True
    print("[TaskBucket] Worker started")
    try:
        while True:
            if _bucket_worker_paused:
                await asyncio.sleep(2)
                continue

            tasks = _load_bucket_queue()
            pending = [t for t in tasks if t['status'] == 'pending']
            if not pending:
                await asyncio.sleep(3)
                continue

            task = pending[0]
            task_id   = task['id']
            query     = task['query']
            task_type = task.get('type', 'name')

            print(f"[TaskBucket] Starting task {task_id} ({task_type}): {query}")
            _update_bucket_task(task_id, status='in_progress', started_at=datetime.now().isoformat())
            _broadcast_sse('bucket_update', {'task_id': task_id, 'status': 'in_progress', 'query': query})

            try:
                # Auto-init scraper if needed
                if not scraper:
                    s = LinkedInScraper(headless=True, browser_type='chromium', session_name='default')
                    await s.initialize()
                    scraper = s

                if not scraper.is_authenticated:
                    raise ValueError("LinkedIn session not authenticated. Please log in via the admin dashboard first.")

                # ── Handle by task type ──────────────────────────────
                if task_type == 'search':
                    # Structured search → extract all found profiles
                    sp = task.get('search_params', {})
                    fn  = sp.get('first_name', query)
                    ln  = sp.get('last_name', '')
                    co  = sp.get('company', '')
                    mx  = int(sp.get('max_results', 5))

                    print(f"[TaskBucket] Searching: '{fn} {ln}' company='{co}' max={mx}")
                    search_results = await scraper.search_people(fn, ln, co, max_results=mx)

                    if not search_results:
                        raise ValueError(f"No profiles found for: {query}")

                    print(f"[TaskBucket] Found {len(search_results)} profiles, extracting…")
                    extracted = []
                    for idx, sr in enumerate(search_results):
                        try:
                            profile = await scraper.extract_profile(sr['profile_url'])
                            if 'error' not in profile:
                                profile['scraped_at'] = datetime.now().isoformat()
                                save_to_persistent_db(profile)
                                extracted.append(profile)
                                _broadcast_sse('new_scrape', {'name': profile.get('name', query), 'count': 1})
                            if idx < len(search_results) - 1:
                                await asyncio.sleep(5)   # small gap between profiles in same task
                        except Exception as pe:
                            print(f"[TaskBucket] Profile extract error: {pe}")

                    # Write to name cache so client status lookup works by name
                    client_name = task.get('_client_name') or query
                    scraped_urls = [p.get('profile_url') for p in extracted if p.get('profile_url')]
                    if scraped_urls:
                        with db_lock:
                            cache_data = {}
                            if NAME_CACHE_FILE.exists():
                                try:
                                    with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as _f:
                                        cache_data = json.load(_f)
                                except Exception:
                                    pass
                            cache_data[client_name] = scraped_urls
                            with open(NAME_CACHE_FILE, 'w', encoding='utf-8') as _f:
                                json.dump(cache_data, _f, indent=2)

                    names = ', '.join(p.get('name', '') for p in extracted[:3])
                    if len(extracted) > 3:
                        names += f' +{len(extracted)-3} more'

                    # Save files for individual download or details retrieval
                    if extracted:
                        # For search tasks, we save the first successful profile under task_id, or aggregate
                        # Let's save the first one or a summary/first profile to make JSON/CSV downloads work
                        with api_scrape_lock:
                            save_scraped_data_formats(extracted[0], task_id)

                    completed_time = datetime.now().isoformat()
                    _update_bucket_task(
                        task_id,
                        status='completed',
                        completed_at=completed_time,
                        result_name=names or query,
                        profiles_found=len(extracted),
                        error=None
                    )
                    
                    # Log to jobs.json for compatibility
                    with api_scrape_lock:
                        jobs_data = {}
                        if JOBS_FILE.exists():
                            with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                                jobs_data = json.load(f)
                        jobs_data[task_id] = {
                            'profile_url': search_results[0]['profile_url'] if search_results else '',
                            'person_name': names or query,
                            'status': 'completed',
                            'requested_at': task.get('added_at', completed_time),
                            'scraped_at': completed_time,
                            'error': None
                        }
                        with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                            json.dump(jobs_data, f, indent=2)

                    print(f"[TaskBucket] Task {task_id} completed: {len(extracted)} profile(s) scraped")
                    _broadcast_sse('bucket_update', {
                        'task_id': task_id, 'status': 'completed',
                        'query': query, 'result_name': names, 'profiles_found': len(extracted)
                    })

                elif task_type == 'url' or query.startswith('http'):
                    # Direct URL scrape
                    profile = await scraper.extract_profile(query)
                    if 'error' in profile:
                        raise ValueError(profile['error'])
                    completed_time = datetime.now().isoformat()
                    profile['scraped_at'] = completed_time
                    save_to_persistent_db(profile)
                    
                    with api_scrape_lock:
                        save_scraped_data_formats(profile, task_id)

                    _broadcast_sse('new_scrape', {'name': profile.get('name', query), 'count': 1})
                    _update_bucket_task(
                        task_id,
                        status='completed',
                        completed_at=completed_time,
                        result_name=profile.get('name', ''),
                        result_url=query,
                        profiles_found=1,
                        error=None
                    )
                    
                    # Log to jobs.json for compatibility
                    with api_scrape_lock:
                        jobs_data = {}
                        if JOBS_FILE.exists():
                            with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                                jobs_data = json.load(f)
                        jobs_data[task_id] = {
                            'profile_url': query,
                            'person_name': profile.get('name', query),
                            'status': 'completed',
                            'requested_at': task.get('added_at', completed_time),
                            'scraped_at': completed_time,
                            'error': None
                        }
                        with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                            json.dump(jobs_data, f, indent=2)

                    print(f"[TaskBucket] Task {task_id} completed: {profile.get('name', query)}")
                    _broadcast_sse('bucket_update', {
                        'task_id': task_id, 'status': 'completed',
                        'query': query, 'result_name': profile.get('name', '')
                    })

                else:
                    # 'name' — search for first match and extract
                    results = await scraper.search_people(query, '', max_results=1, force_search=True)
                    if not results:
                        raise ValueError(f"No profile found for: {query}")
                    profile_url = results[0]['profile_url']
                    profile = await scraper.extract_profile(profile_url)
                    if 'error' in profile:
                        raise ValueError(profile['error'])
                    completed_time = datetime.now().isoformat()
                    profile['scraped_at'] = completed_time
                    save_to_persistent_db(profile)
                    
                    with api_scrape_lock:
                        save_scraped_data_formats(profile, task_id)

                    _broadcast_sse('new_scrape', {'name': profile.get('name', query), 'count': 1})
                    _update_bucket_task(
                        task_id,
                        status='completed',
                        completed_at=completed_time,
                        result_name=profile.get('name', ''),
                        result_url=profile_url,
                        profiles_found=1,
                        error=None
                    )
                    
                    # Log to jobs.json for compatibility
                    with api_scrape_lock:
                        jobs_data = {}
                        if JOBS_FILE.exists():
                            with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                                jobs_data = json.load(f)
                        jobs_data[task_id] = {
                            'profile_url': profile_url,
                            'person_name': profile.get('name', query),
                            'status': 'completed',
                            'requested_at': task.get('added_at', completed_time),
                            'scraped_at': completed_time,
                            'error': None
                        }
                        with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                            json.dump(jobs_data, f, indent=2)

                    print(f"[TaskBucket] Task {task_id} completed: {profile.get('name', query)}")
                    _broadcast_sse('bucket_update', {
                        'task_id': task_id, 'status': 'completed',
                        'query': query, 'result_name': profile.get('name', '')
                    })

            except Exception as exc:
                import traceback as _tb
                _tb.print_exc()
                err = str(exc)
                completed_time = datetime.now().isoformat()
                _update_bucket_task(
                    task_id,
                    status='failed',
                    completed_at=completed_time,
                    error=err
                )
                
                # Log to jobs.json for compatibility
                with api_scrape_lock:
                    jobs_data = {}
                    if JOBS_FILE.exists():
                        with open(JOBS_FILE, 'r', encoding='utf-8') as f:
                            jobs_data = json.load(f)
                    jobs_data[task_id] = {
                        'profile_url': '',
                        'person_name': query,
                        'status': 'failed',
                        'requested_at': task.get('added_at', completed_time),
                        'scraped_at': completed_time,
                        'error': err
                    }
                    with open(JOBS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(jobs_data, f, indent=2)

                print(f"[TaskBucket] Task {task_id} failed: {err}")
                _broadcast_sse('bucket_update', {
                    'task_id': task_id, 'status': 'failed',
                    'query': query, 'error': err
                })


            # Rest period before next task
            cfg  = _load_bucket_config()
            rest = int(cfg.get('rest_seconds', 30))
            if rest > 0:
                print(f"[TaskBucket] Resting {rest}s before next task…")
                _broadcast_sse('bucket_rest', {'seconds': rest})
                elapsed = 0
                while elapsed < rest:
                    await asyncio.sleep(min(2, rest - elapsed))
                    elapsed += 2
                    if _bucket_worker_paused:
                        break

    except asyncio.CancelledError:
        pass
    finally:
        _bucket_worker_running = False
        print("[TaskBucket] Worker stopped")



def _ensure_worker_running():
    """Start the bucket worker coroutine if it isn't already alive."""
    global _bucket_worker_running
    if not _bucket_worker_running:
        asyncio.run_coroutine_threadsafe(_bucket_worker(), _bg_loop)


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.route('/api/bucket/add', methods=['POST'])
def bucket_add():
    """Add one or more tasks to the bucket queue."""
    data = request.json or {}
    raw_queries = data.get('queries', [])
    task_type = data.get('type', 'name')  # 'name' or 'url'

    if not raw_queries:
        # Also accept a single 'query' field
        q = data.get('query', '').strip()
        if q:
            raw_queries = [q]
        else:
            return jsonify({'success': False, 'error': 'queries (list) or query (string) is required'}), 400

    if isinstance(raw_queries, str):
        raw_queries = [raw_queries]

    tasks = _load_bucket_queue()
    added = []
    for raw in raw_queries:
        q = raw.strip()
        if not q:
            continue
        # Auto-detect URL
        detected_type = 'url' if q.startswith('http') else task_type
        task = {
            'id': str(_uuid.uuid4()),
            'query': q,
            'type': detected_type,
            'status': 'pending',
            'added_at': datetime.now().isoformat(),
            'started_at': None,
            'completed_at': None,
            'result_name': '',
            'result_url': '',
            'error': None,
        }
        tasks.append(task)
        added.append(task)

    _save_bucket_queue(tasks)
    _broadcast_sse('bucket_tasks_added', {'count': len(added)})

    # Ensure the worker is running
    _ensure_worker_running()

    return jsonify({'success': True, 'added': len(added), 'tasks': added}), 201


@app.route('/api/bucket/status', methods=['GET'])
def bucket_status():
    """Return the full queue with summary counts."""
    tasks = _load_bucket_queue()
    cfg = _load_bucket_config()
    summary = {'pending': 0, 'in_progress': 0, 'completed': 0, 'failed': 0, 'total': len(tasks)}
    for t in tasks:
        s = t.get('status', 'pending')
        summary[s] = summary.get(s, 0) + 1
    return jsonify({
        'success': True,
        'worker_running': _bucket_worker_running,
        'worker_paused': _bucket_worker_paused,
        'rest_seconds': cfg.get('rest_seconds', 30),
        'summary': summary,
        'tasks': tasks
    })


@app.route('/api/bucket/clear', methods=['POST'])
def bucket_clear():
    """Remove completed and failed tasks from the queue."""
    data = request.json or {}
    clear_all = data.get('all', False)
    tasks = _load_bucket_queue()
    if clear_all:
        kept = []
    else:
        kept = [t for t in tasks if t['status'] not in ('completed', 'failed')]
    _save_bucket_queue(kept)
    removed = len(tasks) - len(kept)
    _broadcast_sse('bucket_cleared', {'removed': removed})
    return jsonify({'success': True, 'removed': removed, 'remaining': len(kept)})


@app.route('/api/bucket/pause', methods=['POST'])
def bucket_pause():
    """Pause the worker (it will finish the current task then stop)."""
    global _bucket_worker_paused
    _bucket_worker_paused = True
    _broadcast_sse('bucket_paused', {})
    return jsonify({'success': True, 'paused': True})


@app.route('/api/bucket/resume', methods=['POST'])
def bucket_resume():
    """Resume the worker."""
    global _bucket_worker_paused
    _bucket_worker_paused = False
    _ensure_worker_running()
    _broadcast_sse('bucket_resumed', {})
    return jsonify({'success': True, 'paused': False})


@app.route('/api/bucket/config', methods=['POST'])
def bucket_config():
    """Update bucket configuration (rest_seconds)."""
    data = request.json or {}
    cfg = _load_bucket_config()
    if 'rest_seconds' in data:
        try:
            cfg['rest_seconds'] = max(0, int(data['rest_seconds']))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'rest_seconds must be an integer >= 0'}), 400
    _save_bucket_config(cfg)
    return jsonify({'success': True, 'config': cfg})


@app.route('/api/bucket/add-search', methods=['POST'])
def bucket_add_search():
    """Add a structured name-based search task to the bucket."""
    data = request.json or {}
    first_name  = data.get('first_name', '').strip()
    last_name   = data.get('last_name', '').strip()
    company     = data.get('company', '').strip()
    max_results = max(1, int(data.get('max_results', 5)))

    if not first_name and not last_name:
        return jsonify({'success': False, 'error': 'first_name or last_name is required'}), 400

    label = ' '.join(filter(None, [first_name, last_name]))
    if company:
        label += f' @ {company}'

    task = {
        'id': str(_uuid.uuid4()),
        'query': label,
        'type': 'search',
        'search_params': {
            'first_name': first_name,
            'last_name':  last_name,
            'company':    company,
            'max_results': max_results,
        },
        'status': 'pending',
        'added_at': datetime.now().isoformat(),
        'started_at': None,
        'completed_at': None,
        'result_name': '',
        'result_url': '',
        'profiles_found': 0,
        'error': None,
    }

    tasks = _load_bucket_queue()
    tasks.append(task)
    _save_bucket_queue(tasks)
    _broadcast_sse('bucket_tasks_added', {'count': 1, 'query': label})
    _ensure_worker_running()

    return jsonify({'success': True, 'task': task}), 201


@app.route('/api/bucket/remove', methods=['POST'])
def bucket_remove():
    """Remove a pending task by id."""
    data = request.json or {}
    task_id = data.get('task_id', '').strip()
    if not task_id:
        return jsonify({'success': False, 'error': 'task_id is required'}), 400
    tasks = _load_bucket_queue()
    original = len(tasks)
    tasks = [t for t in tasks if not (t['id'] == task_id and t['status'] == 'pending')]
    if len(tasks) == original:
        return jsonify({'success': False, 'error': 'Task not found or not in pending state'}), 404
    _save_bucket_queue(tasks)
    _broadcast_sse('bucket_update', {'task_id': task_id, 'status': 'removed'})
    return jsonify({'success': True})


# Auto-start the bucket worker when the server launches so any
# tasks left in the queue from previous runs continue processing.
_ensure_worker_running()


# Run the Flask app
if __name__ == '__main__':
    print("Persona - LinkedIn Profile Scraper and Ranker")
    print("http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
