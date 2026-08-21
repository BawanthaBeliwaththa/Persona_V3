# Product Requirements Document (PRD) - Persona Project

## 1. Objective
To deliver a stable, reliable, and user-friendly platform that extracts high-fidelity professional data from LinkedIn, and exports them in standardized formats. (Profile scoring is a future improvement).

## 2. Target Release
Persona V4.

## 3. Product Features & User Stories
### Epic 1: Scraper Engine
- **As an Admin,** I want the scraper to navigate to detail pages (like `/details/experience`) so that I get complete job descriptions instead of truncated text.
- **As an Admin,** I want the scraper to mimic human scrolling and delays so that my LinkedIn account avoids immediate bot detection.

### Epic 2: Task Bucket
- **As an Admin,** I want to paste a list of 100 LinkedIn URLs into a queue so that the system scrapes them automatically overnight.
- **As an Admin,** I want to set a "rest period" of 45 seconds between scrapes to keep my account safe.
- **As an Admin,** I want the scraper to resume exactly where it left off if the server crashes or restarts.

### Epic 3: User Interfaces
- **As an Admin,** I want to see real-time progress of the scraper in my browser without having to refresh the page.
- **As a Client/End-User,** I want a clean search bar where I can type a name and instantly see a formatted profile card if the data is already in the database.

### Epic 4: Data Export
- **As a Recruiter,** I want to download a formatted PDF of a candidate's profile to share with hiring managers.
- **As a Data Analyst,** I want to download the entire database as a CSV file for import into Excel/Tableau.

## 4. Success Metrics
- **Extraction Accuracy:** 95%+ success rate in identifying and extracting non-empty Experience and Education fields for valid profiles.
- **System Uptime:** Ability to process 500+ profiles in a continuous background queue without a memory leak or crash.
- **Account Safety:** Zero account bans when operating at recommended rest intervals (30+ seconds).
