#Required Imports
from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_cors import CORS
import asyncio
import threading
import os
import io
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
import uuid as _uuid

# Force stdout/stderr to be unbuffered so logs print in real-time on Windows
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


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
from core import (
    LinkedInScraper, sanitize_profile, clean_profile,
    _LINKEDIN_FOOTER_TOKENS, _REAL_LANGUAGE_NAMES,
    _is_junk_text, _is_junk_entry, _is_real_language,
    _clean_about, _clean_experience_list, _clean_education_list,
    _clean_certification_list, _clean_languages_list, _clean_honors_list,
    _clean_recommendations_list, _clean_skills_list, _clean_volunteer_list
)

#Enable below things when you are ready to rank the people
# from ranker import rank_sri_lankan_profiles, get_score_tier 


# Flask App Initialization
app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

scraper = None

# Background event loop for Playwright operations (Chronium processes)
_bg_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
threading.Thread(target=_bg_loop.run_forever, daemon=True, name="playwright-loop").start()

_scrape_lock = None

def _get_scrape_lock():
    global _scrape_lock
    if _scrape_lock is None:
        _scrape_lock = asyncio.Lock()
    return _scrape_lock

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
        # 1. Gracefully close existing scraper if any
        if scraper:
            try:
                run_async(scraper.close())
            except Exception:
                pass
            scraper = None

        # 2. Kill any orphan Playwright Chromium processes that are still holding
        #    LOCK files on the browser_data directory.
        _kill_playwright_chromium()

        data = request.json or {}

        async def init():
            global scraper
            scraper = LinkedInScraper(
                headless=data.get('headless', False),
                browser_type=data.get('browser_type', 'chromium'),
                session_name=data.get('session_name', 'default')
            )
            await scraper.initialize()
            return {'success': True, 'message': 'Browser initialized successfully'}

        result = run_async(init())
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        scraper = None
        return jsonify({'success': False, 'error': str(e)}), 500


def _kill_playwright_chromium():
    """
    Kill any Playwright-launched Chromium child processes that are still
    alive after a previous session was not cleanly closed.
    Only targets processes whose command line includes the browser_data path.
    """
    import subprocess
    try:
        # Use tasklist + wmic to find Chromium children tied to our profile dir
        browser_data_marker = 'browser_data'
        result = subprocess.run(
            ['wmic', 'process', 'where',
             f"name='chrome.exe' and CommandLine like '%{browser_data_marker}%'",
             'get', 'ProcessId,CommandLine', '/FORMAT:CSV'],
            capture_output=True, text=True, timeout=10
        )
        killed = 0
        for line in result.stdout.splitlines():
            parts = line.strip().split(',')
            if len(parts) >= 2:
                try:
                    pid = int(parts[-1].strip())
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                                   capture_output=True, timeout=5)
                    killed += 1
                    print(f"Killed stale Chromium PID {pid}")
                except Exception:
                    pass
        if killed:
            import time
            time.sleep(1)  # brief pause after kill
    except Exception as ex:
        print(f"_kill_playwright_chromium: {ex} (non-fatal, continuing)")


@app.route('/api/scraper/kill-browser', methods=['POST'])
def kill_browser():
    """Emergency endpoint: forcefully close browser and kill any stale processes."""
    global scraper
    try:
        if scraper:
            try:
                run_async(scraper.close())
            except Exception:
                pass
            scraper = None
        _kill_playwright_chromium()
        return jsonify({'success': True, 'message': 'Browser processes terminated'})
    except Exception as e:
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

@app.route('/api/scraper/search-contact-info', methods=['POST'])
def search_contact_info():
    global scraper
    if not scraper or not scraper.is_authenticated:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    try:
        data = request.json
        email = data.get('email', '').strip()
        phone = data.get('phone', '').strip()
        if not email and not phone:
            return jsonify({'success': False, 'error': 'Email or phone required'}), 400
            
        async def do_search():
            is_premium = await scraper.is_premium_account()
            if not is_premium:
                return {'success': False, 'error': 'PREMIUM_REQUIRED', 'message': 'System cannot search for contact info because a premium account is required to search contact info.'}
            results = await scraper.search_by_contact_info(email, phone)
            return {'success': True, 'results': results, 'total': len(results)}
            
        res = run_async(do_search())
        if not res.get('success'):
            return jsonify(res), 403 if res.get('error') == 'PREMIUM_REQUIRED' else 400
        return jsonify(res)
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
            async with _get_scrape_lock():
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

'''@app.route('/api/rank', methods=['POST'])
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
'''

# -----------------------------------------------------------------------
# Profile Data Cleaning Utilities
# -----------------------------------------------------------------------

def _clean_value(v):
    """Return None if a value is null-like, otherwise return it as-is."""
    if v is None:
        return None
    if isinstance(v, str):
        stripped = v.strip()
        if stripped.lower() in ('none', 'null', 'n/a', 'na', ''):
            return None
        return stripped
    return v

def _clean_list(lst):
    """Remove null/empty items from a list; recursively clean dicts within it."""
    if not lst or not isinstance(lst, list):
        return []
    result = []
    for item in lst:
        if isinstance(item, dict):
            cleaned = clean_profile_dict(item)
            if cleaned:
                result.append(cleaned)
        elif item is not None:
            v = _clean_value(item)
            if v is not None:
                result.append(v)
    return result

def clean_profile_dict(d):
    """Recursively remove null/empty keys from a dict."""
    if not d or not isinstance(d, dict):
        return {}
    cleaned = {}
    for k, v in d.items():
        if isinstance(v, dict):
            c = clean_profile_dict(v)
            if c:
                cleaned[k] = c
        elif isinstance(v, list):
            c = _clean_list(v)
            if c:
                cleaned[k] = c
        else:
            c = _clean_value(v)
            if c is not None:
                cleaned[k] = c
    return cleaned

# -----------------------------------------------------------------------
# LinkedIn Scrape Junk Filter
# LinkedIn pages include footer nav / language selector content that gets
# mixed into every scraped section.  These constants identify that garbage.
# -----------------------------------------------------------------------

_LINKEDIN_FOOTER_TOKENS = {
    'accessibility', 'talent solutions', 'community guidelines', 'careers',
    'marketing solutions', 'privacy & terms', 'ad choices', 'advertising',
    'sales solutions', 'mobile', 'small business', 'safety center',
    'linkedin corporation', 'questions?', 'manage your account and privacy',
    'go to your settings.', 'recommendation transparency',
    'learn more about recommended content.', 'select language',
    'visit our help center.', 'about',
    # LinkedIn language names that appear in "select language" dropdown
    'العربية (arabic)', 'বাংলা (bangla)', 'čeština (czech)', 'dansk (danish)',
    'deutsch (german)', 'ελληνικά (greek)', 'english (english)',
    'español (spanish)', 'فارسی (persian)', 'suomi (finnish)',
    'français (french)', 'हिंदी (hindi)', 'magyar (hungarian)',
    'bahasa indonesia (indonesian)', 'italiano (italian)', 'עברית (hebrew)',
    '日本語 (japanese)', '한국어 (korean)', 'मराठी (marathi)',
    'bahasa malaysia (malay)', 'nederlands (dutch)', 'norsk (norwegian)',
    'ਪੰਜਾਬੀ (punjabi)', 'polski (polish)', 'português (portuguese)',
    'română (romanian)', 'русский (russian)', 'svenska (swedish)',
    'తెలుగు (telugu)', 'ภาษาไทย (thai)', 'tagalog (tagalog)',
    'türkçe (turkish)', 'українська (ukrainian)', 'tiếng việt (vietnamese)',
    '简体中文 (chinese (simplified))', '正體中文 (chinese (traditional))',
    # Common garbage strings scraped from skills/project associations
    'show credential', 'badge',
}

# Known real language names (to allow in the languages section)
_REAL_LANGUAGE_NAMES = {
    'english', 'sinhalese', 'sinhala', 'tamil', 'french', 'german',
    'spanish', 'portuguese', 'italian', 'dutch', 'russian', 'chinese',
    'japanese', 'korean', 'arabic', 'hindi', 'urdu', 'bengali',
    'malay', 'indonesian', 'turkish', 'polish', 'swedish', 'norwegian',
    'danish', 'finnish', 'greek', 'hebrew', 'thai', 'vietnamese',
    'tagalog', 'punjabi', 'marathi', 'telugu', 'ukrainian', 'romanian',
    'czech', 'hungarian', 'persian', 'farsi',
}

def _is_junk_text(text):
    """Return True if the string is recognised LinkedIn footer/UI garbage."""
    if not text:
        return False
    t = text.strip().lower()
    if t in _LINKEDIN_FOOTER_TOKENS:
        return True
    if t.startswith('linkedin corporation'):
        return True
    if 'select language' in t:
        return True
    return False

def _is_junk_entry(entry):
    """Return True if a dict entry looks like scraped UI garbage, not real content."""
    if not isinstance(entry, dict):
        return False
    values = [str(v).strip() for v in entry.values() if v]
    if values and all(_is_junk_text(v) for v in values):
        return True
    for key in ('duration', 'date', 'dates'):
        v = entry.get(key, '')
        if v and _is_junk_text(str(v)):
            return True
    return False

def _is_real_language(lang_name):
    """True only if the name looks like a real human language, not a nav item."""
    if not lang_name:
        return False
    t = lang_name.strip().lower()
    if t in _REAL_LANGUAGE_NAMES:
        return True
    if _is_junk_text(t):
        return False
    junk_indicators = [
        'solutions', 'guidelines', 'corporation', 'accessibility',
        'advertising', 'privacy', 'terms', 'choices', 'credential',
        'settings', 'transparency', 'center', 'questions', 'careers',
    ]
    for ind in junk_indicators:
        if ind in t:
            return False
    return False

def _clean_about(about_text):
    """Strip the LinkedIn footer/language-selector content and 'more...' artifacts from the About field."""
    if not about_text:
        return ''
    cutoff_markers = [
        'Accessibility\nTalent Solutions',
        '\nAccessibility\n',
        'Talent Solutions\nCommunity Guidelines',
        'Select language\n',
        'LinkedIn Corporation',
    ]
    text = about_text
    for marker in cutoff_markers:
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx].strip()

    # Remove "...more" or "… more" or "more..." suffix/artifacts
    for junk in ['… more', '...more', '... more', '…more', 'more...', '... see more', 'see more', '…']:
        if text.endswith(junk):
            text = text[:-len(junk)].strip()

    lines = text.split('\n')
    clean_lines = []
    for ln in lines:
        s = ln.strip()
        if not s or _is_junk_text(s):
            continue
        s = s.replace('… more', '').replace('...more', '').replace('more...', '').replace('…', '')
        if s.lower() in ('about', 'see more', 'show more'):
            continue
        clean_lines.append(s)
    return '\n'.join(clean_lines).strip()

def _clean_experience_list(exp_list):
    """Remove junk entries from experience; keep only real jobs."""
    if not exp_list:
        return []
    result = []
    seen = set()
    for e in exp_list:
        if not isinstance(e, dict):
            continue
        if _is_junk_entry(e):
            continue
        title   = (e.get('title') or '').strip()
        company = (e.get('company') or '').strip()
        if _is_junk_text(title) or _is_junk_text(company):
            continue
        if not title and not company:
            continue
        key = (title.lower(), company.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(e)
    return result

def _clean_education_list(edu_list):
    """Remove junk entries from education/qualifications."""
    if not edu_list:
        return []
    result = []
    seen = set()
    for e in edu_list:
        if not isinstance(e, dict):
            continue
        if _is_junk_entry(e):
            continue
        inst   = (e.get('institution') or '').strip()
        degree = (e.get('degree') or '').strip()
        if _is_junk_text(inst) or _is_junk_text(degree):
            continue
        if not inst and not degree:
            continue
        if inst.lower().startswith('skills:') or degree.lower().startswith('skills:'):
            continue
        key = (inst.lower(), degree.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(e)
    return result

def _clean_certification_list(cert_list):
    """Remove junk entries from certifications."""
    if not cert_list:
        return []
    result = []
    seen = set()
    for c in cert_list:
        if not isinstance(c, dict):
            continue
        if _is_junk_entry(c):
            continue
        name   = (c.get('name') or '').strip()
        issuer = (c.get('issuer') or '').strip()
        if _is_junk_text(name) or _is_junk_text(issuer):
            continue
        if name.lower() in ('show credential', 'badge', ''):
            continue
        if issuer.lower().startswith('skills:'):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(c)
    return result

def _clean_languages_list(lang_list):
    """Keep only real human languages, discard footer-nav garbage."""
    if not lang_list:
        return []
    result = []
    seen = set()
    for l in lang_list:
        if not isinstance(l, dict):
            continue
        lang_name = (l.get('language') or '').strip()
        if not lang_name:
            continue
        if not _is_real_language(lang_name):
            continue
        key = lang_name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(l)
    return result

def _clean_honors_list(hon_list):
    """Remove junk entries from honors/awards."""
    if not hon_list:
        return []
    result = []
    seen = set()
    for h in hon_list:
        if not isinstance(h, dict):
            continue
        if _is_junk_entry(h):
            continue
        title  = (h.get('title') or '').strip()
        issuer = (h.get('issuer') or '').strip()
        if _is_junk_text(title) or _is_junk_text(issuer):
            continue
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(h)
    return result

def _clean_recommendations_list(rec_list):
    """Remove junk entries from recommendations."""
    if not rec_list:
        return []
    result = []
    for r in rec_list:
        if not isinstance(r, dict):
            continue
        if _is_junk_entry(r):
            continue
        recommender = (r.get('recommender') or '').strip()
        text_val    = (r.get('text') or '').strip()
        title       = (r.get('title') or '').strip()
        if _is_junk_text(recommender) or _is_junk_text(title):
            continue
        if "haven't received" in recommender.lower() or 'try asking' in title.lower():
            continue
        if not recommender and not text_val:
            continue
        result.append(r)
    return result

def _clean_skills_list(skills_list):
    """Deduplicate and remove junk from skills list."""
    if not skills_list:
        return []
    seen = set()
    result = []
    for s in skills_list:
        if isinstance(s, dict):
            name = (s.get('skill') or s.get('name') or '').strip()
        elif isinstance(s, str):
            name = s.strip()
        else:
            continue
        if not name:
            continue
        if _is_junk_text(name):
            continue
        # Filter out long project/job titles that sneaked into skills
        if len(name) > 80:
            continue
        if ' at ' in name.lower() and 'intern' in name.lower():
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({'skill': name})
    return result

def _clean_volunteer_list(vol_list):
    """Remove junk entries from volunteer experience (e.g. LinkedIn footer links & language pickers)."""
    if not vol_list:
        return []
    result = []
    seen = set()
    junk_indicators = [
        'questions?', 'manage your account', 'recommendation transparency',
        'help center', 'settings', 'recommended content', 'select language',
        'mobile', 'visit our help center.'
    ]
    for v in vol_list:
        if not isinstance(v, dict):
            continue
        if _is_junk_entry(v):
            continue
        role = (v.get('role') or '').strip()
        org  = (v.get('organization') or v.get('company') or '').strip()
        if _is_junk_text(role) or _is_junk_text(org):
            continue
        if not role and not org:
            continue
        r_low = role.lower()
        o_low = org.lower()
        if any(ind in r_low or ind in o_low for ind in junk_indicators):
            continue
        if ('(' in o_low and ')' in o_low) or ('(' in r_low and ')' in r_low):
            continue
        if _is_real_language(org) or _is_real_language(role):
            continue
        key = (role.lower(), org.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(v)
    return result

def sanitize_profile(profile):
    """
    Deep-clean a raw scraped profile:
    - Strips LinkedIn footer/nav junk from every section
    - Removes null/empty values
    - Deduplicates skills
    - Cleans the About text
    Returns a new dict with only real data.
    """
    if not profile or not isinstance(profile, dict):
        return {}

    p = dict(profile)

    # Clean About field
    p['about'] = _clean_about(p.get('about', '') or '')

    # Clean list sections
    p['experience']      = _clean_experience_list(p.get('experience') or p.get('experiences') or [])
    p['experiences']     = p['experience']
    p['qualifications']  = _clean_education_list(p.get('qualifications') or p.get('education') or [])
    p['education']       = p['qualifications']
    p['certifications']  = _clean_certification_list(p.get('certifications') or [])
    p['languages']       = _clean_languages_list(p.get('languages') or [])
    p['honors']          = _clean_honors_list(p.get('honors') or [])
    p['recommendations'] = _clean_recommendations_list(p.get('recommendations') or [])
    p['skills']          = _clean_skills_list(p.get('skills') or [])
    p['volunteer']       = _clean_volunteer_list(p.get('volunteer') or [])
    p['contact_info']    = p.get('contact_info') or {}

    # Clean current_job
    cj = p.get('current_job')
    if cj and isinstance(cj, dict):
        if _is_junk_entry(cj):
            p['current_job'] = {}

    # Remove empty string / null top-level fields
    for field in ('name', 'headline', 'location', 'profile_url', 'profile_picture',
                  'connections', 'scraped_at'):
        v = p.get(field)
        if v is not None and isinstance(v, str):
            cleaned = v.strip()
            if cleaned.lower() in ('none', 'null', 'n/a', 'na', ''):
                p[field] = ''
            else:
                p[field] = cleaned

    # Remove empty lists/dicts to keep JSON output clean
    for k in list(p.keys()):
        v = p[k]
        if v == [] or v == {} or v == '':
            if k not in ('name',):
                del p[k]

    return p

# Keep backward-compatible alias
def clean_profile(profile):
    return sanitize_profile(profile)

# -----------------------------------------------------------------------
# CSV format helpers — convert nested data to human-readable strings
# -----------------------------------------------------------------------

def _format_experience_for_csv(exp_list):
    """Turn experience list into a human-readable semicolon-separated string."""
    if not exp_list:
        return ''
    parts = []
    for e in exp_list:
        if not isinstance(e, dict):
            continue
        title   = (e.get('title') or '').strip()
        company = (e.get('company') or '').strip()
        dur     = (e.get('duration') or '').strip()
        pieces  = []
        if title:   pieces.append(title)
        if company: pieces.append(f'at {company}')
        if dur:     pieces.append(f'({dur})')
        if pieces:
            parts.append(' '.join(pieces))
    return '; '.join(parts)

def _format_education_for_csv(edu_list):
    """Turn education/qualifications list into a readable string."""
    if not edu_list:
        return ''
    parts = []
    for e in edu_list:
        if not isinstance(e, dict):
            continue
        inst   = (e.get('institution') or '').strip()
        degree = (e.get('degree') or '').strip()
        dates  = (e.get('dates') or '').strip()
        pieces = []
        if inst:   pieces.append(inst)
        if degree: pieces.append(degree)
        if dates:  pieces.append(f'({dates})')
        if pieces:
            parts.append(' | '.join(pieces))
    return '; '.join(parts)

def _format_certifications_for_csv(cert_list):
    """Turn certifications list into a readable string."""
    if not cert_list:
        return ''
    parts = []
    for c in cert_list:
        if not isinstance(c, dict):
            continue
        name   = (c.get('name') or '').strip()
        issuer = (c.get('issuer') or '').strip()
        date   = (c.get('date') or '').strip()
        pieces = []
        if name:   pieces.append(name)
        if issuer: pieces.append(f'by {issuer}')
        if date:   pieces.append(f'({date})')
        if pieces:
            parts.append(' '.join(pieces))
    return '; '.join(parts)

def _format_skills_for_csv(skills_list):
    """Turn skills list into a comma-separated readable string."""
    if not skills_list:
        return ''
    parts = []
    for s in skills_list:
        if isinstance(s, dict):
            name = (s.get('skill') or s.get('name') or '').strip()
            if name:
                parts.append(name)
        elif isinstance(s, str):
            s = s.strip()
            if s:
                parts.append(s)
    return ', '.join(parts)

def _format_current_job_for_csv(job):
    """Turn current_job dict into a readable Title at Company string."""
    if not job or not isinstance(job, dict):
        return ''
    title   = (job.get('title') or '').strip()
    company = (job.get('company') or '').strip()
    if title and company:
        return f'{title} at {company}'
    return title or company

# -------------------------------------------------------------------------

#Data Export Endpoint (Supports JSON and CSV)
@app.route('/api/scraper/export', methods=['POST'])
def export_data():
    try:
        data = request.json or {}
        export_payload = data.get('data', {})
        format_type = data.get('format', 'json')
        if not export_payload:
            return jsonify({'success': False, 'error': 'No data'}), 400

        if isinstance(export_payload, list):
            profiles = export_payload
        elif isinstance(export_payload, dict) and 'profiles' in export_payload:
            profiles = export_payload.get('profiles') or []
        elif isinstance(export_payload, dict):
            profiles = [export_payload]
        else:
            profiles = []

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path("exports").mkdir(exist_ok=True)
        if format_type == 'json':
            filename = f"linkedin_export_{timestamp}.json"
            filepath = Path("exports") / filename
            # Clean profiles before saving — remove nulls and junk symbols
            cleaned_payload = {'profiles': [clean_profile(p) for p in profiles]}
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(cleaned_payload, f, indent=2, ensure_ascii=False)
            return send_file(filepath, as_attachment=True, download_name=filename)
        elif format_type == 'csv':
            from flask import make_response
            filename = f"linkedin_export_{timestamp}.csv"
            output = io.StringIO()
            writer = csv.writer(output)
            if not profiles:
                return jsonify({'success': False, 'error': 'No profiles in data'}), 400
            # Human-readable column headers
            writer.writerow([
                'Name', 'Headline', 'Location',
                'Current Position',
                'Experience', 'Education / Qualifications',
                'Skills', 'Certifications',
                'About', 'Profile URL', 'Scraped At'
            ])
            for p in profiles:
                cp = clean_profile(p)
                writer.writerow([
                    cp.get('name', ''),
                    cp.get('headline', ''),
                    cp.get('location', ''),
                    _format_current_job_for_csv(cp.get('current_job')),
                    _format_experience_for_csv(cp.get('experiences') or cp.get('experience')),
                    _format_education_for_csv(cp.get('qualifications') or cp.get('education')),
                    _format_skills_for_csv(cp.get('skills')),
                    _format_certifications_for_csv(cp.get('certifications')),
                    (cp.get('about') or '')[:2000],
                    cp.get('profile_url', ''),
                    cp.get('scraped_at', '')
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
        
    cleaned_p = clean_profile(profile)
    with db_lock:
        try:
            # Ensure parent directories exist
            ALL_PROFILES_JSON.parent.mkdir(parents=True, exist_ok=True)
            # 1. Update master JSON database
            profiles = []
            if ALL_PROFILES_JSON.exists():
                try:
                    with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                        profiles = [clean_profile(p) for p in json.load(f)]
                except Exception:
                    profiles = []
                    
            # Avoid duplicate profile URLs in the master database (update if exists, otherwise append)
            url = cleaned_p.get('profile_url')
            updated = False
            for i, p in enumerate(profiles):
                if p.get('profile_url') == url:
                    profiles[i] = cleaned_p
                    updated = True
                    break
            if not updated:
                profiles.append(cleaned_p)
                
            with open(ALL_PROFILES_JSON, 'w', encoding='utf-8') as f:
                json.dump(profiles, f, indent=2, ensure_ascii=False)
                
            # 2. Rewrite master CSV database (human-readable columns)
            headers = [
                'Name', 'Headline', 'Location',
                'Current Position',
                'Experience', 'Education / Qualifications',
                'Skills', 'Certifications',
                'About', 'Profile URL', 'Scraped At'
            ]
            
            with open(ALL_PROFILES_CSV, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for p in profiles:
                    cp = clean_profile(p)
                    writer.writerow([
                        cp.get('name', ''),
                        cp.get('headline', ''),
                        cp.get('location', ''),
                        _format_current_job_for_csv(cp.get('current_job')),
                        _format_experience_for_csv(cp.get('experiences') or cp.get('experience')),
                        _format_education_for_csv(cp.get('qualifications') or cp.get('education')),
                        _format_skills_for_csv(cp.get('skills')),
                        _format_certifications_for_csv(cp.get('certifications')),
                        (cp.get('about') or '')[:2000],
                        cp.get('profile_url', ''),
                        cp.get('scraped_at', '')
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

def save_scraped_data_formats(data_input, return_code):
    # Support single profile dict or list of profile dicts
    if isinstance(data_input, list):
        profiles = [clean_profile(p) for p in data_input if p and 'error' not in p]
    elif isinstance(data_input, dict) and 'profiles' in data_input:
        profiles = [clean_profile(p) for p in data_input['profiles'] if p and 'error' not in p]
    elif isinstance(data_input, dict):
        profiles = [clean_profile(data_input)]
    else:
        profiles = []

    if not profiles:
        return

    # Save cleaned JSON file (remove null values and junk symbols)
    json_path = API_SCRAPES_DIR / f"{return_code}.json"
    if len(profiles) > 1:
        json_data = {'profiles': profiles}
    else:
        json_data = profiles[0]

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
        
    # Save CSV file with human-readable expanded columns
    csv_path = API_SCRAPES_DIR / f"{return_code}.csv"
    headers = [
        'Name', 'Headline', 'Location',
        'Current Position',
        'Experience', 'Education / Qualifications',
        'Skills', 'Certifications',
        'About', 'Profile URL', 'Scraped At', 'Return Code'
    ]
    
    rows_data = []
    for cp in profiles:
        rows_data.append([
            cp.get('name', ''),
            cp.get('headline', ''),
            cp.get('location', ''),
            _format_current_job_for_csv(cp.get('current_job')),
            _format_experience_for_csv(cp.get('experiences') or cp.get('experience')),
            _format_education_for_csv(cp.get('qualifications') or cp.get('education')),
            _format_skills_for_csv(cp.get('skills')),
            _format_certifications_for_csv(cp.get('certifications')),
            (cp.get('about') or '')[:2000],
            cp.get('profile_url', ''),
            cp.get('scraped_at', ''),
            return_code
        ])
    
    # Save individual CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows_data:
            writer.writerow(row)
        
    # Append to master CSV file
    master_exists = MASTER_CSV_FILE.exists()
    with open(MASTER_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not master_exists:
            writer.writerow(headers)
        for row in rows_data:
            writer.writerow(row)

async def perform_background_scrape(profile_url, return_code):
    global scraper
    async with _get_scrape_lock():
        try:
            if not scraper:
                print("Auto-initializing scraper for background API request...")
                _kill_playwright_chromium()
                scraper = LinkedInScraper(headless=False, browser_type='chromium', session_name='default')
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
    async with _get_scrape_lock():
        try:
            if not scraper:
                print("Auto-initializing scraper for background name-based request...")
                _kill_playwright_chromium()
                scraper = LinkedInScraper(headless=False, browser_type='chromium', session_name='default')
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

@app.route('/api/client/scrape', methods=['GET', 'POST'])
def client_scrape():
    """
    Client search endpoint — routes ALL scrape requests through the Task Bucket.
    Supports POST (JSON/Form-data) and GET (query params).
    Returns the bucket task_id as the reference number immediately.
    The client polls /api/client/scrape-status?task_id=... to watch progress.
    """
    if request.method == 'GET':
        data = request.args.to_dict()
    else:
        data = request.get_json(silent=True) or request.form.to_dict() or request.args.to_dict()

    # If opened directly in browser via GET with no search parameters, return informative status & usage guide
    if request.method == 'GET' and not any(k in data for k in ('name', 'query', 'url', 'profile_url', 'first_name', 'username', 'candidate_name')):
        return jsonify({
            'success': True,
            'message': 'Persona V3 Scrape API is online and operational.',
            'endpoints': {
                'scrape': 'POST /api/client/scrape (or GET with ?name=...)',
                'scrape_status': 'GET /api/client/scrape-status?task_id={reference_number}',
                'retrieve_profile': 'GET/POST /api/client/retrieve?return_code={reference_number}',
                'client_portal_ui': '/'
            },
            'example_usage': {
                'curl_post': 'curl -X POST https://decorated-program-starfish.ngrok-free.dev/api/client/scrape -H "Content-Type: application/json" -d \'{"name": "Bawantha Beliwaththa", "company": "TechCorp"}\'',
                'browser_get': 'https://decorated-program-starfish.ngrok-free.dev/api/client/scrape?name=Bawantha+Beliwaththa'
            }
        }), 200

    url = (data.get('url') or data.get('profile_url') or '').strip()
    name = (data.get('name') or data.get('query') or data.get('candidate_name') or '').strip()
    first_name = (data.get('first_name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    company = (data.get('company') or '').strip()
    max_results = int(data.get('max_results') or 5)

    if not name and (first_name or last_name):
        name = f"{first_name} {last_name}".strip()
    elif not name and url:
        name = url

    if not name:
        return jsonify({'success': False, 'error': "'name', 'query', or 'profile_url' is required"}), 400

    name_lower = name.lower()

    # --- Check cache first (instant return if already scraped, case-insensitive) ---
    with db_lock:
        cache_data = {}
        if NAME_CACHE_FILE.exists():
            try:
                with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            except Exception:
                pass

    matched_key = next((k for k in cache_data.keys() if k.lower() == name_lower), None)
    if matched_key:
        cached_urls = cache_data[matched_key]
        all_profiles = []
        if ALL_PROFILES_JSON.exists():
            try:
                with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                    all_profiles = json.load(f)
            except Exception:
                pass
        results = [clean_profile(p) for p in all_profiles if p.get('profile_url') in cached_urls]
        if results:
            return jsonify({
                'success': True, 'cached': True,
                'profiles': results, 'total': len(results),
                'reference_number': 'cached_' + matched_key
            }), 200

    # --- Check if this name is already in the bucket (pending or in_progress, case-insensitive) ---
    existing_tasks = _load_bucket_queue()
    for t in existing_tasks:
        if (t.get('query') or '').lower() == name_lower and t['status'] in ('pending', 'in_progress'):
            return jsonify({
                'success': True, 'status': t['status'],
                'reference_number': t['id'],
                'message': 'Already queued. Check back soon.'
            }), 202

    # --- Add to Task Bucket ---
    is_direct_url = name.startswith('http') or 'linkedin.com/in/' in name
    task = {
        'id': str(_uuid.uuid4()),
        'query': name,
        'type': 'url' if is_direct_url else 'search',
        'search_params': {
            'first_name': first_name or name,
            'last_name': last_name,
            'company': company,
            'max_results': max_results,
        },
        'status': 'pending',
        'added_at': datetime.now().isoformat(),
        'started_at': None,
        'completed_at': None,
        'result_name': '',
        'result_url': name if is_direct_url else '',
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
    Returns profiles from the master DB when the task is complete. (100% Case-Insensitive)
    """
    task_id = request.args.get('task_id', '').strip()
    name    = request.args.get('name', '').strip()

    if not task_id and not name:
        return jsonify({'success': False, 'error': 'task_id or name is required'}), 400

    task_id_lower = task_id.lower()
    name_lower    = name.lower()

    tasks = _load_bucket_queue()

    # Case-insensitive search by task_id first, then by name
    task = None
    if task_id:
        task = next((t for t in tasks if t['id'].lower() == task_id_lower), None)
    if not task and name:
        task = next((t for t in tasks if (t.get('_client_name') or t.get('query') or '').lower() == name_lower), None)

    if not task:
        # Maybe it already completed and was cleared from queue — check master DB
        all_profiles = []
        if ALL_PROFILES_JSON.exists():
            try:
                with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                    all_profiles = json.load(f)
            except Exception:
                pass
        # Check name cache case-insensitively
        with db_lock:
            cache_data = {}
            if NAME_CACHE_FILE.exists():
                try:
                    with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                except Exception:
                    pass

        matched_key = next((k for k in cache_data.keys() if k.lower() == name_lower), None) if name_lower else None
        if matched_key:
            cached_urls = cache_data[matched_key]
            results = [clean_profile(p) for p in all_profiles if p.get('profile_url') in cached_urls]
            if results:
                return jsonify({'success': True, 'status': 'completed', 'profiles': results, 'total': len(results)}), 200
        return jsonify({'success': False, 'error': 'Task not found'}), 404

    status = task['status']

    if status in ('pending', 'in_progress'):
        pending_or_active = [t for t in tasks if t['status'] in ('pending', 'in_progress')]
        queue_total = len(pending_or_active)
        queue_position = 0
        for i, t in enumerate(pending_or_active):
            if t['id'].lower() == task.get('id', '').lower():
                queue_position = i + 1
                break
        return jsonify({
            'success': True,
            'status': status,
            'queue_position': queue_position,
            'queue_total': queue_total,
            'message': 'Queued in Task Bucket — the worker will process it automatically.' if status == 'pending'
                       else 'Currently scraping LinkedIn profiles…'
        }), 202

    if status == 'failed':
        return jsonify({
            'success': False,
            'status': 'failed',
            'error': task.get('error', 'Unknown error')
        }), 200

    # Completed — load profiles from task JSON or master DB
    if status == 'completed':
        task_id = task.get('id')
        if task_id:
            json_path = API_SCRAPES_DIR / f"{task_id}.json"
            if json_path.exists():
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        raw = json.load(f)
                    if isinstance(raw, dict) and 'profiles' in raw:
                        t_profiles = raw['profiles']
                    elif isinstance(raw, list):
                        t_profiles = raw
                    elif isinstance(raw, dict):
                        t_profiles = [raw]
                    else:
                        t_profiles = []
                    if t_profiles:
                        return jsonify({'success': True, 'status': 'completed', 'profiles': t_profiles, 'total': len(t_profiles)}), 200
                except Exception:
                    pass

        search_name = task.get('_client_name') or task.get('query', name)
        all_profiles = []
        if ALL_PROFILES_JSON.exists():
            try:
                with open(ALL_PROFILES_JSON, 'r', encoding='utf-8') as f:
                    all_profiles = json.load(f)
            except Exception:
                pass

        with db_lock:
            cache_data = {}
            if NAME_CACHE_FILE.exists():
                try:
                    with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                except Exception:
                    pass

        search_lower = search_name.lower()
        matched_key = next((k for k in cache_data.keys() if k.lower() == search_lower), None)
        if matched_key:
            cached_urls = cache_data[matched_key]
            results = [clean_profile(p) for p in all_profiles if p.get('profile_url') in cached_urls]
            if results:
                return jsonify({'success': True, 'status': 'completed', 'profiles': results, 'total': len(results)}), 200

        # Fallback: return most recently scraped profiles whose name matches case-insensitively
        results = [clean_profile(p) for p in all_profiles if search_lower in (p.get('name') or '').lower()]
        if results:
            return jsonify({'success': True, 'status': 'completed', 'profiles': results, 'total': len(results)}), 200
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
    return emoji_pattern.sub(r"", text).strip()

def make_pdf_safe(text):
    """Sanitise text for PDF output — returns empty string (not N/A) if blank."""
    if not text:
        return ""
    s = str(text)
    replacements = {
        '\u2014': ' - ',  # em-dash
        '\u2013': '-',    # en-dash
        '\u201c': '"',    # left double quote
        '\u201d': '"',    # right double quote
        '\u2018': "'",    # left single quote
        '\u2019': "'",    # right single quote
        '\u2022': '*',    # bullet point
        '\xa0': ' ',      # non-breaking space
    }
    for orig, rep in replacements.items():
        s = s.replace(orig, rep)
        
    clean = strip_emojis(s)
    if clean.strip().lower() in ('none', 'null', 'n/a', 'na'):
        return ""
    return clean.encode('latin-1', 'replace').decode('latin-1')


def make_pdf_label(text, fallback='Unknown'):
    """Like make_pdf_safe but uses a fallback for truly required fields."""
    result = make_pdf_safe(text)
    return result if result.strip() else fallback

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

def _pdf_section_header(pdf, title):
    """Draw a section header with a blue underline rule."""
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(10, 102, 194)
    pdf.cell(0, 6, title, ln=True)
    pdf.set_fill_color(10, 102, 194)
    pdf.rect(15, pdf.get_y(), 180, 0.5, 'F')
    pdf.ln(4)

def build_profile_pdf(pdf, p):
    # Clean profile first so no null values sneak through
    p = clean_profile(p)

    image_path = None
    pic_url = p.get('profile_picture', '')
    if pic_url and pic_url.startswith('http'):
        image_path = download_profile_pic(pic_url)
        
    pdf.set_y(40)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 16)
    name_line = make_pdf_label(p.get('name', ''), fallback='Unknown Name')
    pdf.cell(130, 8, name_line, ln=True)
    
    headline = make_pdf_safe(p.get('headline', ''))
    if headline:
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(130, 5, headline)
        pdf.ln(2)
    
    location = make_pdf_safe(p.get('location', ''))
    if location:
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(130, 5, f"Location: {location}", ln=True)
    
    profile_url = make_pdf_safe(p.get('profile_url', ''))
    if profile_url:
        pdf.set_font("Arial", size=9)
        pdf.set_text_color(10, 102, 194)
        pdf.cell(130, 5, f"LinkedIn: {profile_url}", ln=True)
    
    connections = make_pdf_safe(str(p.get('connections', '')))
    if connections:
        pdf.set_font("Arial", size=9)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(130, 5, f"Connections: {connections}", ln=True)

    followers = make_pdf_safe(str(p.get('followers', '')))
    if followers:
        pdf.set_font("Arial", size=9)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(130, 5, f"Followers: {followers}", ln=True)
        
    pdf.ln(4)
    if image_path:
        try:
            pdf.image(image_path, x=155, y=42, w=35, h=35)
        except Exception as e:
            print(f"Error embedding image: {e}")
            
    current_y = pdf.get_y()
    if current_y < 85:
        pdf.set_y(85)
    
    # --- ABOUT ---
    about_text = make_pdf_safe(p.get('about', ''))
    if about_text:
        _pdf_section_header(pdf, "ABOUT")
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 5, about_text)
        pdf.ln(5)
        
    # --- CURRENT POSITION ---
    current_job = p.get('current_job')
    if current_job and isinstance(current_job, dict):
        job_title   = make_pdf_safe(current_job.get('title', ''))
        job_company = make_pdf_safe(current_job.get('company', ''))
        job_dur     = make_pdf_safe(current_job.get('duration', ''))
        if job_title or job_company:
            _pdf_section_header(pdf, "CURRENT POSITION")
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            pos_line = f"{job_title} at {job_company}" if (job_title and job_company) else (job_title or job_company)
            pdf.multi_cell(0, 5, pos_line)
            if job_dur:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 5, job_dur, ln=True)
            pdf.ln(4)

    # --- EXPERIENCE ---
    exp_list = p.get('experiences') or p.get('experience') or []
    if exp_list:
        _pdf_section_header(pdf, "EXPERIENCE")
        for exp in exp_list:
            if not isinstance(exp, dict):
                continue
            title    = make_pdf_safe(exp.get('title', ''))
            company  = make_pdf_safe(exp.get('company', ''))
            duration = make_pdf_safe(exp.get('duration', ''))
            loc      = make_pdf_safe(exp.get('location', ''))
            desc     = make_pdf_safe(exp.get('description', ''))
            
            if not title and not company:
                continue  # skip entirely empty entries
            
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            pos_line = f"{title} at {company}" if (title and company) else (title or company)
            pdf.multi_cell(0, 5, pos_line)
            
            meta_parts = []
            if duration: meta_parts.append(duration)
            if loc:      meta_parts.append(loc)
            if meta_parts:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 5, "  ".join(meta_parts), ln=True)
            if desc:
                pdf.set_font("Arial", size=9)
                pdf.set_text_color(50, 50, 50)
                pdf.multi_cell(0, 4, desc)
            pdf.ln(3)
        pdf.ln(2)

    # --- EDUCATION ---
    edu_list = p.get('education') or p.get('qualifications') or []
    if edu_list:
        _pdf_section_header(pdf, "EDUCATION & QUALIFICATIONS")
        for edu in edu_list:
            if not isinstance(edu, dict):
                continue
            inst   = make_pdf_safe(edu.get('institution', ''))
            degree = make_pdf_safe(edu.get('degree', ''))
            dates  = make_pdf_safe(edu.get('dates', ''))
            field  = make_pdf_safe(edu.get('field_of_study', ''))
            
            if not inst and not degree:
                continue
            
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            edu_line = f"{inst}" if inst else ''
            if degree:
                edu_line += f" - {degree}" if edu_line else degree

            if field:
                edu_line += f", {field}"
            pdf.multi_cell(0, 5, edu_line)
            if dates:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 5, dates, ln=True)
            pdf.ln(3)
        pdf.ln(2)

    # --- SKILLS ---
    skills_list = p.get('skills') or []
    if skills_list:
        _pdf_section_header(pdf, "SKILLS")
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(30, 30, 30)
        skills_formatted = []
        for s in skills_list:
            if isinstance(s, dict):
                skill_name = make_pdf_safe(s.get('skill') or s.get('name') or '')
                ends       = make_pdf_safe(str(s.get('endorsements', '')))
                if skill_name:
                    skills_formatted.append(f"{skill_name} ({ends} endorsements)" if ends and ends != '0' else skill_name)
            elif isinstance(s, str):
                safe_s = make_pdf_safe(s)
                if safe_s:
                    skills_formatted.append(safe_s)
        if skills_formatted:
            pdf.multi_cell(0, 5, make_pdf_safe(", ".join(skills_formatted)))
        pdf.ln(5)

    # --- CERTIFICATIONS ---
    cert_list = p.get('certifications') or []
    if cert_list:
        _pdf_section_header(pdf, "CERTIFICATIONS")
        for cert in cert_list:
            if not isinstance(cert, dict):
                continue
            cname  = make_pdf_safe(cert.get('name', ''))
            issuer = make_pdf_safe(cert.get('issuer', ''))
            date   = make_pdf_safe(cert.get('date', ''))
            
            if not cname:
                continue
            
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            cert_line = cname
            if issuer: cert_line += f" - {issuer}"

            pdf.cell(0, 5, cert_line, ln=True)
            if date:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 4, date, ln=True)
            pdf.ln(2)
        pdf.ln(2)

    # --- LANGUAGES ---
    lang_list = p.get('languages') or []
    if lang_list:
        _pdf_section_header(pdf, "LANGUAGES")
        pdf.set_font("Arial", size=10)
        pdf.set_text_color(30, 30, 30)
        langs_formatted = []
        for l in lang_list:
            if isinstance(l, dict):
                lang_name = make_pdf_safe(l.get('language', ''))
                prof      = make_pdf_safe(l.get('proficiency', ''))
                if lang_name:
                    langs_formatted.append(f"{lang_name} ({prof})" if prof else lang_name)
            elif isinstance(l, str):
                safe_l = make_pdf_safe(l)
                if safe_l:
                    langs_formatted.append(safe_l)
        if langs_formatted:
            pdf.multi_cell(0, 5, make_pdf_safe(", ".join(langs_formatted)))
        pdf.ln(5)

    # --- VOLUNTEER EXPERIENCE ---
    vol_list = p.get('volunteer') or []
    if vol_list:
        _pdf_section_header(pdf, "VOLUNTEER EXPERIENCE")
        for vol in vol_list:
            if not isinstance(vol, dict):
                continue
            role = make_pdf_safe(vol.get('role', ''))
            org  = make_pdf_safe(vol.get('organization', ''))
            dur  = make_pdf_safe(vol.get('duration', ''))
            
            if not role and not org:
                continue
            
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            vol_line = f"{role} at {org}" if (role and org) else (role or org)
            pdf.multi_cell(0, 5, vol_line)
            if dur:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 5, dur, ln=True)
            pdf.ln(3)
        pdf.ln(2)

    # --- HONORS & AWARDS ---
    hon_list = p.get('honors') or []
    if hon_list:
        _pdf_section_header(pdf, "HONORS & AWARDS")
        for hon in hon_list:
            if not isinstance(hon, dict):
                continue
            title  = make_pdf_safe(hon.get('title', ''))
            issuer = make_pdf_safe(hon.get('issuer', ''))
            date   = make_pdf_safe(hon.get('date', ''))
            
            if not title:
                continue
            
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            hon_line = f"{title} - {issuer}" if issuer else title

            pdf.multi_cell(0, 5, hon_line)
            if date:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 4, date, ln=True)
            pdf.ln(3)
        pdf.ln(2)

    # --- RECOMMENDATIONS ---
    rec_list = p.get('recommendations') or []
    _pdf_section_header(pdf, "RECOMMENDATIONS")
    if rec_list:
        for rec in rec_list:
            if not isinstance(rec, dict):
                continue
            recommender = make_pdf_safe(rec.get('recommender', ''))
            rec_title   = make_pdf_safe(rec.get('title', ''))
            text_val    = make_pdf_safe(rec.get('text', ''))
            
            if not recommender and not text_val:
                continue
            
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            rec_header = recommender
            if rec_title: rec_header += f" ({rec_title})"
            if rec_header:
                pdf.cell(0, 5, rec_header, ln=True)
            if text_val:
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(50, 50, 50)
                pdf.multi_cell(0, 4, text_val)
            pdf.ln(3)
        pdf.ln(2)
    else:
        pdf.set_font("Arial", 'I', 10)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 6, "None was received yet", ln=True)
        pdf.ln(4)

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
        tasks = _load_bucket_queue()
        task = next((t for t in tasks if t['id'] == return_code), None)
        if not task:
            return jsonify({'success': False, 'error': 'No scrape request found for the provided return_code'}), 404
        
    json_path = API_SCRAPES_DIR / f"{return_code}.json"
    if not json_path.exists():
        return jsonify({'success': False, 'error': 'Data file does not exist on disk'}), 404
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            p = json.load(f)
            
        if isinstance(p, dict) and 'profiles' in p:
            profiles = p['profiles']
        elif isinstance(p, list):
            profiles = p
        else:
            profiles = [p]

        pdf_path = API_SCRAPES_DIR / f"{return_code}.pdf"
        pdf = PDF()
        pdf.set_margins(15, 40, 15)
        pdf.set_auto_page_break(True, margin=15)
        
        for prof in profiles:
            pdf.add_page()
            build_profile_pdf(pdf, prof)
        
        pdf.output(str(pdf_path))
        return send_file(pdf_path, as_attachment=True, download_name=f"{return_code}.pdf", mimetype='application/pdf')
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': f'Error generating PDF: {str(e)}'}), 500

@app.route('/api/export-profile-pdf', methods=['POST'])
def export_profile_pdf():
    try:
        data = request.json or {}
        p = data.get('profile') or data.get('profiles')
        if not p:
            return jsonify({'success': False, 'error': 'profile data is required'}), 400
            
        if isinstance(p, dict) and 'profiles' in p:
            profiles = p['profiles']
        elif isinstance(p, list):
            profiles = p
        else:
            profiles = [p]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path("exports").mkdir(exist_ok=True)
        filename = f"linkedin_profile_{timestamp}.pdf"
        filepath = Path("exports") / filename
        
        pdf = PDF()
        pdf.set_margins(15, 40, 15)
        pdf.set_auto_page_break(True, margin=15)
        
        for prof in profiles:
            pdf.add_page()
            build_profile_pdf(pdf, prof)
        
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
@app.route('/api/scraper/export', methods=['POST'])
def export_scraper_data():
    """
    Export scraped profile data (single or bulk) as JSON or CSV file.
    Accepts JSON body:
      {
        "data": { "profiles": [...] } OR { "profile": {...} },
        "format": "json" | "csv"
      }
    """
    try:
        req_data = request.json or {}
        fmt = (req_data.get('format') or 'json').lower()
        data_obj = req_data.get('data') or {}

        # Extract profiles list
        profiles = []
        if isinstance(data_obj, dict):
            if 'profiles' in data_obj and isinstance(data_obj['profiles'], list):
                profiles = data_obj['profiles']
            elif 'profile' in data_obj and isinstance(data_obj['profile'], dict):
                profiles = [data_obj['profile']]
        elif isinstance(data_obj, list):
            profiles = data_obj

        if not profiles:
            if 'profiles' in req_data and isinstance(req_data['profiles'], list):
                profiles = req_data['profiles']
            elif 'profile' in req_data and isinstance(req_data['profile'], dict):
                profiles = [req_data['profile']]

        if not profiles:
            return jsonify({'success': False, 'error': 'No profiles found to export'}), 400

        # Clean all profiles
        cleaned_profiles = [clean_profile(p) for p in profiles]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path("exports").mkdir(exist_ok=True)

        if fmt == 'csv':
            filename = f"linkedin_export_bulk_{timestamp}.csv" if len(cleaned_profiles) > 1 else f"linkedin_export_{timestamp}.csv"
            filepath = Path("exports") / filename

            headers = [
                'name', 'headline', 'location', 'profile_picture', 'about', 
                'current_job', 'experience', 'qualifications', 'certifications', 
                'profile_url', 'scraped_at'
            ]
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for p in cleaned_profiles:
                    writer.writerow([
                        p.get('name', ''),
                        p.get('headline', ''),
                        p.get('location', ''),
                        p.get('profile_picture', ''),
                        p.get('about', ''),
                        json.dumps(p.get('current_job', {})),
                        json.dumps(p.get('experience', []) or p.get('experiences', [])),
                        json.dumps(p.get('qualifications', []) or p.get('education', [])),
                        json.dumps(p.get('certifications', [])),
                        p.get('profile_url', ''),
                        p.get('scraped_at', '')
                    ])
            return send_file(filepath, as_attachment=True, download_name=filename, mimetype='text/csv')

        else:  # Default JSON export
            filename = f"linkedin_export_bulk_{timestamp}.json" if len(cleaned_profiles) > 1 else f"linkedin_export_{timestamp}.json"
            filepath = Path("exports") / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({'profiles': cleaned_profiles, 'total': len(cleaned_profiles)}, f, indent=2, ensure_ascii=False)
            return send_file(filepath, as_attachment=True, download_name=filename, mimetype='application/json')

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Export error: {str(e)}'}), 500

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

        # Update in task bucket queue if present
        tasks = _load_bucket_queue()
        task_found = False
        for t in tasks:
            if t['id'] == request_id:
                t['status'] = 'completed'
                t['completed_at'] = scraped_at
                t['result_name'] = profile.get('name', person_name)
                t['result_url'] = profile_url
                t['profiles_found'] = 1
                t['error'] = None
                task_found = True
                break
        if task_found:
            _save_bucket_queue(tasks)
            _broadcast_sse('bucket_update', {'task_id': request_id, 'status': 'completed', 'query': person_name})

        # Save to name cache to link name -> URL mapping for lookup-by-name
        client_name = person_name
        with db_lock:
            cache_data = {}
            if NAME_CACHE_FILE.exists():
                try:
                    with open(NAME_CACHE_FILE, 'r', encoding='utf-8') as _f:
                        cache_data = json.load(_f)
                except Exception:
                    pass
            cache_data[client_name] = [profile_url]
            with open(NAME_CACHE_FILE, 'w', encoding='utf-8') as _f:
                json.dump(cache_data, _f, indent=2)
                    
        return jsonify({'success': True, 'profile': profile})
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Update in task bucket queue if present to failed
        tasks = _load_bucket_queue()
        task_found = False
        for t in tasks:
            if t['id'] == request_id:
                t['status'] = 'failed'
                t['completed_at'] = datetime.now().isoformat()
                t['error'] = str(e)
                task_found = True
                break
        if task_found:
            _save_bucket_queue(tasks)
            _broadcast_sse('bucket_update', {'task_id': request_id, 'status': 'failed', 'query': person_name})
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
        # Clear name cache and task bucket queue
        with db_lock:
            if NAME_CACHE_FILE.exists():
                try:
                    with open(NAME_CACHE_FILE, 'w', encoding='utf-8') as f:
                        f.write('{}')
                except Exception:
                    pass
            if BUCKET_QUEUE_FILE.exists():
                try:
                    with open(BUCKET_QUEUE_FILE, 'w', encoding='utf-8') as f:
                        f.write('[]')
                except Exception:
                    pass
        _broadcast_sse('bucket_cleared', {})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Background Bulk scraping worker
async def perform_background_bulk_scrape(profile_urls, return_code):
    global scraper
    async with _get_scrape_lock():
        try:
            if not scraper:
                print("Auto-initializing scraper for background bulk API request...")
                _kill_playwright_chromium()
                scraper = LinkedInScraper(headless=False, browser_type='chromium', session_name='default')
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
                    import random
                    delay = random.randint(12, 25)
                    print(f"[BulkScrape] Resting {delay}s before next profile...")
                    await asyncio.sleep(delay)
            
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
            
    # Enqueue tasks into Task Bucket queue linked to return_code
    tasks = _load_bucket_queue()
    added = []
    for url in profile_urls:
        u = str(url).strip()
        if not u:
            continue
        task = {
            'id': str(_uuid.uuid4()),
            'query': u,
            'type': 'url' if u.startswith('http') else 'name',
            'status': 'pending',
            'added_at': datetime.now().isoformat(),
            'started_at': None,
            'completed_at': None,
            'result_name': '',
            'result_url': u if u.startswith('http') else '',
            'error': None,
            'bulk_return_code': return_code
        }
        tasks.append(task)
        added.append(task)

    _save_bucket_queue(tasks)
    _broadcast_sse('bucket_tasks_added', {'count': len(added), 'bulk_return_code': return_code})
    _ensure_worker_running()
    
    return jsonify({
        'success': True,
        'message': f'Bulk scrape request with {len(added)} item(s) queued successfully into the queue.',
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
        tasks = _load_bucket_queue()
        task = next((t for t in tasks if t['id'] == reference_number), None)
        if task:
            status = task.get('status', 'pending')
            if status == 'completed':
                json_path = API_SCRAPES_DIR / f"{reference_number}.json"
                if json_path.exists():
                    try:
                        with open(json_path, 'r', encoding='utf-8') as f:
                            bulk_data = json.load(f)
                        profiles_list = bulk_data.get('profiles', [bulk_data]) if isinstance(bulk_data, dict) else bulk_data
                        return jsonify({
                            'success': True,
                            'status': 'completed',
                            'profiles': profiles_list,
                            'total': len(profiles_list),
                            'reference_number': reference_number
                        })
                    except Exception:
                        pass
            elif status == 'failed':
                return jsonify({
                    'success': False,
                    'status': 'failed',
                    'reference_number': reference_number,
                    'person_name': task.get('query', ''),
                    'error': task.get('error', 'The scrape job failed. Please contact the admin.')
                }), 200
                
            return jsonify({
                'success': False,
                'status': status,
                'reference_number': reference_number,
                'person_name': task.get('query', ''),
                'requested_at': task.get('added_at', ''),
                'message': f"This search is currently '{status}' in the task bucket queue. Please wait."
            }), 202

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
_worker_launch_lock = threading.Lock()

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


def _cleanup_stale_in_progress_tasks():
    """Reset any tasks marked as in_progress back to pending on startup."""
    tasks = _load_bucket_queue()
    changed = False
    for t in tasks:
        if t.get('status') == 'in_progress':
            t['status'] = 'pending'
            t['started_at'] = None
            changed = True
    if changed:
        _save_bucket_queue(tasks)

_cleanup_stale_in_progress_tasks()


def _pop_next_pending_task():
    """Atomically find the first pending task in queue.json and mark it in_progress."""
    with bucket_lock:
        if not BUCKET_QUEUE_FILE.exists():
            return None
        try:
            with open(BUCKET_QUEUE_FILE, 'r', encoding='utf-8') as f:
                tasks = json.load(f)
        except Exception:
            return None

        for t in tasks:
            if t.get('status') == 'pending':
                t['status'] = 'in_progress'
                t['started_at'] = datetime.now().isoformat()
                with open(BUCKET_QUEUE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(tasks, f, indent=2, ensure_ascii=False)
                return t
    return None


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


def _check_and_finalize_bulk_job(bulk_return_code: str):
    """Check if all tasks belonging to bulk_return_code are done. If so, consolidate data and update jobs.json."""
    if not bulk_return_code:
        return
    tasks = _load_bucket_queue()
    related = [t for t in tasks if t.get('bulk_return_code') == bulk_return_code]
    if not related:
        return
    unfinished = [t for t in related if t.get('status') in ('pending', 'in_progress')]
    if unfinished:
        return  # still running

    # All related tasks are finished! Collect profiles from completed tasks.
    scraped_profiles = []
    errors = []

    for t in related:
        t_id = t.get('id')
        if t.get('status') == 'failed':
            if t.get('error'):
                errors.append(f"{t.get('query')}: {t.get('error')}")
        elif t.get('status') == 'completed' and t_id:
            json_path = API_SCRAPES_DIR / f"{t_id}.json"
            if json_path.exists():
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        raw = json.load(f)
                    if isinstance(raw, dict) and 'profiles' in raw:
                        scraped_profiles.extend(raw['profiles'])
                    elif isinstance(raw, list):
                        scraped_profiles.extend(raw)
                    elif isinstance(raw, dict):
                        scraped_profiles.append(raw)
                except Exception:
                    pass

    # Save consolidated bulk JSON and CSV
    scraped_at = datetime.now().isoformat()
    with api_scrape_lock:
        json_path = API_SCRAPES_DIR / f"{bulk_return_code}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({'profiles': scraped_profiles}, f, indent=2, ensure_ascii=False)

        csv_path = API_SCRAPES_DIR / f"{bulk_return_code}.csv"
        headers = [
            'name', 'headline', 'location', 'profile_picture', 'about', 
            'current_job', 'experience', 'qualifications', 'certifications', 
            'profile_url', 'scraped_at', 'return_code'
        ]
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for p in scraped_profiles:
                writer.writerow([
                    p.get('name', ''), p.get('headline', ''), p.get('location', ''),
                    p.get('profile_picture', ''), p.get('about', ''),
                    json.dumps(p.get('current_job', {})),
                    json.dumps(p.get('experience', []) or p.get('experiences', [])),
                    json.dumps(p.get('qualifications', []) or p.get('education', [])),
                    json.dumps(p.get('certifications', [])),
                    p.get('profile_url', ''),
                    p.get('scraped_at', scraped_at),
                    bulk_return_code
                ])

    final_status = 'completed' if scraped_profiles or not errors else 'failed'
    err_str = "; ".join(errors) if errors else None
    update_job_status(bulk_return_code, final_status, scraped_at=scraped_at, error=err_str)
    print(f"[TaskBucket] Bulk job '{bulk_return_code}' finalized: status={final_status} ({len(scraped_profiles)} profiles)")


# ── Background worker ─────────────────────────────────────────────────────────
async def _bucket_worker():
    """
    Background worker loop for processing Task Bucket items one by one sequentially.
    Guaranteed single-worker execution.
    """
    global _bucket_worker_running, _bucket_worker_paused, scraper
    print("[TaskBucket] Worker thread started")
    try:
        while True:
            if _bucket_worker_paused:
                await asyncio.sleep(2)
                continue

            task = _pop_next_pending_task()
            if not task:
                await asyncio.sleep(3)
                continue

            task_id   = task['id']
            query     = task['query']
            task_type = task.get('type', 'name')
            bulk_rc   = task.get('bulk_return_code')

            print(f"[TaskBucket] Processing task {task_id} ({task_type}): '{query}'")
            _broadcast_sse('bucket_update', {'task_id': task_id, 'status': 'in_progress', 'query': query})

            try:
                async with _get_scrape_lock():
                    # Auto-init scraper if needed, or re-verify current session authentication
                    if not scraper:
                        _kill_playwright_chromium()  # clear orphan processes before launching
                        s = LinkedInScraper(headless=False, browser_type='chromium', session_name='default')
                        await s.initialize()
                        scraper = s
                    else:
                        is_ok = await scraper.check_auth()
                        if not is_ok:
                            print("[TaskBucket] Scraper session invalid/disconnected. Re-initializing...")
                            try:
                                await scraper.close()
                            except Exception:
                                pass
                            scraper = None
                            _kill_playwright_chromium()  # clear orphan processes before re-launching
                            s = LinkedInScraper(headless=False, browser_type='chromium', session_name='default')
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
                            with api_scrape_lock:
                                save_scraped_data_formats(extracted, task_id)

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
                if any(k in err.lower() for k in ["target page", "closed", "crashed", "disconnected", "context"]):
                    is_dead = True
                    try:
                        if scraper and scraper.page and not scraper.page.is_closed():
                            # Page is alive, no need to kill browser process
                            is_dead = False
                    except Exception:
                        is_dead = True

                    if is_dead:
                        print("[TaskBucket] Browser disconnect detected. Resetting scraper session...")
                        try:
                            if scraper:
                                await scraper.close()
                        except Exception:
                            pass
                        scraper = None
                        _kill_playwright_chromium()

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

            # Check if this task belongs to a bulk scrape job and finalize if all tasks are done
            if bulk_rc:
                _check_and_finalize_bulk_job(bulk_rc)

            # Rest period before next task
            cfg = _load_bucket_config()
            import random
            base_rest = int(cfg.get('rest_seconds', 30))
            if base_rest > 0:
                rest = random.randint(max(15, base_rest), max(25, base_rest + 15))
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
        with _worker_launch_lock:
            _bucket_worker_running = False
        print("[TaskBucket] Worker stopped")


def _ensure_worker_running():
    """Start the bucket worker coroutine if it isn't already alive."""
    global _bucket_worker_running
    with _worker_launch_lock:
        if not _bucket_worker_running:
            _bucket_worker_running = True
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


@app.route('/api/bucket/upload', methods=['POST'])
def bucket_upload():
    """Upload a CSV or JSON file to add multiple tasks to the bucket queue."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file part in the request'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected for uploading'}), 400

    tasks_added = []
    filename_lower = (file.filename or '').lower()

    try:
        raw_bytes = file.stream.read()
        if not raw_bytes:
            return jsonify({'success': False, 'error': 'Uploaded file is empty'}), 400

        if filename_lower.endswith('.csv'):
            try:
                text_content = raw_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                text_content = raw_bytes.decode('latin-1', errors='replace')

            stream = io.StringIO(text_content, newline=None)
            csv_input = list(csv.reader(stream))
            if not csv_input:
                return jsonify({'success': False, 'error': 'CSV file contains no rows'}), 400

            # Synonym set for headers
            possible_headers = {
                'query', 'queries', 'name', 'full_name', 'fullname', 'person_name',
                'username', 'url', 'profile', 'profile_url', 'linkedin_url', 'link',
                'linkedin', 'search', 'user', 'profile link', 'linkedin profile'
            }

            first_row = True
            header_col_idx = 0

            for row in csv_input:
                if not row:
                    continue
                cleaned_row = [str(c).strip() for c in row if c is not None]
                if not cleaned_row or not any(cleaned_row):
                    continue

                if first_row:
                    first_row = False
                    lower_cols = [c.lower() for c in cleaned_row]
                    found_header_idx = -1

                    for idx, col in enumerate(lower_cols):
                        if col in possible_headers or any(h in col for h in ('profile', 'url', 'linkedin', 'name', 'query')):
                            found_header_idx = idx
                            break

                    if found_header_idx != -1:
                        header_col_idx = found_header_idx
                        continue  # Skip header row
                    else:
                        header_col_idx = 0

                if header_col_idx < len(cleaned_row):
                    val = cleaned_row[header_col_idx].strip()
                    if val:
                        tasks_added.append(val)

        elif filename_lower.endswith('.json'):
            try:
                text_content = raw_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                text_content = raw_bytes.decode('latin-1', errors='replace')

            json_data = json.loads(text_content)

            items_to_parse = []
            if isinstance(json_data, list):
                items_to_parse = json_data
            elif isinstance(json_data, dict):
                for key in ('queries', 'profiles', 'urls', 'data', 'items', 'list', 'names'):
                    if key in json_data and isinstance(json_data[key], list):
                        items_to_parse = json_data[key]
                        break
                if not items_to_parse:
                    items_to_parse = [json_data]

            for item in items_to_parse:
                if isinstance(item, str):
                    val = item.strip()
                    if val:
                        tasks_added.append(val)
                elif isinstance(item, dict):
                    for key in ('query', 'url', 'profile_url', 'linkedin_url', 'link', 'name', 'full_name', 'person_name', 'username'):
                        if key in item and item[key]:
                            val = str(item[key]).strip()
                            if val:
                                tasks_added.append(val)
                                break
        else:
            return jsonify({'success': False, 'error': 'Allowed file types are CSV (.csv) and JSON (.json)'}), 400

        if not tasks_added:
            return jsonify({'success': False, 'error': 'No valid names or URLs found in the uploaded file'}), 400

        # Add to bucket
        tasks = _load_bucket_queue()
        added = []
        for q in tasks_added:
            q = q.strip()
            if not q:
                continue
            detected_type = 'url' if q.startswith('http') else 'name'
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
        _ensure_worker_running()

        return jsonify({
            'success': True,
            'added': len(added),
            'message': f'Successfully uploaded and queued {len(added)} task(s) into the queue.'
        }), 201

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Error processing file: {str(e)}'}), 500



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


# Run the Flask app
if __name__ == '__main__':
    print("Persona - LinkedIn Profile Scraper and Ranker")
    print("http://localhost:5000")
    # use_reloader=False prevents Flask from spawning duplicate background worker processes
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000, threaded=True)