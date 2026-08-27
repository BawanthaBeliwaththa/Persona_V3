# Software Requirements Specification (SRS) - Persona Project

## 1. Introduction
### 1.1 Purpose
The purpose of this SRS is to outline the software requirements for the Persona LinkedIn Scraper platform. It serves as a guide for developers and stakeholders to understand what the system will do and how it will perform.

### 1.2 Product Scope
Persona is a Python/Flask-based web application orchestrating a Playwright Chromium browser to systematically scrape, export, and (in the future) rank LinkedIn profiles, managed via a web UI and REST API.

## 2. Overall Description
### 2.1 Product Perspective
Persona acts as a standalone service. It requires an internet connection and a valid LinkedIn account. It interacts with the local file system to store data (`exports/`) and browser state (`browser_data/`).

### 2.2 User Characteristics
- **Admin Users:** Technical or semi-technical users who configure the scraper, manage the queue, and perform bulk exports.
- **Client Users:** Non-technical users who use the Client Portal to search and view generated profile cards.

### 2.3 Operating Environment
- Platform: Windows, macOS, Linux (Ubuntu).
- Frameworks: Flask, Playwright for Python.

## 3. System Features
### 3.1 Headless Browser Orchestration
- **Description:** Uses `playwright` to launch Chromium.
- **Inputs:** URLs or Search Terms.
- **Outputs:** Extracted HTML/DOM text converted into structured dictionaries.

### 3.2 Asynchronous Background Queue
- **Description:** A dedicated `asyncio` loop running in a daemon thread processes queued tasks.
- **Inputs:** Task payloads (name or URL).
- **Outputs:** Updated `queue.json` state and scraped profile data appended to `all_scraped_profiles.json`.

## 4. Non-Functional Requirements
### 4.1 Performance Requirements
- The UI shall remain responsive (under 200ms) while the background worker is actively scraping.
- SSE events shall be broadcast to connected clients within 1 second of a status change.

### 4.2 Security Requirements
- The application does not store plain-text LinkedIn passwords (only browser cookies via Playwright).
- The REST API assumes a trusted local network deployment (no built-in JWT/OAuth).

### 4.3 Reliability
- The system must aggressively hunt and kill orphan `chrome.exe` processes (Windows) during initialization to prevent `LevelDB LOCK` file errors.
