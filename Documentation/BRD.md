# Persona LinkedIn Profile Intelligence Platform
## Business Requirements Document (BRD)

---

## 1. Executive Summary
Persona is a full-stack LinkedIn profile intelligence platform designed to automate the discovery, extraction, ranking, and export of LinkedIn profile data. By leveraging real browser automation (Chromium via Playwright), Persona bypasses traditional scraping limitations, extracting rich, structured data (experience, education, skills, etc.) directly from LinkedIn's detailed sub-pages. The system includes an Admin Dashboard for task orchestration and a Client Portal for end-user data consumption.

## 2. Project Objectives
- **Automated Data Extraction:** Seamlessly navigate and extract structured data from LinkedIn profiles without manual intervention.
- **Deep Scraping:** Visit dedicated detail pages (e.g., `/details/experience`, `/details/education`) to bypass UI truncations on the main profile page.
- **Scalable Processing:** Implement a robust background task queue (Task Bucket) to handle bulk scraping over long periods while respecting rate limits.
- **Intelligent Ranking:** Score and rank profiles based on completeness, experience quality, and field relevance.
- **Data Accessibility:** Provide user-friendly interfaces (Admin/Client) and multiple export formats (JSON, CSV, PDF).

## 3. Target Audience
- **Recruiters & HR Professionals:** To source, rank, and export candidate profiles in bulk.
- **Sales & Lead Generation Teams:** To build comprehensive, structured lists of potential prospects.
- **Data Analysts:** To gather structured professional data for market analysis.

## 4. Scope of Work
### In-Scope
- Single and bulk profile scraping via URLs or Name/Company search.
- Extraction of over 15 profile sections (About, Experience, Education, Certifications, Languages, etc.).
- Background task orchestration with configurable rest periods.
- Real-time Admin Dashboard using Server-Sent Events (SSE).
- Client Portal for profile search and reference lookup.
- Ranking engine with a 0-150 point scoring model.
- Data export in JSON, CSV, and PDF formats.
- Persistent browser sessions (login once, scrape indefinitely).

### Out-of-Scope
- Automated messaging or connection requests on LinkedIn (System is read-only).
- Bypassing LinkedIn CAPTCHAs automatically (requires manual intervention during initial login).
- Scraping of LinkedIn Recruiter or Sales Navigator specific pages (unless using the standard profile URL).

## 5. Functional Requirements
### 5.1 Scraper Engine
- **REQ-01:** The system uses Playwright to drive a headless or headed Chromium browser.
- **REQ-02:** The system should navigate to detail sub-pages to extract complete list items (Experience, Education, etc.).
- **REQ-03:** The system shall filter out LinkedIn UI noise (navigation headers, footer links, etc.) from the extracted data.

### 5.2 Task Bucket & Orchestration
- **REQ-04:** The system may maintain a persistent task queue that survives server restarts.
- **REQ-05:** The system would process tasks asynchronously in a background thread to prevent blocking the web server.
- **REQ-06:** The system shall enforce configurable delays (rest periods) between scrapes to avoid rate-limiting.

### 5.3 Web Interfaces
- **REQ-07:** The Admin Dashboard shall provide real-time updates via SSE.
- **REQ-08:** The Client Portal shall allow searching by name and caching results for instant future retrieval.
- **REQ-09:** The Client Portal shall display profile cards and detailed modals.

### 5.4 Profile Ranking
- **REQ-10:** The system shall score profiles based on predefined weighted criteria (Profile Strength + Field Relevance).
- **REQ-11:** The system shall assign Tier labels (e.g., Elite, Advanced, Beginner) based on the total score.

## 6. Non-Functional Requirements
- **NFR-01 (Reliability):** The system must include a mechanism to kill orphan Chromium processes and recover from browser crashes.
- **NFR-02 (Performance):** The background event loop must handle continuous scraping without memory leaks.
- **NFR-03 (Security):** The session data (`browser_data/`) containing LinkedIn cookies must be stored locally and not exposed via APIs.
- **NFR-04 (Compatibility):** The extracted JSON schema must remain consistent for reliable API consumption.

## 7. Assumptions & Dependencies
- **LinkedIn UI Changes:** The scraper relies on current DOM structures. Major updates to LinkedIn's UI may require updates to the parsing logic in `core.py`.
- **Account Health:** Bulk scraping carries an inherent risk of LinkedIn account restrictions. Users are assumed to configure sensible rest periods.
- **Premium Features:** Extracting contact info (email/phone) natively depends on the scraping account having LinkedIn Premium/Sales Navigator access.
