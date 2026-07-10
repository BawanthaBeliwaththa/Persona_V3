#Required Imports
import asyncio
import re
import sys
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
    'Search', 'Me', 'Work', 'Premium', 'Try Premium for free',
    # Generic expand/collapse buttons
    'Show all', 'Show more', 'See more', 'See less', 'Show less',
    'Show all experiences', 'Show all education', 'Show all skills',
    'Show all licenses & certifications', 'Show all honors & awards',
    'Show all volunteer experience', 'Show all recommendations',
    'Show all languages', 'Add skills', 'Add languages',
    'Show all 1 experience', 'Show all 1 education',
    # Tab labels inside detail pages
    'Received', 'Given', 'All', 'Top skills',
    # Common sidebar / footer
    'People also viewed', 'People you may know', 'Suggested for you',
    'More profiles for you', 'Activity', 'Interests', 'Following',
    'Connect', 'Follow', 'Message', 'More', 'Report',
    # Misc UI
    'Open to', 'Open to work', 'Hiring', 'Pronouns',
    'Contact info', 'Company size', 'Industry', 'Employees',
    '1st', '2nd', '3rd', '· 1st', '· 2nd', '· 3rd',
    '1st degree connection', '2nd degree connection',
    '• 1st', '• 2nd', '• 3rd',
}

# Patterns that indicate a line is UI noise (not profile data)
_UI_NOISE_PATTERNS = [
    re.compile(r'^\d+\s+connection', re.I),       # "500+ connections"
    re.compile(r'^\d+\s+follower', re.I),          # "1,234 followers"
    re.compile(r'^See all \d+', re.I),              # "See all 12 …"
    re.compile(r'^Show all \d+', re.I),             # "Show all 5 …"
    re.compile(r'^·\s+\d+\s+(yr|mo|week|day)', re.I),  # "· 2 yrs 3 mos"
    re.compile(r'^linkedin\.com', re.I),
    re.compile(r'^www\.linkedin\.com', re.I),
    re.compile(r'^\s*\d+\s*$'),                    # lone digit (page numbers etc.)
    re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}$', re.I),  # bare dates
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


def _is_noise(line: str) -> bool:
    """Return True if the line is UI chrome, not real profile text."""
    s = line.strip()
    if not s:
        return True
    if s in _UI_NOISE:
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
        self.stats = {'requests_made': 0, 'profiles_scraped': 0, 'errors': 0, 'start_time': None, 'runtime_seconds': 0}
        self.user_data_dir = Path(f"./browser_data/{session_name}")
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

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
        if sys.platform != 'win32':
            return
        try:
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
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-infobars',
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
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
        """)
        await self.page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)
        base_url = self.page.url.split('?')[0].rstrip('/')
        if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
            self.is_authenticated = True
            print("User is already logged in")
        else:
            self.is_authenticated = False
            print("Not logged in – please log in via UI")
        return self


    async def check_auth(self) -> bool:
        """Actively check if the current browser session is authenticated on LinkedIn."""
        if not self.page or not self.context:
            self.is_authenticated = False
            return False
        try:
            base_url = self.page.url.split('?')[0].rstrip('/')
            if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                self.is_authenticated = True
                return True
            
            await self.page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(1)
            base_url = self.page.url.split('?')[0].rstrip('/')
            if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                self.is_authenticated = True
                return True
        except Exception:
            pass
        self.is_authenticated = False
        return False


    # Login method (if not already authenticated)

    async def login(self, email: str, password: str) -> bool:
        if self.is_authenticated:
            return True
        await self.page.goto('https://www.linkedin.com/login', wait_until='domcontentloaded')
        await asyncio.sleep(2)
        await self.page.fill('#username', email)
        await self.page.fill('#password', password)
        await self.page.click('button[type="submit"]')
        # Wait up to 120 seconds for feed redirect to support CAPTCHA or 2FA in visible window
        print("Waiting for login redirect to feed (up to 120s for CAPTCHA/2FA)...")
        for _ in range(60):
            await asyncio.sleep(2)
            base_url = self.page.url.split('?')[0].rstrip('/')
            if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
                self.is_authenticated = True
                print("Login successful (feed page loaded)!")
                return True
                
        base_url = self.page.url.split('?')[0].rstrip('/')
        if 'feed' in base_url and 'login' not in base_url and 'checkpoint' not in base_url:
            self.is_authenticated = True
            return True
        print("Login timeout or failed.")
        return False


    # ── Core profile extraction ─────────────────────────────────────────────
    async def extract_profile(self, profile_url: str, _retry: int = 0) -> Dict:
        MAX_RETRIES = 2
        print(f"Extracting: {profile_url}" + (f" (retry {_retry})" if _retry else ""))
        try:
            # Step 1: Load main profile page
            await self.page.goto(profile_url, wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(4)
            try:
                await self.page.wait_for_selector('h1', timeout=15000)
            except:
                await asyncio.sleep(3)

            # Step 2: Scroll to trigger lazy-loading
            for _ in range(10):
                try:
                    await self.page.evaluate('window.scrollBy(0, 500)')
                except:
                    pass
                await asyncio.sleep(0.6)
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
                            await btn.scroll_into_view_if_needed()
                            await btn.click()
                            await asyncio.sleep(0.5)
                        except:
                            pass
                except:
                    pass
            await asyncio.sleep(1)

            # Step 4: Extract basic info from main page DOM
            raw = await self.page.evaluate('''() => {
                const data = {
                    name: '', headline: '', location: '',
                    profile_picture: '', connections: '',
                    page_title: document.title || ''
                };
                // Name
                const nameEls = ['h1', '.text-heading-xlarge', '.pv-top-card--list li:first-child'];
                for (const sel of nameEls) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim()) { data.name = el.innerText.trim(); break; }
                }
                // Headline
                const hlEls = ['.text-body-medium', '.pv-text-details__left-panel .text-body-medium'];
                for (const sel of hlEls) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim()) { data.headline = el.innerText.trim(); break; }
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
                // Connections/followers
                const spans = document.querySelectorAll('span.t-bold');
                for (const s of spans) {
                    const txt = s.innerText.trim();
                    if (/\\d/.test(txt) && /connection|follower/i.test(s.parentElement?.innerText || '')) {
                        data.connections = s.parentElement.innerText.trim();
                        break;
                    }
                }
                // About section — from the dedicated about div
                let aboutText = '';
                const aboutDiv = document.querySelector('#about ~ div, section[data-section="about"] .display-flex span[aria-hidden="true"]');
                if (aboutDiv) aboutText = aboutDiv.innerText.trim();
                if (!aboutText) {
                    // Fallback: look for the "About" section heading and grab next sibling
                    const headings = document.querySelectorAll('h2, h3, div[id]');
                    for (const h of headings) {
                        if (h.innerText && h.innerText.trim() === 'About') {
                            const sib = h.nextElementSibling;
                            if (sib) aboutText = sib.innerText.trim();
                            break;
                        }
                    }
                }
                data.about = aboutText;
                return data;
            }''')

            name = raw.get('name', '')
            if not name and raw.get('page_title'):
                title = raw['page_title']
                if ' - ' in title:
                    name = title.split(' - ')[0].strip()
                elif ' | ' in title:
                    name = title.split(' | ')[0].strip()

            # Step 5: Visit detail sub-pages
            base_url = profile_url.rstrip('/')
            detail_texts: Dict[str, str] = {}
            detail_pages = {
                'experience':      f"{base_url}/details/experience/",
                'education':       f"{base_url}/details/education/",
                'skills':          f"{base_url}/details/skills/",
                'certifications':  f"{base_url}/details/certifications/",
                'honors':          f"{base_url}/details/honors/",
                'languages':       f"{base_url}/details/languages/",
                'volunteer':       f"{base_url}/details/volunteering-experiences/",
                'recommendations': f"{base_url}/details/recommendations/",
            }
            for section, url in detail_pages.items():
                try:
                    await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(2)
                    # Scroll sub-page
                    for _ in range(5):
                        try:
                            await self.page.evaluate('window.scrollBy(0, 500)')
                        except:
                            pass
                        await asyncio.sleep(0.4)
                    # Expand "Show more" buttons
                    try:
                        btns = await self.page.query_selector_all(
                            'button.inline-show-more-text__button, button[aria-label*="Show more"]'
                        )
                        for b in btns:
                            try:
                                await b.click()
                                await asyncio.sleep(0.4)
                            except:
                                pass
                    except:
                        pass
                    # Extract ONLY the structured list items from the detail pane,
                    # not the entire body (which includes nav, sidebar, "People also viewed", etc.)
                    page_text = await self.page.evaluate('''() => {
                        // Try the most specific container first
                        const selectors = [
                            'main .pvs-list__container',
                            'main ul.pvs-list',
                            '[data-view-name="profile-component-entity"]',
                            '.scaffold-layout__main .pvs-list__container',
                            '.scaffold-layout__main ul',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.innerText.trim().length > 50) {
                                return el.innerText.trim();
                            }
                        }
                        // Last resort: grab only the <li> text inside main, NOT full body
                        const main = document.querySelector('main, [role="main"]');
                        if (main) {
                            const items = main.querySelectorAll('li.pvs-list__paged-list-item, li.artdeco-list__item');
                            if (items.length > 0) {
                                return Array.from(items).map(li => li.innerText.trim()).join('\\n---\\n');
                            }
                            // Narrow fallback: exclude known sidebar regions
                            const sidebar = main.querySelector('aside, [data-view-name="profile-card"]');
                            if (sidebar) sidebar.remove();
                            return main.innerText.trim();
                        }
                        return "";
                    }''')
                    if page_text and len(page_text) > 80:
                        detail_texts[section] = page_text
                except:
                    pass

            # Step 6: Parse each section
            about = raw.get('about', '').strip()
            if not about:
                # Fallback: parse from main page text
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

            connections = raw.get('connections', '')

            # Step 7: Navigate back to profile
            try:
                await self.page.goto(profile_url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(2)
            except:
                pass

            self.stats['profiles_scraped'] += 1
            result = {
                'name': name,
                'headline': raw.get('headline', ''),
                'location': raw.get('location', ''),
                'connections': connections,
                'profile_picture': raw.get('profile_picture', ''),
                'about': about,
                'current_job': current_job,
                'experience': experience,
                'qualifications': qualifications,
                'certifications': certifications,
                'skills': skills,
                'languages': languages,
                'volunteer': volunteer,
                'honors': honors,
                'recommendations': recommendations,
                'profile_url': profile_url,
                'scraped_at': datetime.now().isoformat()
            }
            found = []
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
            print(f"Success: Extracted: {name or 'Unknown'} | Found: {', '.join(found) or 'basic info only'}")
            return result

        except Exception as e:
            err_msg = str(e)
            print(f"Extraction error: {err_msg}")
            if _retry < MAX_RETRIES and ('context' in err_msg.lower() or 'navigation' in err_msg.lower()):
                print(f"Retrying ({_retry + 1}/{MAX_RETRIES})...")
                await asyncio.sleep(3)
                return await self.extract_profile(profile_url, _retry=_retry + 1)
            self.stats['errors'] += 1
            return {'profile_url': profile_url, 'error': err_msg}

    # ── Text cleaning helpers ───────────────────────────────────────────────

    def _clean_lines(self, text: str) -> List[str]:
        """Split text into lines, removing empty lines and known UI noise."""
        result = []
        for line in text.split('\n'):
            s = line.strip()
            if s and not _is_noise(s):
                result.append(s)
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
                    captured.append(s)
        return '\n'.join(captured).strip()

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
            # (short, mostly alphabetical, not a duration or number)
            if lang and len(lang) < 60 and not _looks_like_duration(lang) and not lang.isdigit():
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
                             max_results: int = 10, force_search: bool = False) -> List[Dict]:
        if not self.is_authenticated:
            raise Exception("Not authenticated")
        query = " ".join(filter(None, [first_name, last_name, company]))
        if not query:
            return []
        import urllib.parse
        encoded = urllib.parse.quote(query)
        url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
        try:
            await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
        except Exception as e:
            print(f"Warning: Search page navigation timed out or encountered error: {e}. Attempting to parse elements anyway...")

        await asyncio.sleep(3)

        for _ in range(4):
            await self.page.evaluate('window.scrollBy(0, 800)')
            await asyncio.sleep(1)
        html_content = await self.page.content()
        with open("search_debug.html", "w", encoding="utf-8") as f:
            f.write(html_content)

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


    async def search_and_extract(self, first_name: str, last_name: str, company: str = "") -> Dict:
        results = await self.search_people(first_name, last_name, company)
        if not results:
            return {'success': False, 'error': 'No profiles found', 'profiles': []}
        extracted = []
        for i, r in enumerate(results):
            print(f"Extracting {i+1}/{len(results)}")
            extracted.append(await self.extract_profile(r['profile_url']))
            await asyncio.sleep(5)
        return {'success': True, 'profiles_extracted': len(extracted), 'profiles': extracted}

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
