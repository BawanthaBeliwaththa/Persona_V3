#Required Imports
import asyncio
import re
from typing import Dict, List
from datetime import datetime
from playwright.async_api import async_playwright
from pathlib import Path

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

    # Initialization and Login
    async def initialize(self):
        print("Initializing browser...")
        self.stats['start_time'] = datetime.now()
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=self.headless,
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            args=['--disable-blink-features=AutomationControlled']
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
        """)
        await self.page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)
        if 'feed' in self.page.url:
            self.is_authenticated = True
            print("User is already logged in")
        else:
            print("Not logged in – please log in via UI")
        return self

    # Login method (if not already authenticated)
    async def login(self, email: str, password: str) -> bool:
        if self.is_authenticated:
            return True
        await self.page.goto('https://www.linkedin.com/login', wait_until='domcontentloaded')
        await asyncio.sleep(2)
        await self.page.fill('#username', email)
        await self.page.fill('#password', password)
        await self.page.click('button[type="submit"]')
        await asyncio.sleep(5)
        if 'feed' in self.page.url:
            self.is_authenticated = True
            return True
        return False

    # Core profile extraction method with retries and robust parsing
    async def extract_profile(self, profile_url: str, _retry: int = 0) -> Dict:
        MAX_RETRIES = 2
        print(f"Extracting: {profile_url}" + (f" (retry {_retry})" if _retry else ""))
        try:
            await self.page.goto(profile_url, wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(5)

            # Wait for main content
            try:
                await self.page.wait_for_selector('h1', timeout=15000)
            except:
                await asyncio.sleep(3)

            # Scroll to load ALL lazy sections (more passes for complete data)
            for _ in range(12):
                try:
                    await self.page.evaluate('window.scrollBy(0, 500)')
                except:
                    pass
                await asyncio.sleep(0.8)
            try:
                await self.page.evaluate('window.scrollTo(0, 0)')
            except:
                pass
            await asyncio.sleep(2)

            # Click ALL "Show all / see more / show more" buttons to expand hidden sections
            # LinkedIn collapses Experience, Skills, Education etc. behind these buttons
            expand_selectors = [
                'button[aria-label*="show all"]',
                'button[aria-label*="Show all"]',
                'button.inline-show-more-text__button',
                'button.pv-profile-section__see-more-inline',
                'a.pv-profile-section__see-more-inline',
                'button[data-control-name="about_see_more"]',
                'span[role="button"].lt-line-clamp__more',
                '.lt-line-clamp__more',
                'button.artdeco-button--tertiary',
            ]
            for sel in expand_selectors:
                try:
                    buttons = await self.page.query_selector_all(sel)
                    for btn in buttons:
                        try:
                            if await btn.is_visible():
                                await btn.click()
                                await asyncio.sleep(0.4)
                        except:
                            pass
                except:
                    pass

            # Also click buttons by their visible text content
            try:
                await self.page.evaluate('''() => {
                    const keywords = [
                        "Show all", "show all", "See more", "see more",
                        "Show more", "show more", "…more", "...more"
                    ];
                    const buttons = [...document.querySelectorAll('button, span[role="button"], a[role="button"]')];
                    for (const btn of buttons) {
                        const txt = (btn.innerText || btn.textContent || "").trim();
                        if (keywords.some(k => txt.includes(k))) {
                            try { btn.click(); } catch(e) {}
                        }
                    }
                }''')
                await asyncio.sleep(1)
            except:
                pass

            # Scroll again after expanding to load any newly revealed lazy content
            for _ in range(6):
                try:
                    await self.page.evaluate('window.scrollBy(0, 600)')
                except:
                    pass
                await asyncio.sleep(0.6)
            try:
                await self.page.evaluate('window.scrollTo(0, 0)')
            except:
                pass
            await asyncio.sleep(1)

            # Extract raw data in one JS call
            raw = await self.page.evaluate('''() => {
                const data = {
                    name: '', headline: '', location: '',
                    profile_picture: '', full_text: '',
                    connections: '', followers: '',
                    page_title: document.title || ''
                };

                // Name — try multiple selectors
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
                const imgEls = ['img.pv-top-card-profile-picture__image', 'img.presence-entity__image', 'img[src*="media.licdn.com"]'];
                for (const sel of imgEls) {
                    const el = document.querySelector(sel);
                    if (el && el.src) { data.profile_picture = el.src; break; }
                }

                // Connections / Followers counts
                const connEl = document.querySelector('.pv-top-card--list .t-bold, [data-field="connections"]');
                if (connEl) data.connections = connEl.innerText.trim();

                // Full page text — this always works
                data.full_text = document.body.innerText || '';
                return data;
            }''')

            # Parse name fallback from page title
            name = raw.get('name', '')
            if not name and raw.get('page_title'):
                title = raw['page_title']
                if ' - ' in title:
                    name = title.split(' - ')[0].strip()
                elif ' | ' in title:
                    name = title.split(' | ')[0].strip()

            full_text = raw.get('full_text', '')

            # Strip out Activity/posts content before parsing
            clean_text = self._strip_posts(full_text)

            # Try to extract contact info from the modal (email, phone, website)
            contact_info = await self._extract_contact_info()

            # Parse ALL structured sections from clean text
            about = self._parse_section(clean_text,
                start_markers=['About'],
                end_markers=self._ALL_SECTION_MARKERS)

            current_job    = self._parse_experience(clean_text)
            experiences    = self._parse_all_experiences(clean_text)
            education      = self._parse_education(clean_text)
            certifications = self._parse_certifications(clean_text)
            skills         = self._parse_skills(clean_text)
            honors         = self._parse_honors(clean_text)
            languages      = self._parse_languages(clean_text)
            projects       = self._parse_projects(clean_text)
            volunteer      = self._parse_volunteer(clean_text)
            publications   = self._parse_publications(clean_text)
            courses        = self._parse_courses(clean_text)
            recommendations = self._parse_recommendations(clean_text)
            interests      = self._parse_interests(clean_text)

            # Update stats and return structured result
            self.stats['profiles_scraped'] += 1
            result = {
                'name':            name,
                'headline':        raw.get('headline', ''),
                'location':        raw.get('location', ''),
                'profile_picture': raw.get('profile_picture', ''),
                'connections':     raw.get('connections', ''),
                'about':           about,
                'email':           contact_info.get('email', ''),
                'phone':           contact_info.get('phone', ''),
                'website':         contact_info.get('website', ''),
                'current_job':     current_job,
                'experiences':     experiences,
                'education':       education,
                'certifications':  certifications,
                'skills':          skills,
                'honors':          honors,
                'languages':       languages,
                'projects':        projects,
                'volunteer':       volunteer,
                'publications':    publications,
                'courses':         courses,
                'recommendations': recommendations,
                'interests':       interests,
                'profile_url':     profile_url,
                'scraped_at':      datetime.now().isoformat()
            }
            found = []
            if about: found.append('about')
            if current_job.get('title'): found.append('job')
            if experiences:     found.append(f'{len(experiences)} exp')
            if education:       found.append(f'{len(education)} edu')
            if certifications:  found.append(f'{len(certifications)} certs')
            if skills:          found.append(f'{len(skills)} skills')
            if languages:       found.append(f'{len(languages)} langs')
            if volunteer:       found.append(f'{len(volunteer)} vol')
            if publications:    found.append(f'{len(publications)} pubs')
            if projects:        found.append(f'{len(projects)} proj')
            print(f"✅ Extracted: {name or 'Unknown'} | Found: {', '.join(found) or 'basic info only'}")
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

    # ─── Section Marker Registry ─────────────────────────────────────────────
    # Full list of all known LinkedIn section headers. Used as end_markers so
    # each parser stops before the next section starts.
    _ALL_SECTION_MARKERS = [
        'About', 'Experience', 'Education', 'Licenses & certifications',
        'Skills', 'Honors & awards', 'Languages', 'Volunteer experience',
        'Projects', 'Publications', 'Courses', 'Recommendations',
        'Interests', 'Activity', 'Featured', 'Organizations',
        'Patents', 'Test scores', 'Volunteer'
    ]

    # ─── Contact Info (Modal) ────────────────────────────────────────────────
    # LinkedIn hides email/phone/website behind a modal. This method clicks the
    # "Contact info" link, waits for the modal, extracts the data, then closes it.
    async def _extract_contact_info(self) -> Dict:
        info = {'email': '', 'phone': '', 'website': ''}
        try:
            btn = await self.page.query_selector(
                'a[href*="contact-info"], #top-card-text-details-contact-info, '
                'a[id*="contact-info"], .pv-contact-info__contact-type'
            )
            if not btn:
                btn = await self.page.query_selector('a[href$="/detail/contact-info/"]')
            if btn:
                await btn.click()
                await asyncio.sleep(2)
                modal_info = await self.page.evaluate('''() => {
                    const info = {email: '', phone: '', website: ''};
                    const sections = document.querySelectorAll(
                        '.pv-contact-info__contact-type, .pv-contact-info__ci-container'
                    );
                    for (const s of sections) {
                        const txt = s.innerText || '';
                        // Email
                        const emailA = s.querySelector('a[href^="mailto:"]');
                        if (emailA) info.email = emailA.href.replace('mailto:', '').trim();
                        // Phone
                        const phoneSpan = s.querySelector('span.t-14');
                        if (phoneSpan && (txt.toLowerCase().includes('phone') ||
                            txt.toLowerCase().includes('mobile'))) {
                            info.phone = phoneSpan.innerText.trim();
                        }
                        // Website
                        const webA = s.querySelector('a[href^="http"]');
                        if (webA && !webA.href.includes('linkedin.com')) {
                            info.website = webA.href.trim();
                        }
                    }
                    return info;
                }''')
                info.update(modal_info)
                # Close the modal
                try:
                    close = await self.page.query_selector(
                        'button[aria-label="Dismiss"], .artdeco-modal__dismiss, button.artdeco-button--circle'
                    )
                    if close:
                        await close.click()
                        await asyncio.sleep(0.5)
                except:
                    pass
        except Exception as e:
            print(f"Contact info extraction skipped: {e}")
        return info

    # ─── Text Parsing Helpers ────────────────────────────────────────────────

    # Removes Activity/posts sections so they don't bleed into profile parsing.
    def _strip_posts(self, text: str) -> str:
        lines = text.split('\n')
        clean = []
        skip_markers = ['Activity', 'Suggested for you', 'People also viewed',
                        'People you may know', 'More profiles for you']
        skipping = False
        resume_markers = [
            'Experience', 'Education', 'Licenses & certifications',
            'Skills', 'Honors & awards', 'Recommendations',
            'Languages', 'Volunteer experience', 'Projects',
            'Publications', 'Courses', 'Interests', 'About'
        ]
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

    # Generic section parser — captures text between start and the next end marker.
    def _parse_section(self, text: str, start_markers: list, end_markers: list) -> str:
        lines = text.split('\n')
        capturing = False
        captured = []
        for line in lines:
            stripped = line.strip()
            if not capturing:
                if stripped in start_markers:
                    capturing = True
                    continue
            else:
                if stripped in end_markers:
                    break
                if stripped:
                    captured.append(stripped)
        return '\n'.join(captured).strip()

    # Returns the first experience entry (current job) as a dict.
    def _parse_experience(self, text: str) -> Dict:
        lines = text.split('\n')
        in_exp = False
        exp_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Experience':
                in_exp = True
                continue
            if in_exp:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Experience':
                    break
                if stripped and stripped not in ['Show all experiences', 'Show all']:
                    exp_lines.append(stripped)
        if not exp_lines:
            return {}
        return {
            'title':    exp_lines[0] if len(exp_lines) > 0 else '',
            'company':  exp_lines[1] if len(exp_lines) > 1 else '',
            'duration': exp_lines[2] if len(exp_lines) > 2 else '',
            'location': exp_lines[3] if len(exp_lines) > 3 else ''
        }

    # Returns ALL experience entries as a list of dicts (4 lines each).
    def _parse_all_experiences(self, text: str) -> list:
        lines = text.split('\n')
        in_exp = False
        exp_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Experience':
                in_exp = True
                continue
            if in_exp:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Experience':
                    break
                if stripped and stripped not in ['Show all experiences', 'Show all']:
                    exp_lines.append(stripped)
        if not exp_lines:
            return []
        entries = []
        i = 0
        while i < len(exp_lines):
            entry = {'title': exp_lines[i], 'company': '', 'duration': '', 'location': ''}
            if i + 1 < len(exp_lines): entry['company']  = exp_lines[i + 1]
            if i + 2 < len(exp_lines): entry['duration'] = exp_lines[i + 2]
            if i + 3 < len(exp_lines): entry['location'] = exp_lines[i + 3]
            entries.append(entry)
            i += 4
        return entries

    # Returns education entries as a list of dicts (3 lines each).
    def _parse_education(self, text: str) -> list:
        lines = text.split('\n')
        in_edu = False
        edu_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Education':
                in_edu = True
                continue
            if in_edu:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Education':
                    break
                if stripped and stripped not in ['Show all education', 'Show all']:
                    edu_lines.append(stripped)
        entries = []
        i = 0
        while i < len(edu_lines):
            entry = {'institution': edu_lines[i], 'degree': '', 'dates': ''}
            if i + 1 < len(edu_lines): entry['degree'] = edu_lines[i + 1]
            if i + 2 < len(edu_lines): entry['dates']  = edu_lines[i + 2]
            entries.append(entry)
            i += 3
        return entries

    # Returns certification entries as a list of dicts (3 lines each).
    def _parse_certifications(self, text: str) -> list:
        lines = text.split('\n')
        in_certs = False
        cert_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped in ['Licenses & certifications', 'Licenses and certifications']:
                in_certs = True
                continue
            if in_certs:
                if stripped in self._ALL_SECTION_MARKERS:
                    break
                if stripped and stripped not in ['Show all licenses & certifications', 'Show all']:
                    cert_lines.append(stripped)
        entries = []
        i = 0
        while i < len(cert_lines):
            entry = {'name': cert_lines[i], 'issuer': '', 'date': ''}
            if i + 1 < len(cert_lines): entry['issuer'] = cert_lines[i + 1]
            if i + 2 < len(cert_lines): entry['date']   = cert_lines[i + 2]
            entries.append(entry)
            i += 3
        return entries

    # Returns skills as a list of dicts with name and endorsement count.
    # Lines that look like endorsement metadata are filtered out.
    def _parse_skills(self, text: str) -> list:
        lines = text.split('\n')
        in_skills = False
        skill_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Skills':
                in_skills = True
                continue
            if in_skills:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Skills':
                    break
                skip_phrases = ['Endorsed by', 'endorsements', 'Show all', 'colleagues at']
                if stripped and not any(p in stripped for p in skip_phrases):
                    skill_lines.append(stripped)
        entries = []
        i = 0
        while i < len(skill_lines):
            # Each skill is 1 line; endorsement count may follow (e.g. "99+")
            name = skill_lines[i]
            endorsements = ''
            if i + 1 < len(skill_lines) and re.match(r'^\d', skill_lines[i + 1]):
                endorsements = skill_lines[i + 1]
                i += 2
            else:
                i += 1
            entries.append({'skill': name, 'endorsements': endorsements})
        return entries

    # Returns honors & awards as a list of dicts (3 lines: title, issuer, date).
    def _parse_honors(self, text: str) -> list:
        lines = text.split('\n')
        in_honors = False
        honor_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped in ['Honors & awards', 'Honors and awards']:
                in_honors = True
                continue
            if in_honors:
                if stripped in self._ALL_SECTION_MARKERS:
                    break
                if stripped and stripped not in ['Show all honors & awards', 'Show all']:
                    honor_lines.append(stripped)
        entries = []
        i = 0
        while i < len(honor_lines):
            entry = {'title': honor_lines[i], 'issuer': '', 'date': '', 'description': ''}
            if i + 1 < len(honor_lines): entry['issuer']      = honor_lines[i + 1]
            if i + 2 < len(honor_lines): entry['date']        = honor_lines[i + 2]
            if i + 3 < len(honor_lines): entry['description'] = honor_lines[i + 3]
            entries.append(entry)
            i += 4
        return entries

    # Returns languages as a list of dicts (2 lines: language, proficiency).
    def _parse_languages(self, text: str) -> list:
        lines = text.split('\n')
        in_lang = False
        lang_lines = []
        proficiency_keywords = [
            'Native', 'Bilingual', 'Full professional', 'Professional working',
            'Limited working', 'Elementary', 'proficiency'
        ]
        for line in lines:
            stripped = line.strip()
            if stripped == 'Languages':
                in_lang = True
                continue
            if in_lang:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Languages':
                    break
                if stripped and stripped not in ['Show all languages', 'Show all']:
                    lang_lines.append(stripped)
        entries = []
        i = 0
        while i < len(lang_lines):
            name = lang_lines[i]
            proficiency = ''
            if i + 1 < len(lang_lines) and any(kw in lang_lines[i + 1] for kw in proficiency_keywords):
                proficiency = lang_lines[i + 1]
                i += 2
            else:
                i += 1
            entries.append({'language': name, 'proficiency': proficiency})
        return entries

    # Returns projects as a list of dicts (title, dates, description).
    def _parse_projects(self, text: str) -> list:
        lines = text.split('\n')
        in_proj = False
        proj_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Projects':
                in_proj = True
                continue
            if in_proj:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Projects':
                    break
                if stripped and stripped not in ['Show all projects', 'Show all']:
                    proj_lines.append(stripped)
        entries = []
        i = 0
        while i < len(proj_lines):
            entry = {'title': proj_lines[i], 'dates': '', 'associated_with': '', 'description': ''}
            if i + 1 < len(proj_lines): entry['dates']           = proj_lines[i + 1]
            if i + 2 < len(proj_lines): entry['associated_with'] = proj_lines[i + 2]
            if i + 3 < len(proj_lines): entry['description']     = proj_lines[i + 3]
            entries.append(entry)
            i += 4
        return entries

    # Returns volunteer experience as a list of dicts (4 lines each).
    def _parse_volunteer(self, text: str) -> list:
        lines = text.split('\n')
        in_vol = False
        vol_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped in ['Volunteer experience', 'Volunteering']:
                in_vol = True
                continue
            if in_vol:
                if stripped in self._ALL_SECTION_MARKERS:
                    break
                if stripped and stripped not in ['Show all volunteer experience', 'Show all']:
                    vol_lines.append(stripped)
        entries = []
        i = 0
        while i < len(vol_lines):
            entry = {'role': vol_lines[i], 'organization': '', 'duration': '', 'cause': ''}
            if i + 1 < len(vol_lines): entry['organization'] = vol_lines[i + 1]
            if i + 2 < len(vol_lines): entry['duration']     = vol_lines[i + 2]
            if i + 3 < len(vol_lines): entry['cause']        = vol_lines[i + 3]
            entries.append(entry)
            i += 4
        return entries

    # Returns publications as a list of dicts (title, publisher, date, description).
    def _parse_publications(self, text: str) -> list:
        lines = text.split('\n')
        in_pub = False
        pub_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Publications':
                in_pub = True
                continue
            if in_pub:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Publications':
                    break
                if stripped and stripped not in ['Show all publications', 'Show all']:
                    pub_lines.append(stripped)
        entries = []
        i = 0
        while i < len(pub_lines):
            entry = {'title': pub_lines[i], 'publisher': '', 'date': '', 'description': ''}
            if i + 1 < len(pub_lines): entry['publisher']   = pub_lines[i + 1]
            if i + 2 < len(pub_lines): entry['date']        = pub_lines[i + 2]
            if i + 3 < len(pub_lines): entry['description'] = pub_lines[i + 3]
            entries.append(entry)
            i += 4
        return entries

    # Returns courses as a list of dicts (2 lines: name, associated_with).
    def _parse_courses(self, text: str) -> list:
        lines = text.split('\n')
        in_courses = False
        course_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Courses':
                in_courses = True
                continue
            if in_courses:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Courses':
                    break
                if stripped and stripped not in ['Show all courses', 'Show all']:
                    course_lines.append(stripped)
        entries = []
        i = 0
        while i < len(course_lines):
            entry = {'name': course_lines[i], 'associated_with': ''}
            if i + 1 < len(course_lines): entry['associated_with'] = course_lines[i + 1]
            entries.append(entry)
            i += 2
        return entries

    # Returns received recommendations as a list of dicts.
    def _parse_recommendations(self, text: str) -> list:
        lines = text.split('\n')
        in_rec = False
        rec_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Recommendations':
                in_rec = True
                continue
            if in_rec:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Recommendations':
                    break
                if stripped and stripped not in ['Received', 'Given', 'Show all recommendations', 'Show all']:
                    rec_lines.append(stripped)
        entries = []
        i = 0
        while i < len(rec_lines):
            entry = {'recommender': rec_lines[i], 'title': '', 'text': ''}
            if i + 1 < len(rec_lines): entry['title'] = rec_lines[i + 1]
            if i + 2 < len(rec_lines): entry['text']  = rec_lines[i + 2]
            entries.append(entry)
            i += 3
        return entries

    # Returns interests (followed companies/people/schools) as a simple list of names.
    def _parse_interests(self, text: str) -> list:
        lines = text.split('\n')
        in_int = False
        int_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == 'Interests':
                in_int = True
                continue
            if in_int:
                if stripped in self._ALL_SECTION_MARKERS and stripped != 'Interests':
                    break
                skip = ['Top Voices', 'Companies', 'Groups', 'Schools', 'Newsletters',
                        'Show all', 'Follow', 'followers']
                if stripped and not any(s in stripped for s in skip) and len(stripped) > 2:
                    int_lines.append(stripped)
        return int_lines

    # Search & other methods

    # The search_people method performs a LinkedIn people search based on the provided first name, last name, and optional company. It constructs a search query, navigates to the search results page, scrolls to load more results, and extracts profile URLs and names from the search results. If only a first name is provided without a last name and it looks like a profile URL, it tries to extract that specific profile directly.
    async def search_people(self, first_name: str, last_name: str, company: str = "", max_results: int = 10, force_search: bool = False) -> List[Dict]:
        if not self.is_authenticated:
            raise Exception("Not authenticated")
        if not force_search and first_name and not last_name and '@' not in first_name:
            profile = await self.extract_profile(f"https://www.linkedin.com/in/{first_name.strip()}/")
            return [profile] if profile.get('name') else []
        query = " ".join(filter(None, [first_name, last_name, company]))
        if not query:
            return []
        import urllib.parse
        encoded = urllib.parse.quote(query)
        url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
        await self.page.goto(url, wait_until='domcontentloaded')
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
                        
                        // Extract headline if possible to improve quality
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
                        let img = '';
                        try {
                            let card = a.parentElement.parentElement;
                            if (card) {
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
                            }
                        } catch(e) {}
                        res.push({ profile_url: url, name: name, profile_picture: img });
                    }
                }
            }
            return res.slice(0, 15);
        }''')
        return results[:max_results]

    # The search_and_extract method combines the search_people and extract_profile methods to perform a search based on the provided criteria and then extract detailed profile information for each of the top results. It returns a structured result indicating success, the number of profiles extracted, and any errors encountered.
    async def search_and_extract(self, first_name: str, last_name: str, company: str = "", max_profiles: int = 3) -> Dict:
        results = await self.search_people(first_name, last_name, company, max_profiles)
        if not results:
            return {'success': False, 'error': 'No profiles found', 'profiles': []}
        extracted = []
        for i, r in enumerate(results[:max_profiles]):
            print(f"Extracting {i+1}/{min(max_profiles, len(results))}")
            extracted.append(await self.extract_profile(r['profile_url']))
            await asyncio.sleep(4)
        return {'success': True, 'profiles_extracted': len(extracted), 'profiles': extracted}

    # Stats and cleanup methods
    async def get_stats(self) -> Dict:
        if self.stats['start_time']:
            self.stats['runtime_seconds'] = (datetime.now() - self.stats['start_time']).total_seconds()
        return {**self.stats, 'is_authenticated': self.is_authenticated}

    # The close method ensures that the browser context and Playwright instance are properly closed to free up resources. It checks if the context and Playwright instances exist before attempting to close them, and it prints a confirmation message once the browser is closed.
    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        print("Browser closed")