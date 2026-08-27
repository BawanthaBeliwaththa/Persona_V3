#Required Imports
import sys
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import os
import re
from typing import Dict, List
from datetime import datetime
from playwright.async_api import async_playwright
from pathlib import Path

# Force stdout/stderr to be unbuffered so logs print in real-time on Windows
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


# ── Global noise filter ────────────────────────────────────────────────────────
# Lines that appear in LinkedIn's UI chrome, navigation, sidebars, and CTA
# buttons — never real profile data.
_UI_NOISE = {
    # Navigation / chrome
    'LinkedIn', 'Home', 'My Network', 'Jobs', 'Messaging', 'Notifications',
    'Search', 'Me', 'Work', 'Premium', 'Try Premium for free', 'Try Premium for $0',
    'Sales Navigator', 'Recruiter', 'Learning', 'Ad Choices', 'Advertising',
    'Talent Solutions', 'Marketing Solutions', 'Sales Solutions', 'Small Business',
    'Safety Center', 'Community Guidelines', 'Careers', 'Privacy & Terms',
    'Accessibility', 'Help Center', 'Select language', 'LinkedIn Corporation',
    'LinkedIn Corporation © 2026', 'LinkedIn Corporation © 2025',
    # Generic expand/collapse & action buttons
    'Show all', 'Show more', 'See more', 'See less', 'Show less',
    'Show all experiences', 'Show all education', 'Show all skills',
    'Show all licenses & certifications', 'Show all honors & awards',
    'Show all volunteer experience', 'Show all recommendations',
    'Show all languages', 'Add skills', 'Add languages', 'Add profile section',
    'Show all 1 experience', 'Show all 1 education', 'Show credential',
    'More', 'Connect', 'Follow', 'Message', 'Saved', 'Save', 'Report', 'Block',
    'Share via message', 'Share via...', 'Copy link to profile', 'Send message',
    'Endorse', 'Endorsed', 'Verified', 'Verification', 'Verified member',
    'Passed skill assessment', 'Top skill', 'Skill assessment',
    # Tab labels inside detail pages & headers
    'Received', 'Given', 'All', 'Top skills', 'About', 'Experience', 'Experiences',
    'Education', 'Licenses & certifications', 'Certifications', 'Skills',
    'Languages', 'Honors & awards', 'Volunteer experience', 'Recommendations',
    'Interests', 'Causes', 'Groups', 'Newsletters',
    # Common sidebar / footer
    'People also viewed', 'People you may know', 'Suggested for you',
    'More profiles for you', 'Activity', 'Following',
    # Misc UI
    'Open to', 'Open to work', 'Hiring', 'Pronouns',
    'Contact info', 'Company size', 'Industry', 'Employees',
    '1st', '2nd', '3rd', '· 1st', '· 2nd', '· 3rd',
    '1st degree connection', '2nd degree connection',
    '• 1st', '• 2nd', '• 3rd',
}

# Patterns that indicate a line is UI noise (not profile data)
_UI_NOISE_PATTERNS = [
    re.compile(r'^\d+(\+)?\s+(connection|follower)', re.I),       # "500+ connections"
    re.compile(r'^(See|Show|View)\s+all(\s+\d+)?', re.I),           # "See all 12 …"
    re.compile(r'^Show\s+credential', re.I),
    re.compile(r'^Endorsed\s+by', re.I),
    re.compile(r'^\d+\s+endorsement', re.I),
    re.compile(r'^Skill(s)?(\s+\d+)?$', re.I),
    re.compile(r'^·\s+\d+\s+(yr|mo|week|day)', re.I),               # "· 2 yrs 3 mos"
    re.compile(r'^linkedin\.com', re.I),
    re.compile(r'^www\.linkedin\.com', re.I),
    re.compile(r'^\s*\d+\s*$'),                                    # lone digit (page numbers etc.)
    re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}$', re.I),  # bare dates
    re.compile(r'^[•·\-\s]+$'),                                    # bullet/dash-only lines
]

# Known proficiency keywords for languages
_PROFICIENCY_KW = {
    'native', 'bilingual', 'full professional', 'professional working',
    'limited working', 'elementary', 'fluent', 'advanced', 'intermediate',
    'beginner', 'basic', 'conversational', 'working proficiency',
    'native or bilingual', 'professional',
}

# Duration/date patterns that signal the end of a title/org line
_DURATION_RE = re.compile(
    r'\b(\d{4}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|'
    r'Present|Current|Now|\d+\s*yr|\d+\s*mo|\d+\s*week)',
    re.I
)


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

_JUNK_SUBSTRINGS = [
    'select language', 'help center', 'manage your account', 'go to your settings',
    'recommendation transparency', 'recommended content', 'linkedin corporation',
    'talent solutions', 'community guidelines', 'privacy & terms', 'ad choices',
    'marketing solutions', 'sales solutions', 'safety center', 'small business',
    'accessibility', 'visit our help center', 'questions?', 'show credential'
]

_LANG_DROPDOWN_RE = re.compile(
    r'\(\s*(arabic|bangla|czech|danish|german|greek|english|spanish|persian|'
    r'finnish|french|hindi|hungarian|indonesian|italian|hebrew|japanese|'
    r'korean|marathi|malay|dutch|norwegian|punjabi|polish|portuguese|'
    r'romana|românia|romanian|russian|swedish|telugu|thai|tagalog|turkish|'
    r'ukrainian|vietnamese|chinese)\b',
    re.I
)

def _is_junk_text(text: str) -> bool:
    """Return True if the string is recognised LinkedIn footer/UI garbage."""
    if not text:
        return False
    t = text.strip().lower()
    if t in _LINKEDIN_FOOTER_TOKENS:
        return True
    if any(j in t for j in _JUNK_SUBSTRINGS):
        return True
    if _LANG_DROPDOWN_RE.search(t):
        return True
    return False

def _is_junk_entry(entry) -> bool:
    """Return True if a dict entry looks like scraped UI garbage, not real content."""
    if not isinstance(entry, dict):
        return False
    values = [str(v).strip() for v in entry.values() if v]
    if values and any(_is_junk_text(v) for v in values):
        return True
    for key in ('duration', 'date', 'dates'):
        v = entry.get(key, '')
        if v and _is_junk_text(str(v)):
            return True
    return False

def _is_real_language(lang_name: str) -> bool:
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

def _clean_about(about_text: str) -> str:
    """Strip the LinkedIn footer/language-selector content and 'more...' artifacts from the About field."""
    if not about_text:
        return ''

    lines = about_text.split('\n')
    clean_lines = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if _is_junk_text(s):
            break
        s = s.replace('… more', '').replace('...more', '').replace('more...', '').replace('…', '')
        if s.lower() in ('about', 'see more', 'show more'):
            continue
        clean_lines.append(s)
    res = '\n'.join(clean_lines).strip()
    for junk in ['… more', '...more', '... more', '…more', 'more...', '... see more', 'see more', '…']:
        if res.endswith(junk):
            res = res[:-len(junk)].strip()
    return res

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

clean_profile = sanitize_profile


def _is_noise(line: str) -> bool:
    """Return True if the line is UI chrome, not real profile text."""
    s = line.strip()
    if not s:
        return True
    if s in _UI_NOISE or _is_junk_text(s):
        return True
    if any(p.search(s) for p in _UI_NOISE_PATTERNS):
        return True
    # Very short lines that are likely icons / counts / badges
    if len(s) <= 2:
        return True
    return False


def _looks_like_duration(line: str) -> bool:
    return bool(_DURATION_RE.search(line.strip()))


def _looks_like_proficiency(line: str) -> bool:
    lower = line.strip().lower()
    return any(kw in lower for kw in _PROFICIENCY_KW)



# Core LinkedIn Scraper Class
class LinkedInScraper:
    def __init__(self, headless: bool = False, browser_type: str = "chromium", session_name: str = "default"):
        self.headless = headless
        self.browser_type = browser_type
        self.session_name = session_name
        self.playwright = None
        self.context = None
        self.page = None
        self.is_authenticated = False
        self.verification_required = False
        self.stats = {'requests_made': 0, 'profiles_scraped': 0, 'errors': 0, 'start_time': None, 'runtime_seconds': 0}
        self.user_data_dir = Path(f"./browser_data/{session_name}")
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

    def sanitize_profile(self, profile):
        """Sanitize profile using global cleaner."""
        return sanitize_profile(profile)

    # ── Static helpers for lock cleanup ──────────────────────────────────────
    _LOCK_PATTERNS = ['SingletonLock', 'SingletonCookie', 'SingletonSocket']
    _DB_DIRS_WITH_LOCKS = [
        'Default/Local Storage/leveldb',
        'Default/Session Storage',
        'Default/IndexedDB',
        'Default/Sync Data/LevelDB',
        'Default/Site Characteristics Database',
        'Default/shared_proto_db',
        'Default/shared_proto_db/metadata',
        'Default/Extension State',
        'Default/GCM Store',
    ]

    @staticmethod
    def _kill_orphan_chromium(browser_data_marker: str = 'browser_data'):
        """Force-kill any Chromium processes that were launched with our profile dir.
        Must be called BEFORE _remove_locks so the files are no longer held open."""
        import subprocess, sys
        try:
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['wmic', 'process', 'where',
                     f"name='chrome.exe' and CommandLine like '%{browser_data_marker}%'",
                     'get', 'ProcessId', '/FORMAT:CSV'],
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
                            print(f"[init] Killed orphan Chromium PID {pid}")
                        except (ValueError, Exception):
                            pass
                if killed:
                    import time
                    time.sleep(2)  # allow Windows to release file handles
            else:
                subprocess.run(['pkill', '-f', f'chromium.*{browser_data_marker}'], capture_output=True, timeout=5)
                subprocess.run(['pkill', '-f', f'chrome.*{browser_data_marker}'], capture_output=True, timeout=5)
        except Exception as ex:
            print(f"[init] _kill_orphan_chromium: {ex} (non-fatal)")

    @staticmethod
    def _remove_locks(base_dir: Path):
        """Remove Singleton* and LevelDB LOCK files, plus residual Chrome caches."""
        import shutil
        # Singleton files at profile root
        for pat in LinkedInScraper._LOCK_PATTERNS:
            lock_file = base_dir / pat
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    print(f"Removed stale lock: {lock_file}")
                except Exception as ex:
                    print(f"Could not remove {lock_file}: {ex}")
        # LevelDB LOCK files inside subdirectories
        for subdir in LinkedInScraper._DB_DIRS_WITH_LOCKS:
            lock_file = base_dir / subdir / 'LOCK'
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    print(f"Removed stale lock: {lock_file}")
                except Exception as ex:
                    print(f"Could not remove {lock_file}: {ex}")
        # Residual Chrome downgrade delete markers & caches
        for name in ('Snapshots.CHROME_DELETE', 'default.CHROME_DELETE', 'ShaderCache'):
            item = base_dir / name
            if item.exists():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink()
                    print(f"Removed residual directory/file: {item}")
                except Exception as ex:
                    print(f"Could not remove residual {item}: {ex}")

    # Initialization and Login
    async def initialize(self):
        print("Initializing browser...")
        self.stats['start_time'] = datetime.now()

        # ── Step 1: Kill any orphan Chromium processes FIRST so lock files become free ──
        self._kill_orphan_chromium()

        # ── Step 2: Remove stale lock files now that processes are dead ──
        self._remove_locks(self.user_data_dir)

        self.playwright = await async_playwright().start()

        launch_kwargs = dict(
            headless=self.headless,
            viewport={'width': 1440, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Sec-Ch-Ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            },
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-infobars',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
            ]
        )

        # First attempt: persistent profile (preserves LinkedIn session/cookies)
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(self.user_data_dir),
                **launch_kwargs
            )
        except Exception as e:
            print(f"Persistent context launch failed: {e}. Attempting recovery...")
            # ── Recovery: kill processes again, clean locks, wait, retry ──
            await self.playwright.stop()
            self.playwright = None
            self._kill_orphan_chromium()
            self._remove_locks(self.user_data_dir)
            await asyncio.sleep(2)  # extra async wait for Windows handle release

            self.playwright = await async_playwright().start()
            try:
                self.context = await self.playwright.chromium.launch_persistent_context(
                    str(self.user_data_dir),
                    **launch_kwargs
                )
                print("Recovery successful! Browser launched with existing profile.")
            except Exception as retry_err:
                print(f"Recovery launch failed: {retry_err}. Nuking profile for fresh start...")
                await self.playwright.stop()
                self.playwright = None

                # ── Nuclear option: delete the entire profile and start fresh ──
                import shutil
                try:
                    shutil.rmtree(self.user_data_dir, ignore_errors=True)
                    self.user_data_dir.mkdir(parents=True, exist_ok=True)
                    print("[init] Profile directory wiped. Starting with a fresh profile.")
                except Exception as nuke_err:
                    print(f"[init] Could not wipe profile: {nuke_err}")

                await asyncio.sleep(1)
                self.playwright = await async_playwright().start()
                try:
                    self.context = await self.playwright.chromium.launch_persistent_context(
                        str(self.user_data_dir),
                        **launch_kwargs
                    )
                    print("Fresh profile launch successful!")
                except Exception as final_err:
                    print(f"Final launch failed: {final_err}")
                    await self.playwright.stop()
                    self.playwright = None
                    raise RuntimeError(
                        "Browser could not launch after multiple recovery attempts. "
                        "Please restart the application. "
                        f"(Final error: {final_err})"
                    )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        # Check existing session in persistent browser profile
        try:
            await self.page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(2)
            base_url = self.page.url.split('?')[0].rstrip('/')
            if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                self.is_authenticated = True
                print("[Init] User is already logged in with persistent profile.")
            else:
                self.is_authenticated = False
                print("[Init] Not logged in – authentication required.")
        except Exception as e:
            print(f"[Init] Initial feed check notice: {e}")
            self.is_authenticated = False

        return self


    async def ensure_active_page(self):
        """Ensure that the browser, context, and page are alive and responsive before performing operations."""
        try:
            if not self.context or not self.playwright:
                print("[LinkedInScraper] No active context/playwright. Initializing...")
                await self.initialize()
                return

            is_page_closed = False
            try:
                if not self.page or self.page.is_closed():
                    is_page_closed = True
                else:
                    _ = self.page.url
            except Exception:
                is_page_closed = True

            if is_page_closed:
                print("[LinkedInScraper] Main page is closed or target context destroyed. Restoring page...")
                if self.context and self.context.pages:
                    self.page = self.context.pages[0]
                elif self.context:
                    self.page = await self.context.new_page()
                    await self.context.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                        window.chrome = { runtime: {} };
                    """)
                else:
                    await self.initialize()
        except Exception as e:
            print(f"[LinkedInScraper] Error in ensure_active_page, re-initializing session: {e}")
            await self.initialize()

    async def check_auth(self) -> bool:
        """Check if the current browser session is authenticated on LinkedIn.
        
        If li_at was pre-injected at context level, we trust it immediately.
        Only navigates to /feed/ as a fallback when not already known-authenticated.
        """
        await self.ensure_active_page()
        if not self.page or not self.context:
            self.is_authenticated = False
            return False

        # If cookie was pre-injected, trust it — avoid /feed/ navigation which causes redirect loops
        if getattr(self, '_li_at_injected', False) and self.is_authenticated:
            return True

        try:
            base_url = self.page.url.split('?')[0].rstrip('/')
            if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                self.is_authenticated = True
                return True
            # Only navigate to /feed/ if we don't have a pre-injected cookie
            if not getattr(self, '_li_at_injected', False):
                await self.page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=15000)
                await asyncio.sleep(1)
                base_url = self.page.url.split('?')[0].rstrip('/')
                if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                    self.is_authenticated = True
                    return True
        except Exception as e:
            print(f"[LinkedInScraper] check_auth exception: {e}")
            pass
        self.is_authenticated = False
        return False

    async def is_premium_account(self) -> bool:
        """Check if the logged-in account has a LinkedIn Premium subscription."""
        if not await self.check_auth():
            return False
        try:
            # Check the feed page for the 'Try Premium for free' link
            # If it exists, they are not premium.
            await self.page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(2)
            is_free = await self.page.evaluate('''() => {
                const links = Array.from(document.querySelectorAll('a'));
                return links.some(a => a.innerText.toLowerCase().includes('try premium for free') || a.href.includes('/premium/'));
            }''')
            # Alternatively, look for a premium icon on the profile drop-down or navbar.
            has_premium_icon = await self.page.evaluate('''() => {
                return !!document.querySelector('li-icon[type="premium-brand"], svg.premium-icon, svg[data-supported-dps="24x24_premium_icon"]');
            }''')
            
            # If we explicitly see "Try Premium for free", it's false.
            if is_free:
                return False
            # Otherwise if we see the icon, it's true.
            if has_premium_icon:
                return True
            # Fallback: assume false if we couldn't definitively tell
            return False
        except Exception as e:
            print(f"Error checking premium status: {e}")
            return False

    async def search_by_contact_info(self, email: str = "", phone: str = "") -> List[Dict]:
        """Search for a profile by email or phone (requires Premium/Sales Nav)."""
        # We will attempt a general LinkedIn search using the email/phone as a keyword.
        # This often works if the user has Premium or if the profile is highly visible.
        keyword = email if email else phone
        if not keyword:
            return []
            
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={keyword}"
        await self.page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)
        
        # Scroll to load results
        for _ in range(5):
            await self.page.evaluate('window.scrollBy(0, 500)')
            await asyncio.sleep(0.5)
            
        results = await self.page.evaluate('''() => {
            const items = document.querySelectorAll('li.reusable-search__result-container');
            const data = [];
            for (const item of items) {
                const link = item.querySelector('.app-aware-link');
                const img = item.querySelector('img');
                const title = item.querySelector('.entity-result__primary-subtitle');
                const subtitle = item.querySelector('.entity-result__secondary-subtitle');
                if (link && link.href && link.href.includes('/in/')) {
                    let url = link.href.split('?')[0];
                    data.push({
                        profile_url: url,
                        name: link.innerText.trim().split('\\n')[0],
                        profile_picture: img ? img.src : '',
                        headline: title ? title.innerText.trim() : '',
                        location: subtitle ? subtitle.innerText.trim() : ''
                    });
                }
            }
            return data;
        }''')
        return results



    # Login method (if not already authenticated)

    async def login_with_cookie(self, li_at: str) -> bool:
        """Inject li_at session cookie directly into browser context without a /feed/ roundtrip.
        
        Avoids ERR_TOO_MANY_REDIRECTS by NOT navigating to verify — the cookie is trusted
        and auth is confirmed on the first profile extraction attempt.
        """
        try:
            await self.ensure_active_page()
            if not self.context:
                return False

            cookie_val = str(li_at).strip()
            if 'li_at=' in cookie_val:
                cookie_val = cookie_val.split('li_at=')[1].split(';')[0].strip()

            if not cookie_val:
                print("[Cookie Login] Empty li_at value — skipping.")
                return False

            # Clear old conflicting cookies from persistent store first
            try:
                await self.context.clear_cookies()
            except Exception:
                pass

            # Inject cookie with domain .linkedin.com
            await self.context.add_cookies([
                {'name': 'li_at', 'value': cookie_val, 'domain': '.linkedin.com', 'path': '/', 'httpOnly': True, 'secure': True}
            ])

            self.is_authenticated = True
            self._li_at_injected = True
            print("[Cookie Login] li_at cookie injected cleanly into browser context.")
            return True

        except Exception as e:
            print(f"[Cookie Login] Error injecting cookie: {e}")
        return False

    async def submit_verification_pin(self, pin_code: str) -> bool:
        """Submit email/SMS verification PIN code to pass LinkedIn security checkpoint."""
        try:
            await self.ensure_active_page()
            if not self.page:
                return False
            pin = str(pin_code).strip()
            print(f"[Submit PIN] Submitting verification code: {pin}")
            pin_selectors = [
                '#input__email_verification_pin',
                'input[name="pin"]',
                'input[name="verificationCode"]',
                'input[id*="pin"]',
                'input[id*="code"]',
                'input[type="text"]',
                'input[type="number"]'
            ]
            filled = False
            for sel in pin_selectors:
                try:
                    if await self.page.is_visible(sel):
                        await self.page.fill(sel, pin)
                        filled = True
                        await asyncio.sleep(1)
                        submit_btn = await self.page.query_selector('button[type="submit"], #email-verification-submit-button, button[id*="submit"], input[type="submit"]')
                        if submit_btn:
                            await submit_btn.click()
                        else:
                            await self.page.keyboard.press('Enter')
                        await asyncio.sleep(4)
                        break
                except Exception:
                    pass
            if not filled:
                try:
                    await self.page.keyboard.type(pin)
                    await self.page.keyboard.press('Enter')
                    await asyncio.sleep(4)
                except Exception:
                    pass

            base_url = self.page.url.split('?')[0].rstrip('/')
            if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                self.is_authenticated = True
                self.verification_required = False
                print("[Submit PIN] Verification successful! Feed page loaded.")
                return True
            else:
                print(f"[Submit PIN] Page after submission: {self.page.url}")
        except Exception as ex:
            print(f"[Submit PIN] Exception submitting PIN: {ex}")
        return False

    # Login method (if not already authenticated)
    async def login(self, email: str = "uov.agri.faculty@gmail.com", password: str = "Hello@2026", li_at: str = None) -> bool:
        email = email or os.environ.get('LINKEDIN_EMAIL', "uov.agri.faculty@gmail.com")
        password = password or os.environ.get('LINKEDIN_PASSWORD', "Hello@2026")
        li_at_env = li_at or os.environ.get('LINKEDIN_LI_AT') or os.environ.get('LI_AT')
        
        # 1. Try session cookie bypass if li_at cookie is available in env or args
        if li_at_env:
            print("[Login] Attempting session cookie (li_at) bypass...")
            cookie_ok = await self.login_with_cookie(li_at_env)
            if cookie_ok:
                # Validate the cookie actually works against LinkedIn
                try:
                    await self.page.goto('https://www.linkedin.com/feed/', wait_until='commit', timeout=15000)
                    await asyncio.sleep(2)
                    cur_url = self.page.url
                    if not cur_url.startswith("chrome-error://") and not any(bad in cur_url for bad in ['login', 'authwall', 'uas/authenticate']):
                        self.is_authenticated = True
                        print("[Login] Session cookie verified successfully!")
                        return True
                    else:
                        print(f"[Login] Session cookie invalid (landed on {cur_url}). Falling back to credentials...")
                        self.is_authenticated = False
                        self._li_at_injected = False
                except Exception as ce:
                    print(f"[Login] Cookie verification exception ({ce}). Falling back to credentials...")
                    self.is_authenticated = False
                    self._li_at_injected = False

        if self.is_authenticated:
            return True

        await self.ensure_active_page()
        try:
            await self.page.goto('https://www.linkedin.com/login', wait_until='domcontentloaded', timeout=30000)
        except Exception:
            pass
        await asyncio.sleep(2)
        
        base_url = self.page.url.split('?')[0].rstrip('/')
        if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
            self.is_authenticated = True
            self.verification_required = False
            print("[Login] Already logged into LinkedIn feed.")
            return True
        if 'checkpoint' in base_url or 'challenge' in base_url:
            self.verification_required = True
            print(f"[Login] Redirected to security checkpoint / 2FA screen: {self.page.url}")
            return False

        # Fill login form with multi-selector fallback
        try:
            user_selectors = ['#username', 'input[name="session_key"]', 'input[id*="username"]', 'input[type="text"]', 'input[type="email"]']
            pass_selectors = ['#password', 'input[name="session_password"]', 'input[id*="password"]', 'input[type="password"]']

            try:
                await self.page.wait_for_selector(', '.join(user_selectors), timeout=10000)
            except Exception:
                pass

            user_filled = False
            for us in user_selectors:
                try:
                    el = await self.page.query_selector(us)
                    if el:
                        await el.fill(email)
                        user_filled = True
                        break
                except Exception:
                    pass
                    
            pass_filled = False
            for ps in pass_selectors:
                try:
                    el = await self.page.query_selector(ps)
                    if el:
                        await el.fill(password)
                        pass_filled = True
                        break
                except Exception:
                    pass

            if user_filled and pass_filled:
                submit_selectors = ['button[type="submit"]', 'button[data-litms-control-urn*="login-submit"]', '.btn__primary--large', '#login-submit']
                submitted = False
                for ss in submit_selectors:
                    try:
                        if await self.page.is_visible(ss):
                            await self.page.click(ss)
                            submitted = True
                            break
                    except Exception:
                        pass
                if not submitted:
                    await self.page.keyboard.press('Enter')
            else:
                print(f"[Login] Notice: Form inputs not found (user={user_filled}, pass={pass_filled}) on {self.page.url}")

        except Exception as fill_err:
            base_url = self.page.url.split('?')[0].rstrip('/')
            if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                self.is_authenticated = True
                self.verification_required = False
                return True
            if 'checkpoint' in base_url or 'challenge' in base_url:
                self.verification_required = True
                print(f"[Login] Form fill notice (on checkpoint page): {self.page.url}")
                return False
            print(f"[Login] Form fill exception: {fill_err}")

        print("Waiting for login redirect to feed (up to 120s for CAPTCHA/2FA/verification)...")
        for _ in range(60):
            await asyncio.sleep(2)
            base_url = self.page.url.split('?')[0].rstrip('/')
            if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                self.is_authenticated = True
                self.verification_required = False
                print("Login successful (feed page loaded)!")
                return True
            elif 'checkpoint' in base_url or 'challenge' in base_url:
                self.verification_required = True
                print(f"[Login] Email verification checkpoint detected! URL: {self.page.url}")

        base_url = self.page.url.split('?')[0].rstrip('/')
        if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
            self.is_authenticated = True
            self.verification_required = False
            return True
        if 'checkpoint' in base_url or 'challenge' in base_url:
            self.verification_required = True
            print("[Login] Stuck on verification checkpoint. PIN entry or li_at cookie bypass required.")
        print("Login timeout or failed.")
        return False


    # ── Core profile extraction ─────────────────────────────────────────────
    async def extract_profile(self, profile_url: str, _retry: int = 0) -> Dict:
        MAX_RETRIES = 2
        print(f"Extracting: {profile_url}" + (f" (retry {_retry})" if _retry else ""))
        try:
            await self.ensure_active_page()

            # Normalize and identify target slug to guard against stray redirects
            target_slug = profile_url.rstrip('/').split('/in/')[-1].split('?')[0].lower() if '/in/' in profile_url else ''

            # Step 1: Load main profile page
            nav_ok = False
            for wait_mode in ('domcontentloaded', 'commit'):
                try:
                    await self.page.goto(profile_url, wait_until=wait_mode, timeout=45000)
                    nav_ok = True
                    break
                except Exception as ge:
                    ge_str = str(ge)
                    print(f"Navigation notice for {profile_url} ({wait_mode}): {ge_str[:120]}")
                    if self.page.is_closed() or any(k in ge_str.lower() for k in ["closed", "target", "context"]):
                        raise ge
                    if "redirect" in ge_str.lower() or "timeout" in ge_str.lower():
                        continue
                    break

            await asyncio.sleep(2.5)

            # Verify we landed on a valid page, not an authwall or error
            try:
                current_url = self.page.url
                if current_url.startswith("chrome-error://") or not nav_ok:
                    print(f"[Extract] Navigation landed on error page: {current_url}.")
                    return {
                        "error": f"LinkedIn navigation failed for {profile_url}. Check connection or cookie."
                    }
                if any(bad in current_url for bad in ['authwall', 'login', 'checkpoint', 'uas/authenticate']):
                    print(f"[Extract] Redirected to auth wall: {current_url}.")
                    return {
                        "error": f"LinkedIn redirected to login/authwall. Session cookie may be expired. URL: {current_url}"
                    }
            except Exception:
                pass

            try:
                await self.page.wait_for_selector('h1', timeout=10000)
            except Exception:
                await asyncio.sleep(2)

            # Step 2: Scroll to trigger lazy-loading of all main page sections
            for _ in range(8):
                try:
                    await self.page.evaluate('window.scrollBy(0, 600)')
                except Exception:
                    pass
                await asyncio.sleep(0.4)
            await asyncio.sleep(1)

            # Step 3: Click expand buttons on main page
            expand_selectors = [
                'button[aria-label*="Show all"]',
                'button[aria-label*="See more"]',
                'button.inline-show-more-text__button',
                'span.see-more-button button',
                'a.optional-action-on-hide-show__button',
            ]
            for sel in expand_selectors:
                try:
                    buttons = await self.page.query_selector_all(sel)
                    for btn in buttons:
                        try:
                            await btn.click()
                            await asyncio.sleep(0.3)
                        except Exception:
                            pass
                except Exception:
                    pass
            await asyncio.sleep(0.8)

            # Step 4: Extract rich basic info and all visible section texts directly from main page DOM
            dom_data = await self.page.evaluate('''() => {
                const data = {
                    name: '', headline: '', tagline: '', location: '',
                    profile_picture: '', connections: '', followers: '',
                    page_title: document.title || '',
                    about: '', is_premium: false,
                    exp_text: '', edu_text: '', skill_text: '',
                    cert_text: '', lang_text: '', vol_text: '',
                    hon_text: '', rec_text: '',
                    has_more_exp: false, has_more_edu: false, has_more_skills: false,
                    contact_info: {}
                };

                // Name
                const nameEls = ['h1', '.text-heading-xlarge', '.pv-top-card--list li:first-child'];
                for (const sel of nameEls) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim()) { data.name = el.innerText.trim(); break; }
                }

                // Headline / Tagline
                const hlEls = ['.text-body-medium', '.pv-text-details__left-panel .text-body-medium', '.text-heading-medium'];
                for (const sel of hlEls) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim()) {
                        data.headline = el.innerText.trim();
                        data.tagline = el.innerText.trim();
                        break;
                    }
                }

                // Location
                const locEls = ['.text-body-small.inline.t-black--light', '.pv-text-details__left-panel span.text-body-small'];
                for (const sel of locEls) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim()) { data.location = el.innerText.trim(); break; }
                }

                // Profile picture
                const imgEls = ['img.pv-top-card-profile-picture__image', '.pv-top-card-profile-picture img', '.pv-top-card__photo img', 'img[alt*="profile photo" i]', 'img[alt*="profile picture" i]', 'img[src*="licdn.com/dms/image/"]', 'img.presence-entity__image'];
                for (const sel of imgEls) {
                    const el = document.querySelector(sel);
                    if (el && el.src) { data.profile_picture = el.src; break; }
                }

                // Connections & Followers
                const spanEls = document.querySelectorAll('span.t-bold, ul.pv-top-card--list-bullet li, li.text-body-small span, span');
                for (const s of spanEls) {
                    const txt = (s.innerText || '').trim();
                    const pTxt = (s.parentElement?.innerText || s.innerText || '').trim();
                    if (!data.connections && (/connection/i.test(pTxt) || /connection/i.test(txt))) {
                        data.connections = pTxt || txt;
                    }
                    if (!data.followers && (/follower/i.test(pTxt) || /follower/i.test(txt))) {
                        data.followers = pTxt || txt;
                    }
                }

                // About section
                const aboutSec = document.querySelector('section[data-section="about"], #about ~ div, div[id="about"]');
                if (aboutSec) {
                    const btn = aboutSec.querySelector('button, .inline-show-more-text__button, span.see-more-button button');
                    if (btn) { try { btn.click(); } catch(e) {} }
                    const textSpans = aboutSec.querySelectorAll('.display-flex span[aria-hidden="true"], .pv-shared-text-with-see-more span');
                    if (textSpans.length > 0) {
                        data.about = Array.from(textSpans).map(s => s.innerText.trim()).filter(t => t.length > 0).join('\\n');
                    } else {
                        data.about = aboutSec.innerText.trim();
                    }
                }

                // Premium Badge Detection
                let isPremium = false;
                const premiumSelectors = [
                    '.pv-member-badge--premium',
                    'svg.premium-icon',
                    '[data-test-premium-icon]',
                    '[aria-label*="Premium member" i]',
                    '[aria-label*="Premium subscriber" i]',
                    '.pv-top-card__badge--premium',
                    'svg[data-test-icon="premium-gold-icon"]',
                    '.premium-icon',
                    'span.premium-badge'
                ];
                for (const sel of premiumSelectors) {
                    if (document.querySelector(sel)) {
                        isPremium = true;
                        break;
                    }
                }
                if (!isPremium) {
                    const bodyText = document.body ? document.body.innerText : '';
                    if (bodyText.includes('Premium subscriber') || bodyText.includes('Premium member') || bodyText.includes('LinkedIn Premium')) {
                        isPremium = true;
                    }
                }
                data.is_premium = isPremium;

                // Section text helper
                function getSectionContent(selectors) {
                    for (const sel of selectors) {
                        const sec = document.querySelector(sel);
                        if (sec) {
                            const items = sec.querySelectorAll('li.artdeco-list__item, li.pvs-list__paged-list-item, div.pvs-entity');
                            if (items.length > 0) {
                                return Array.from(items).map(li => li.innerText.trim()).filter(t => t.length > 0).join('\\n---\\n');
                            }
                            return sec.innerText.trim();
                        }
                    }
                    return '';
                }

                data.exp_text   = getSectionContent(['section[data-section="experience"]', '#experience ~ div', 'div[id="experience"]']);
                data.edu_text   = getSectionContent(['section[data-section="education"]', '#education ~ div', 'div[id="education"]']);
                data.skill_text = getSectionContent(['section[data-section="skills"]', '#skills ~ div', 'div[id="skills"]']);
                data.cert_text  = getSectionContent(['section[data-section="certifications"]', '#certifications ~ div', '#licenses_and_certifications ~ div']);
                data.lang_text  = getSectionContent(['section[data-section="languages"]', '#languages ~ div']);
                data.vol_text   = getSectionContent(['section[data-section="volunteer"]', '#volunteering_experience ~ div']);
                data.hon_text   = getSectionContent(['section[data-section="honors"]', '#honors_and_awards ~ div']);
                data.rec_text   = getSectionContent(['section[data-section="recommendations"]', '#recommendations ~ div']);

                // Check for "Show all" links to know if detail subpage is worth fetching
                data.has_more_exp    = !!document.querySelector('a[href*="/details/experience"]');
                data.has_more_edu    = !!document.querySelector('a[href*="/details/education"]');
                data.has_more_skills = !!document.querySelector('a[href*="/details/skills"]');

                return data;
            }''')

            name = dom_data.get('name', '')
            if not name and dom_data.get('page_title'):
                title = dom_data['page_title']
                if ' - ' in title:
                    name = title.split(' - ')[0].strip()
                elif ' | ' in title:
                    name = title.split(' | ')[0].strip()

            detail_texts: Dict[str, str] = {
                'experience': dom_data.get('exp_text', ''),
                'education': dom_data.get('edu_text', ''),
                'skills': dom_data.get('skill_text', ''),
                'certifications': dom_data.get('cert_text', ''),
                'languages': dom_data.get('lang_text', ''),
                'volunteer': dom_data.get('vol_text', ''),
                'honors': dom_data.get('hon_text', ''),
                'recommendations': dom_data.get('rec_text', ''),
            }
            contact_info: Dict[str, str] = dom_data.get('contact_info', {})

            # Step 5: Safe targeted detail subpages visit ONLY if "Show all" was found and section is truncated
            base_url = profile_url.rstrip('/')
            subpages_to_check = []
            if dom_data.get('has_more_exp'):
                subpages_to_check.append(('experience', f"{base_url}/details/experience/"))
            if dom_data.get('has_more_edu'):
                subpages_to_check.append(('education', f"{base_url}/details/education/"))
            if dom_data.get('has_more_skills'):
                subpages_to_check.append(('skills', f"{base_url}/details/skills/"))

            for section, url in subpages_to_check:
                try:
                    await self.page.goto(url, wait_until='domcontentloaded', timeout=20000)
                    await asyncio.sleep(1.5)

                    # Guard: verify page hasn't redirected to an authwall, feed, or a different profile
                    current_sub_url = self.page.url.lower()
                    if target_slug and target_slug not in current_sub_url:
                        print(f"[Extract] Detail page {section} redirected away from target ({current_sub_url}). Skipping subpage.")
                        break

                    page_text = await self.page.evaluate('''() => {
                        const main = document.querySelector('main, [role="main"], .scaffold-layout__main');
                        if (main) {
                            const items = main.querySelectorAll('li.pvs-list__paged-list-item, li.artdeco-list__item');
                            if (items.length > 0) {
                                return Array.from(items).map(li => li.innerText.trim()).join('\\n---\\n');
                            }
                            return main.innerText.trim();
                        }
                        return "";
                    }''')
                    if page_text and len(page_text) > len(detail_texts.get(section, '')):
                        detail_texts[section] = page_text
                except Exception as de:
                    print(f"[Extract] Notice visiting detail page {section}: {de}")
                    pass

            # Step 6: Parse each section cleanly
            about = dom_data.get('about', '').strip()
            if not about:
                main_text_for_about = await self.page.evaluate('() => document.body.innerText || ""')
                clean_main = self._strip_posts(main_text_for_about)
                about = self._parse_about(clean_main)

            exp_text   = detail_texts.get('experience', '')
            edu_text   = detail_texts.get('education', '')
            cert_text  = detail_texts.get('certifications', '')
            skill_text = detail_texts.get('skills', '')
            lang_text  = detail_texts.get('languages', '')
            vol_text   = detail_texts.get('volunteer', '')
            hon_text   = detail_texts.get('honors', '')
            rec_text   = detail_texts.get('recommendations', '')

            current_job     = self._parse_experience(exp_text)
            experience      = self._parse_all_experiences(exp_text)
            qualifications  = self._parse_education(edu_text)
            certifications  = self._parse_certifications(cert_text)
            skills          = self._parse_skills(skill_text)
            languages       = self._parse_languages(lang_text)
            volunteer       = self._parse_volunteer(vol_text)
            honors          = self._parse_honors(hon_text)
            recommendations = self._parse_recommendations(rec_text)

            connections = dom_data.get('connections', '')

            # Step 7: Navigate back to profile
            try:
                await self.page.goto(profile_url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(2)
            except:
                pass

            self.stats['profiles_scraped'] += 1
            is_prem = bool(dom_data.get('is_premium', False))
            result = {
                'name': name,
                'headline': dom_data.get('headline', ''),
                'location': dom_data.get('location', ''),
                'connections': connections,
                'profile_picture': dom_data.get('profile_picture', ''),
                'about': about,
                'is_premium': is_prem,
                'current_job': current_job,
                'experience': experience,
                'qualifications': qualifications,
                'certifications': certifications,
                'skills': skills,
                'languages': languages,
                'volunteer': volunteer,
                'honors': honors,
                'recommendations': recommendations,
                'contact_info': contact_info,
                'profile_url': profile_url,
                'scraped_at': datetime.now().isoformat()
            }
            found = []
            if is_prem: found.append('⭐ Premium Account')
            if about: found.append('about')
            if current_job.get('title'): found.append('job')
            if experience: found.append(f'{len(experience)} exp')
            if qualifications: found.append(f'{len(qualifications)} edu')
            if certifications: found.append(f'{len(certifications)} certs')
            if skills: found.append(f'{len(skills)} skills')
            if languages: found.append(f'{len(languages)} langs')
            if volunteer: found.append(f'{len(volunteer)} volunteer')
            if honors: found.append(f'{len(honors)} honors')
            if recommendations: found.append(f'{len(recommendations)} recs')
            if contact_info: found.append('contact info')
            print(f"Success: Extracted: {name or 'Unknown'} | Found: {', '.join(found) or 'basic info only'}")
            return self.sanitize_profile(result)

        except Exception as e:
            err_msg = str(e)
            print(f"Extraction error: {err_msg}")
            if _retry < MAX_RETRIES and any(k in err_msg.lower() for k in ['context', 'navigation', 'closed', 'target', 'crashed']):
                print(f"Browser context/page issue detected. Re-initializing page and retrying ({_retry + 1}/{MAX_RETRIES})...")
                await asyncio.sleep(2)
                await self.ensure_active_page()
                return await self.extract_profile(profile_url, _retry=_retry + 1)
            self.stats['errors'] += 1
            return {'profile_url': profile_url, 'error': err_msg}

    async def extract_contact_info(self, profile_url: str) -> Dict[str, Any]:
        """Navigate to contact-info overlay/modal and extract structured contact info."""
        try:
            await self.ensure_active_page()
            base_url = profile_url.rstrip('/')
            contact_url = f"{base_url}/overlay/contact-info/"
            try:
                await self.page.goto(contact_url, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(2)

            contact_data = await self.page.evaluate('''() => {
                const data = {};
                const sections = document.querySelectorAll('section.pv-contact-info__contact-type, div.pv-profile-section__section-info, [data-view-name="profile-contact-info"]');
                for (const sec of sections) {
                    const header = sec.querySelector('h3, h4');
                    if (!header) continue;
                    const key = header.innerText.trim().toLowerCase();
                    const vals = Array.from(sec.querySelectorAll('.pv-contact-info__ci-container, a, span.t-14, div.t-14')).map(el => el.innerText.trim()).filter(t => t.length > 0 && t !== header.innerText.trim());
                    if (vals.length > 0) {
                        data[key] = Array.from(new Set(vals)).join(', ');
                    }
                }
                const text = document.body ? document.body.innerText : '';
                const emailMatch = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                if (emailMatch && !data['email']) {
                    data['email'] = emailMatch[0];
                }
                return data;
            }''')
            return contact_data or {}
        except Exception as e:
            print(f"Error extracting contact info: {e}")
            return {}

    # ── Text cleaning helpers ───────────────────────────────────────────────

    def _clean_lines(self, text: str) -> List[str]:
        """Split text into lines, removing empty lines, consecutive duplicates, and known UI noise."""
        result = []
        last = None
        for line in text.split('\n'):
            s = line.strip()
            if s and not _is_noise(s):
                if s != last:
                    result.append(s)
                    last = s
        return result

    def _strip_posts(self, text: str) -> str:
        """Remove Activity/posts sections and People-also-viewed sidebars."""
        lines = text.split('\n')
        clean = []
        skip_markers = [
            'Activity', 'Suggested for you', 'People also viewed',
            'People you may know', 'More profiles for you',
        ]
        resume_markers = [
            'Experience', 'Education', 'Licenses & certifications',
            'Skills', 'Honors & awards', 'Recommendations',
            'Languages', 'Volunteer experience', 'About',
        ]
        skipping = False
        for line in lines:
            stripped = line.strip()
            if stripped in skip_markers:
                skipping = True
                continue
            if skipping and stripped in resume_markers:
                skipping = False
            if not skipping:
                clean.append(line)
        return '\n'.join(clean)

    def _parse_about(self, text: str) -> str:
        """Parse About section from main page text as a fallback."""
        lines = text.split('\n')
        capturing = False
        captured = []
        end_markers = {
            'Experience', 'Activity', 'Education', 'Skills', 'Interests',
            'Languages', 'Featured', 'Licenses & certifications',
            'Volunteer experience', 'Projects', 'Publications', 'Courses',
            'Honors & awards', 'Recommendations',
        }
        for line in lines:
            s = line.strip()
            if not capturing:
                if s == 'About':
                    capturing = True
                    continue
            else:
                if s in end_markers:
                    break
                if s and not _is_noise(s):
                    s_clean = s.replace('… more', '').replace('...more', '').replace('more...', '').replace('…', '').strip()
                    if s_clean and s_clean.lower() not in ('about', 'see more', 'show more'):
                        captured.append(s_clean)
        res = '\n'.join(captured).strip()
        for junk in ['… more', '...more', '... more', '…more', 'more...', '... see more', 'see more', '…']:
            if res.endswith(junk):
                res = res[:-len(junk)].strip()
        return res

    # ── Section parsers ─────────────────────────────────────────────────────

    def _parse_experience(self, text: str) -> Dict:
        """Parse the most-recent (current) job from experience detail text."""
        entries = self._parse_all_experiences(text)
        return entries[0] if entries else {}

    def _parse_all_experiences(self, text: str, max_entries: int = 20) -> List[Dict]:
        """
        Parse all experience entries from detail-page text.

        Strategy: clean lines, find the section start, then group consecutive
        non-noise lines into entries.  An entry boundary is detected when we
        see a line that looks like a duration / date range, which always
        appears before the next title.
        """
        if not text:
            return []

        lines = self._clean_lines(text)
        # Find where the Experience section begins
        start = -1
        for i, l in enumerate(lines):
            if l.strip() in ('Experience', 'Experiences'):
                start = i + 1
                break
        if start == -1:
            start = 0

        section_end_markers = {
            'Education', 'Licenses & certifications', 'Skills', 'Interests',
            'Activity', 'Recommendations', 'Honors & awards', 'Languages',
            'Volunteer experience', 'Projects', 'Publications', 'Certifications',
        }

        raw_lines = []
        for l in lines[start:]:
            if l in section_end_markers:
                break
            raw_lines.append(l)

        if not raw_lines:
            return []

        # Group into entries — each entry: title, company, duration, location, description
        entries = []
        i = 0
        while i < len(raw_lines) and len(entries) < max_entries:
            title = raw_lines[i]
            i += 1
            company = duration = location = ''

            if i < len(raw_lines) and not _looks_like_duration(raw_lines[i]):
                company = raw_lines[i]
                i += 1

            if i < len(raw_lines) and _looks_like_duration(raw_lines[i]):
                duration = raw_lines[i]
                i += 1

            # Optional location line (doesn't look like a date/duration or the next job title)
            if i < len(raw_lines):
                nxt = raw_lines[i]
                if not _looks_like_duration(nxt) and len(nxt) < 80:
                    # Peek ahead: if what follows is a duration, this is a location
                    if (i + 1 < len(raw_lines) and _looks_like_duration(raw_lines[i + 1])) or \
                       (i + 1 >= len(raw_lines)):
                        location = nxt
                        i += 1

            # Skip any remaining description lines until next "title" candidate
            # (We skip long description text — it's rarely structured)
            while i < len(raw_lines):
                nxt = raw_lines[i]
                if _looks_like_duration(nxt):
                    i += 1  # skip stray duration lines
                    continue
                # If next line could be a new job title (short, not a duration), stop
                if len(nxt) < 120 and not _looks_like_duration(nxt):
                    break
                i += 1  # skip long description text

            if title:
                entries.append({
                    'title': title,
                    'company': company,
                    'duration': duration,
                    'location': location,
                })

        return entries

    def _parse_education(self, text: str, max_entries: int = 15) -> List[Dict]:
        """
        Parse education entries from detail-page text.
        Each entry: institution, degree, dates.
        """
        if not text:
            return []

        lines = self._clean_lines(text)
        start = -1
        for i, l in enumerate(lines):
            if l.strip() == 'Education':
                start = i + 1
                break
        if start == -1:
            start = 0

        section_end_markers = {
            'Licenses & certifications', 'Skills', 'Interests', 'Activity',
            'Recommendations', 'Experience', 'Honors & awards', 'Languages',
            'Volunteer experience', 'Projects', 'Publications',
        }
        raw_lines = []
        for l in lines[start:]:
            if l in section_end_markers:
                break
            raw_lines.append(l)

        entries = []
        i = 0
        while i < len(raw_lines) and len(entries) < max_entries:
            institution = raw_lines[i]
            i += 1
            degree = dates = ''

            # Next line: degree (if it doesn't look like a date)
            if i < len(raw_lines) and not _looks_like_duration(raw_lines[i]):
                degree = raw_lines[i]
                i += 1

            # Next line: dates
            if i < len(raw_lines) and _looks_like_duration(raw_lines[i]):
                dates = raw_lines[i]
                i += 1

            # Skip optional activities/grade lines until next institution
            while i < len(raw_lines) and _looks_like_duration(raw_lines[i]):
                i += 1

            if institution:
                entries.append({'institution': institution, 'degree': degree, 'dates': dates})

        return entries

    def _parse_certifications(self, text: str, max_entries: int = 20) -> List[Dict]:
        """
        Parse certification entries. Each entry: name, issuer, date.
        """
        if not text:
            return []

        lines = self._clean_lines(text)
        start = -1
        for i, l in enumerate(lines):
            if l in ('Licenses & certifications', 'Licenses and certifications', 'Certifications'):
                start = i + 1
                break
        if start == -1:
            start = 0

        section_end_markers = {
            'Skills', 'Interests', 'Activity', 'Recommendations', 'Education',
            'Experience', 'Honors & awards', 'Languages', 'Volunteer experience',
        }
        raw_lines = []
        for l in lines[start:]:
            if l in section_end_markers:
                break
            raw_lines.append(l)

        entries = []
        i = 0
        while i < len(raw_lines) and len(entries) < max_entries:
            name = raw_lines[i]
            i += 1
            issuer = date = ''

            if i < len(raw_lines) and not _looks_like_duration(raw_lines[i]):
                issuer = raw_lines[i]
                i += 1

            if i < len(raw_lines) and _looks_like_duration(raw_lines[i]):
                date = raw_lines[i]
                i += 1

            # Skip any extra metadata lines (credential ID, URL)
            while i < len(raw_lines) and _looks_like_duration(raw_lines[i]):
                i += 1

            if name:
                entries.append({'name': name, 'issuer': issuer, 'date': date})

        return entries

    def _parse_skills(self, text: str, max_entries: int = 30) -> List[Dict]:
        """
        Parse skills. LinkedIn's skills page lists:
          <Skill name>
          [optional: <N> endorsements]
          [optional: Top skill / category header — skip]
        """
        if not text:
            return []

        lines = self._clean_lines(text)
        start = -1
        for i, l in enumerate(lines):
            if l.strip() in ('Skills', 'Top skills'):
                start = i + 1
                break
        if start == -1:
            start = 0

        section_end_markers = {
            'Interests', 'Activity', 'Recommendations', 'Education', 'Experience',
            'Licenses & certifications', 'Languages', 'Volunteer experience',
            'Honors & awards', 'Publications', 'Projects',
        }

        # Known category headers in the skills detail page
        _SKILL_CATEGORY_HEADERS = {
            'Industry Knowledge', 'Tools & Technologies', 'Interpersonal Skills',
            'Other Skills', 'Top skills',
        }

        raw_lines = []
        for l in lines[start:]:
            if l in section_end_markers:
                break
            if l in _SKILL_CATEGORY_HEADERS:
                continue  # skip category headers
            raw_lines.append(l)

        entries = []
        i = 0
        while i < len(raw_lines) and len(entries) < max_entries:
            skill_name = raw_lines[i]
            i += 1
            endorsements = ''

            if i < len(raw_lines):
                nxt = raw_lines[i]
                if re.match(r'^\d+\s+endorsement', nxt, re.I):
                    endorsements = nxt
                    i += 1
                elif 'endorsement' in nxt.lower():
                    endorsements = nxt
                    i += 1

            # Skip "Endorsed by …" lines
            while i < len(raw_lines) and raw_lines[i].lower().startswith('endorsed by'):
                i += 1

            if skill_name and len(skill_name) < 80:
                entries.append({'skill': skill_name, 'endorsements': endorsements})

        return entries

    def _parse_languages(self, text: str, max_entries: int = 15) -> List[Dict]:
        """
        Parse languages. Each entry: language name, optional proficiency level.
        """
        if not text:
            return []

        lines = self._clean_lines(text)
        start = -1
        for i, l in enumerate(lines):
            if l.strip() == 'Languages':
                start = i + 1
                break
        if start == -1:
            start = 0

        section_end_markers = {
            'Interests', 'Activity', 'Recommendations', 'Skills', 'Experience',
            'Education', 'Volunteer experience', 'Honors & awards',
            'Licenses & certifications', 'Publications', 'Projects',
        }
        raw_lines = []
        for l in lines[start:]:
            if l in section_end_markers:
                break
            raw_lines.append(l)

        entries = []
        i = 0
        while i < len(raw_lines) and len(entries) < max_entries:
            lang = raw_lines[i]
            i += 1
            proficiency = ''

            if i < len(raw_lines) and _looks_like_proficiency(raw_lines[i]):
                proficiency = raw_lines[i]
                i += 1

            # Only accept lines that look like actual language names
            # (short, mostly alphabetical, not a duration or number, and is a real human language)
            if lang and len(lang) < 60 and not _looks_like_duration(lang) and not lang.isdigit():
                if _is_real_language(lang):
                    entries.append({'language': lang, 'proficiency': proficiency})

        return entries

    def _parse_volunteer(self, text: str, max_entries: int = 15) -> List[Dict]:
        """
        Parse volunteer experience. Each entry: role, organization, duration.
        """
        if not text:
            return []

        lines = self._clean_lines(text)
        start = -1
        for i, l in enumerate(lines):
            if l.strip() in ('Volunteer experience', 'Volunteer', 'Volunteering'):
                start = i + 1
                break
        if start == -1:
            start = 0

        section_end_markers = {
            'Skills', 'Interests', 'Activity', 'Recommendations', 'Education',
            'Experience', 'Licenses & certifications', 'Languages',
            'Honors & awards', 'Publications', 'Projects',
        }
        raw_lines = []
        for l in lines[start:]:
            if l in section_end_markers:
                break
            raw_lines.append(l)

        entries = []
        i = 0
        while i < len(raw_lines) and len(entries) < max_entries:
            role = raw_lines[i]
            i += 1
            organization = duration = ''

            if i < len(raw_lines) and not _looks_like_duration(raw_lines[i]):
                organization = raw_lines[i]
                i += 1

            if i < len(raw_lines) and _looks_like_duration(raw_lines[i]):
                duration = raw_lines[i]
                i += 1

            # Skip description lines
            while i < len(raw_lines) and len(raw_lines[i]) > 80:
                i += 1

            if role:
                entries.append({'role': role, 'organization': organization, 'duration': duration})

        return entries

    def _parse_honors(self, text: str, max_entries: int = 15) -> List[Dict]:
        """
        Parse honors & awards. Each entry: title, issuer, date.
        """
        if not text:
            return []

        lines = self._clean_lines(text)
        start = -1
        for i, l in enumerate(lines):
            if l.strip() in ('Honors & awards', 'Honors and Awards'):
                start = i + 1
                break
        if start == -1:
            start = 0

        section_end_markers = {
            'Skills', 'Interests', 'Activity', 'Recommendations', 'Education',
            'Experience', 'Licenses & certifications', 'Languages',
            'Volunteer experience', 'Publications', 'Projects',
        }
        raw_lines = []
        for l in lines[start:]:
            if l in section_end_markers:
                break
            raw_lines.append(l)

        entries = []
        i = 0
        while i < len(raw_lines) and len(entries) < max_entries:
            title = raw_lines[i]
            i += 1
            issuer = date = ''

            if i < len(raw_lines) and not _looks_like_duration(raw_lines[i]):
                issuer = raw_lines[i]
                i += 1

            if i < len(raw_lines) and _looks_like_duration(raw_lines[i]):
                date = raw_lines[i]
                i += 1

            # Skip description lines
            while i < len(raw_lines) and len(raw_lines[i]) > 100:
                i += 1

            if title:
                entries.append({'title': title, 'issuer': issuer, 'date': date})

        return entries

    def _parse_recommendations(self, text: str, max_entries: int = 15) -> List[Dict]:
        """
        Parse recommendations. Each entry: recommender, title/relationship, text snippet.
        LinkedIn's recommendations detail page groups 'Received' and 'Given' tabs.
        We only capture 'Received' recommendations.
        """
        if not text:
            return []

        lines = self._clean_lines(text)

        # Find 'Received' tab section if present, otherwise use all lines
        received_start = -1
        given_start = -1
        for i, l in enumerate(lines):
            if l.strip() == 'Received':
                received_start = i + 1
            elif l.strip() == 'Given':
                given_start = i
                break

        if received_start != -1:
            end = given_start if given_start != -1 else len(lines)
            raw_lines = lines[received_start:end]
        else:
            # Fallback: find 'Recommendations' header
            start = 0
            for i, l in enumerate(lines):
                if l.strip() == 'Recommendations':
                    start = i + 1
                    break
            raw_lines = lines[start:]

        section_end_markers = {
            'Skills', 'Interests', 'Activity', 'Education', 'Experience',
            'Licenses & certifications', 'Languages', 'Volunteer experience',
            'Honors & awards', 'Publications', 'Projects',
        }

        clean_lines = []
        for l in raw_lines:
            if l in section_end_markers:
                break
            clean_lines.append(l)

        entries = []
        i = 0
        while i < len(clean_lines) and len(entries) < max_entries:
            recommender = clean_lines[i]
            i += 1
            title = rec_text = ''

            # Next line: relationship / job title of recommender (short, no date)
            if i < len(clean_lines) and not _looks_like_duration(clean_lines[i]) and len(clean_lines[i]) < 120:
                title = clean_lines[i]
                i += 1

            # Skip date line
            if i < len(clean_lines) and _looks_like_duration(clean_lines[i]):
                i += 1

            # Collect recommendation text (one or more longer lines)
            text_parts = []
            while i < len(clean_lines) and len(clean_lines[i]) > 30:
                text_parts.append(clean_lines[i])
                i += 1
                # Stop if next line looks like a new recommender name
                if i < len(clean_lines) and len(clean_lines[i]) < 60 and \
                   not _looks_like_duration(clean_lines[i]):
                    break
            rec_text = ' '.join(text_parts)

            if recommender and len(recommender) < 80:
                entries.append({
                    'recommender': recommender,
                    'title': title,
                    'text': rec_text[:500],  # cap recommendation text length
                })

        return entries

    # ── Search methods ──────────────────────────────────────────────────────

    async def search_people(self, first_name: str, last_name: str, company: str = "",
                             max_results: int = 10, force_search: bool = False, _retry: int = 0) -> List[Dict]:
        MAX_RETRIES = 2
        try:
            await self.ensure_active_page()
            if not self.is_authenticated:
                raise Exception("Not authenticated")
            query = " ".join(filter(None, [first_name, last_name, company]))
            if not query:
                return []
            import urllib.parse
            encoded = urllib.parse.quote(query)
            url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
            for wait_mode in ('domcontentloaded', 'commit'):
                try:
                    await self.page.goto(url, wait_until=wait_mode, timeout=45000)
                    break
                except Exception as e:
                    e_str = str(e)
                    print(f"Warning: Search page navigation error ({wait_mode}): {e_str[:120]}")
                    if self.page.is_closed() or any(k in e_str.lower() for k in ["closed", "target", "context"]):
                        raise e
                    if "redirect" in e_str.lower() or "timeout" in e_str.lower():
                        continue
                    print("Attempting to parse elements anyway...")
                    break

            # If redirected to authwall, return empty immediately
            try:
                current_url = self.page.url
                if any(bad in current_url for bad in ['authwall', 'login', 'checkpoint', 'uas/authenticate']):
                    print(f"[Search] Redirected to auth wall: {current_url}. Returning empty results.")
                    return []
            except Exception:
                pass

            await asyncio.sleep(3)

            for _ in range(4):
                try:
                    await self.page.evaluate('window.scrollBy(0, 800)')
                except Exception as se:
                    if self.page.is_closed() or any(k in str(se).lower() for k in ["closed", "target", "context"]):
                        raise se
                await asyncio.sleep(1)

            try:
                html_content = await self.page.content()
                with open("search_debug.html", "w", encoding="utf-8") as f:
                    f.write(html_content)
            except Exception:
                pass

            results = await self.page.evaluate('''() => {
                const res = [];
                const seen = new Set();
                const containers = document.querySelectorAll('li.reusable-search__result-container, .entity-result__item');
                if (containers.length > 0) {
                    for (let card of containers) {
                        let a = card.querySelector('a[href*="/in/"]');
                        if (!a) continue;
                        let href = a.getAttribute('href');
                        if (!href || href.includes('/search/')) continue;
                        let url = href.split('?')[0];
                        if (!url.startsWith('http')) url = 'https://www.linkedin.com' + url;
                        if (!seen.has(url)) {
                            seen.add(url);
                            let nameEl = card.querySelector('.entity-result__title-text a, .entity-result__title-text') || a;
                            let name = nameEl.innerText.trim().split('\\n')[0];
                            if (!name) name = url.split('/in/')[1] || '';
                            let img = '';
                            let imgs = card.querySelectorAll('img');
                            for (let im of imgs) {
                                let src = im.src || im.getAttribute('data-delayed-url') || '';
                                if (src && src.includes('licdn.com')) {
                                    if (!src.includes('company-logo') && !src.includes('ghost-person')) {
                                        img = src;
                                        break;
                                    }
                                }
                            }
                            let headline = '';
                            let hlEl = card.querySelector('.entity-result__primary-subtitle');
                            if (hlEl) headline = hlEl.innerText.trim();
                            res.push({ profile_url: url, name: name, profile_picture: img, headline: headline });
                        }
                    }
                } else {
                    const links = document.querySelectorAll('a[href*="/in/"]');
                    for (let a of links) {
                        let href = a.getAttribute('href');
                        if (!href || href.includes('/search/')) continue;
                        let url = href.split('?')[0];
                        if (!url.startsWith('http')) url = 'https://www.linkedin.com' + url;
                        if (!seen.has(url)) {
                            seen.add(url);
                            let name = a.innerText.trim();
                            if (!name) name = url.split('/in/')[1] || '';
                            res.push({ profile_url: url, name: name, profile_picture: '' });
                        }
                    }
                }
                return res;
            }''')
            query_words = [w.lower() for w in (first_name + " " + last_name).split() if len(w) > 1]
            filtered_results = []
            for r in results:
                name_lower = r.get('name', '').lower()
                url_lower = r.get('profile_url', '').lower()
                
                # Filter out anonymous profiles
                if not r.get('name') or r.get('name') in ('LinkedIn Member', 'LinkedIn User'):
                    continue
                    
                # Filter by name keywords if query name is provided
                if query_words:
                    match = False
                    for qw in query_words:
                        if qw in ('sri', 'lanka', 'lankan', 'inc', 'corp', 'limited', 'co'):
                            continue
                        if qw in name_lower or qw in url_lower:
                            match = True
                            break
                    if not match:
                        print(f"Skipping unrelated search result: {r.get('name')} ({r.get('profile_url')})")
                        continue
                filtered_results.append(r)
                
            return filtered_results[:max_results]
        except Exception as e:
            err_msg = str(e)
            print(f"Search error: {err_msg}")
            if _retry < MAX_RETRIES and any(k in err_msg.lower() for k in ['context', 'navigation', 'closed', 'target', 'crashed']):
                print(f"Browser page/context issue detected during search. Re-initializing session and retrying ({_retry + 1}/{MAX_RETRIES})...")
                await asyncio.sleep(2)
                await self.ensure_active_page()
                return await self.search_people(first_name, last_name, company, max_results, force_search, _retry=_retry + 1)
            raise e


    async def search_and_extract(self, first_name: str, last_name: str, company: str = "", max_results: int = 1) -> Dict:
        results = await self.search_people(first_name, last_name, company, max_results=max_results)
        if not results:
            return {'success': False, 'error': 'No matching profiles found', 'profiles': []}
        extracted = []
        for i, r in enumerate(results):
            print(f"[Search & Extract] Scraping profile {i+1}/{len(results)}: {r.get('name')} ({r.get('profile_url')})")
            p = await self.extract_profile(r['profile_url'])
            if p and not p.get('error') and p.get('name'):
                extracted.append(p)
            if i < len(results) - 1:
                await asyncio.sleep(4)
        return {'success': bool(extracted), 'profiles_extracted': len(extracted), 'profiles': extracted}

    def sanitize_profile(self, profile: Dict) -> Dict:
        """
        Deep-clean a raw scraped profile:
        - Strips LinkedIn footer/nav junk from every section
        - Removes null/empty values
        - Deduplicates skills & languages
        - Cleans the About text
        Returns a new dict with only clean, usable section data.
        """
        if not profile or not isinstance(profile, dict):
            return {}

        p = dict(profile)

        # Clean top-level fields
        for field in ('name', 'headline', 'location', 'profile_url', 'profile_picture', 'connections'):
            val = p.get(field)
            if val and isinstance(val, str):
                cleaned = val.strip()
                if _is_noise(cleaned):
                    p[field] = ''
                else:
                    p[field] = cleaned

        # Clean list sections by purging entries with noise titles or missing names
        if 'skills' in p and isinstance(p['skills'], list):
            clean_s = []
            seen = set()
            for s in p['skills']:
                name = s.get('skill', '') if isinstance(s, dict) else str(s)
                name = name.strip()
                if name and not _is_noise(name) and len(name) < 80 and name.lower() not in seen:
                    seen.add(name.lower())
                    clean_s.append({'skill': name})
            p['skills'] = clean_s

        if 'experiences' in p and isinstance(p['experiences'], list):
            clean_e = []
            for e in p['experiences']:
                if isinstance(e, dict):
                    t = (e.get('title') or '').strip()
                    c = (e.get('company') or '').strip()
                    if t and not _is_noise(t) and not _is_noise(c):
                        clean_e.append(e)
            p['experiences'] = clean_e

        if 'qualifications' in p and isinstance(p['qualifications'], list):
            clean_q = []
            for q in p['qualifications']:
                if isinstance(q, dict):
                    inst = (q.get('institution') or '').strip()
                    deg = (q.get('degree') or '').strip()
        if 'volunteer' in p and isinstance(p['volunteer'], list):
            clean_v = []
            seen_v = set()
            junk_v = ['questions?', 'privacy', 'transparency', 'help center', 'settings', 'recommended content', 'select language', 'mobile']
            for v in p['volunteer']:
                if isinstance(v, dict):
                    role = (v.get('role') or '').strip()
                    org = (v.get('organization') or v.get('company') or '').strip()
                    if (role or org) and not _is_noise(role) and not _is_noise(org):
                        r_low, o_low = role.lower(), org.lower()
                        if not any(j in r_low or j in o_low for j in junk_v):
                            if not ('(' in o_low and ')' in o_low):
                                key = (r_low, o_low)
                                if key not in seen_v:
                                    seen_v.add(key)
                                    clean_v.append(v)
            p['volunteer'] = clean_v

        return p

    # Stats and cleanup
    async def get_stats(self) -> Dict:
        if self.stats['start_time']:
            self.stats['runtime_seconds'] = (datetime.now() - self.stats['start_time']).total_seconds()
        return {**self.stats, 'is_authenticated': self.is_authenticated}

    async def close(self):
        """Gracefully close the browser and release all resources."""
        self.is_authenticated = False
        if self.page:
            try:
                await self.page.close()
            except Exception:
                pass
            self.page = None
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        print("Browser closed and resources released.")