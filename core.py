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

            # Scroll to load lazy sections
            for _ in range(8):
                try:
                    await self.page.evaluate('window.scrollBy(0, 400)')
                except:
                    pass
                await asyncio.sleep(1)
            try:
                await self.page.evaluate('window.scrollTo(0, 0)')
            except:
                pass
            await asyncio.sleep(2)

            # Extract raw data in one JS call 
            raw = await self.page.evaluate('''() => {
                const data = {
                    name: '', headline: '', location: '',
                    profile_picture: '', full_text: '',
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

            # Parse structured sections from clean text
            about = self._parse_section(clean_text,
                start_markers=['About'],
                end_markers=['Experience', 'Activity', 'Education', 'Skills', 'Interests',
                             'Languages', 'Featured', 'Licenses & certifications',
                             'Volunteer', 'Projects', 'Publications', 'Courses',
                             'Honors & awards', 'Recommendations'])

            # Parse current job (first experience entry) and all experience entries separately, as some profiles have multiple experiences listed on the main page
            current_job = self._parse_experience(clean_text)
            experience = self._parse_all_experiences(clean_text)
            qualifications = self._parse_education(clean_text)
            certifications = self._parse_certifications(clean_text)

            # Update stats and return structured result
            self.stats['profiles_scraped'] += 1
            result = {
                'name': name,
                'headline': raw.get('headline', ''),
                'location': raw.get('location', ''),
                'profile_picture': raw.get('profile_picture', ''),
                'about': about,
                'current_job': current_job,
                'experience': experience,
                'qualifications': qualifications,
                'certifications': certifications,
                'profile_url': profile_url,
                'scraped_at': datetime.now().isoformat()
            }
            found = []
            if about: found.append('about')
            if current_job.get('title'): found.append('job')
            if experience: found.append(f'{len(experience)} exp')
            if qualifications: found.append(f'{len(qualifications)} edu')
            if certifications: found.append(f'{len(certifications)} certs')
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

    # Text parsing helpers
    
    # Some profiles have a long "Activity" section with posts that drowns out the main profile text. This function removes that section and anything in between until we reach a known resume section like Experience or Education.
    def _strip_posts(self, text: str) -> str:
        lines = text.split('\n')
        clean = []
        skip_markers = ['Activity', 'Suggested for you', 'People also viewed',
                        'People you may know', 'More profiles for you']
        skipping = False

        # Resume markers — sections that come after Activity
        resume_markers = ['Experience', 'Education', 'Licenses & certifications',
                          'Skills', 'Honors & awards', 'Recommendations',
                          'Interests', 'About']
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

    # Generic section parser that captures text between a start marker and the next end marker. Used for About and other sections that may have variable length.
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

    # Experience parsing is tricky because the main profile page often only shows the current job with 3-4 lines of text (title, company, duration, location) and the rest of the experience entries are hidden behind a "Show all experiences" link. This function tries to parse the current job from the main text, while another function separately parses all experience entries if they are present in the full text.
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
                if stripped in ['Education', 'Licenses & certifications', 'Skills',
                                'Interests', 'Activity', 'Recommendations', 'Honors & awards',
                                'Languages', 'Volunteer', 'Projects', 'Publications']:
                    break
                if stripped and stripped not in ['Show all experiences', 'Show all']:
                    exp_lines.append(stripped)
        if not exp_lines:
            return {}
        return {
            'title': exp_lines[0] if len(exp_lines) > 0 else '',
            'company': exp_lines[1] if len(exp_lines) > 1 else '',
            'duration': exp_lines[2] if len(exp_lines) > 2 else '',
            'location': exp_lines[3] if len(exp_lines) > 3 else ''
        }

    # Some profiles have multiple experience entries listed on the main page, while others only show the current job with a "Show all experiences" link. This function parses all experience entries from the full text, grouping them into title/company/duration/location sets. It looks for the Experience section and captures all entries until it reaches another known section like Education or Skills.
    def _parse_all_experiences(self, text: str) -> list:
        lines = text.split('\n')
        in_exp = False
        exp_lines = []
        end_markers = ['Education', 'Licenses & certifications', 'Skills',
                       'Interests', 'Activity', 'Recommendations', 'Honors & awards',
                       'Languages', 'Volunteer', 'Projects', 'Publications']
        for line in lines:
            stripped = line.strip()
            if stripped == 'Experience':
                in_exp = True
                continue
            if in_exp:
                if stripped in end_markers:
                    break
                if stripped and stripped not in ['Show all experiences', 'Show all']:
                    exp_lines.append(stripped)
        if not exp_lines:
            return []
        # Group into entries of 4 lines each (title, company, duration, location)
        entries = []
        i = 0
        while i < len(exp_lines):
            entry = {'title': exp_lines[i], 'company': '', 'duration': '', 'location': ''}
            if i + 1 < len(exp_lines):
                entry['company'] = exp_lines[i + 1]
            if i + 2 < len(exp_lines):
                entry['duration'] = exp_lines[i + 2]
            if i + 3 < len(exp_lines):
                entry['location'] = exp_lines[i + 3]
            entries.append(entry)
            i += 4
        return entries

    # Education parsing is similar to experience parsing, but the entries are usually grouped in sets of 3 lines (institution, degree, dates) and the section ends when we reach another known section like Licenses & certifications or Skills. This function captures all education entries from the full text.
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
                if stripped in ['Licenses & certifications', 'Skills', 'Interests',
                                'Activity', 'Recommendations', 'Experience', 'Honors & awards']:
                    break
                if stripped and stripped not in ['Show all education', 'Show all']:
                    edu_lines.append(stripped)
        entries = []
        i = 0
        while i < len(edu_lines):
            entry = {'institution': edu_lines[i], 'degree': '', 'dates': ''}
            if i + 1 < len(edu_lines):
                entry['degree'] = edu_lines[i + 1]
            if i + 2 < len(edu_lines):
                entry['dates'] = edu_lines[i + 2]
            entries.append(entry)
            i += 3
        return entries

    # Certifications parsing is also similar, with entries usually in sets of 3 lines (name, issuer, date) and the section ending when we reach another known section like Skills or Experience. This function captures all certification entries from the full text.
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
                if stripped in ['Skills', 'Interests', 'Activity', 'Recommendations',
                                'Education', 'Experience', 'Honors & awards']:
                    break
                if stripped and stripped not in ['Show all licenses & certifications', 'Show all']:
                    cert_lines.append(stripped)
        entries = []
        i = 0
        while i < len(cert_lines):
            entry = {'name': cert_lines[i], 'issuer': '', 'date': ''}
            if i + 1 < len(cert_lines):
                entry['issuer'] = cert_lines[i + 1]
            if i + 2 < len(cert_lines):
                entry['date'] = cert_lines[i + 2]
            entries.append(entry)
            i += 3
        return entries

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
