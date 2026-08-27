# Functional Requirements Document (FRD) - Persona Project

## 1. Introduction
This document defines the functional requirements for the Persona LinkedIn Scraper.

## 2. Core Scraping Functionality
- **FR-01:** The system shall authenticate to LinkedIn using a user-provided email and password via a Chromium browser.
- **FR-02:** The system shall maintain browser session persistence using Playwright's user data directory feature.
- **FR-03:** The scraper shall extract data from the main profile page (Name, Headline, Location, Connections, Profile Picture, About).
- **FR-04:** The scraper shall explicitly navigate to detail pages (e.g., `/details/experience/`) to extract complete list items.
- **FR-05:** The system shall filter out predefined LinkedIn UI text (e.g., "Show more", "People also viewed").

## 3. Task Management (Task Bucket)
- **FR-06:** The system shall allow users to enqueue tasks (by URL or Name) into a persistent Task Bucket.
- **FR-07:** The background worker shall process tasks sequentially.
- **FR-08:** The system shall enforce a configurable rest period (e.g., 30-75 seconds) between scraping tasks.
- **FR-09:** The worker shall automatically resume processing queued tasks upon server restart.

## 4. User Interfaces
- **FR-10:** The Admin Dashboard shall display real-time scraper statuses using Server-Sent Events (SSE).
- **FR-11:** The Admin Dashboard shall provide controls to Start, Pause, Resume, and Clear the Task Bucket.
- **FR-12:** The Client Portal shall allow users to search for scraped profiles by name or reference number.

## 5. Export and Ranking (Future Improvement)
- **FR-13:** The system shall score profiles on a 0-150 scale based on completeness (Future).
- **FR-14:** The system shall allow exporting the master database to JSON and CSV formats.
- **FR-15:** The system shall provide an endpoint to export single or bulk profiles as PDF reports.
