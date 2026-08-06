# Release Notes - Persona (V3)

## Overview
Persona V4 introduces a massive architectural overhaul to the scraping engine, transitioning from basic main-page text parsing to deep, sub-page DOM extraction. This release also introduces the Task Bucket system for unattended background processing and real-time SSE updates.

## What's New

### Deep Profile Extraction
- **Detail Page Navigation:** The scraper now actively navigates to dedicated sub-pages (`/details/experience`, `/details/education`, `/details/skills`, etc.) to extract complete list items, bypassing the truncations ("Show more") found on the main profile page.
- **Robust UI Noise Filtering:** Implemented advanced filtering rules to strip out LinkedIn UI garbage (e.g., footer links, language selectors, "People also viewed" sidebars) ensuring pristine JSON output.

### Task Bucket & Background Orchestration
- **Persistent Task Queue:** Added a SQLite/JSON-backed task queue (`queue.json`) that survives server restarts.
- **Background Worker:** A dedicated `asyncio` event loop runs in a background daemon thread, processing scraping jobs continuously without blocking the Flask web server.
- **Configurable Rest Periods:** Added built-in delays between scrapes to mimic human behavior and prevent IP bans/rate-limiting.

### Real-Time Admin Dashboard
- **Server-Sent Events (SSE):** The Admin UI now receives live updates directly from the background worker. Job statuses, scraping progress, and queue counts update instantly without requiring manual page refreshes.

## Improvements & Optimizations

- **Playwright Crash Recovery:** Implemented aggressive orphan process management. The system now automatically detects and kills stale Chromium child processes and clears levelDB `LOCK` files to ensure smooth browser initialization on Windows.
- **Data Sanitization:** Improved the `sanitize_profile` function to recursively clean null values, empty arrays, and duplicate skills from the final JSON object.
- **Contact Info Extraction:** Added support for extracting contact info from the `/overlay/contact-info/` panel (Note: best results require a Premium account).

## Known Limitations
- Extracting Contact Info via the global search endpoint requires the authenticated account to have a LinkedIn Premium or Sales Navigator subscription.
