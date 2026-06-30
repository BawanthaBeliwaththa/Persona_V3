# 📚 Persona — Documentation

> **Persona** is a full-stack LinkedIn profile intelligence platform that automates profile discovery, extraction, ranking, and export through a web-based admin dashboard and REST API.

---

## Documentation Map

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | System architecture, component diagrams, data flow, threading model |
| [Scraper Engine](./scraper-engine.md) | Deep dive into `core.py` — browser automation, extraction pipeline, section parsers |
| [API Reference](./api-reference.md) | Complete REST API documentation with request/response examples for all 40+ endpoints |
| [Data Schema](./data-schema.md) | Profile data model, database schema, file formats, job/task models |
| [Task Bucket System](./task-bucket.md) | Persistent task queue, background worker, configuration, SSE events |
| [Ranking Model](./ranking-model.md) | Weighted scoring model, field categories, tier system, scoring breakdown |
| [Admin Dashboard](./admin-dashboard.md) | Admin UI guide — scraper controls, job monitoring, database management |
| [Client Portal](./client-portal.md) | Client-facing portal — search, profile viewing, reference number lookups |
| [Deployment Guide](./deployment.md) | Installation, configuration, environment variables, production deployment |
| [Troubleshooting](./troubleshooting.md) | Common issues, debugging tips, FAQ |

---

## Quick Links

- **Source Code**: All source files live in the project root
- **Templates**: `templates/index.html` (Admin) and `templates/client.html` (Client)
- **Dependencies**: `req.txt`
- **Entry Point**: `python app.py` → `http://localhost:5000`

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.9+, Flask, asyncio |
| **Browser Automation** | Playwright (Chromium) |
| **Frontend** | Vanilla HTML/CSS/JavaScript (no frameworks) |
| **Data Storage** | JSON files, CSV files |
| **Real-time Updates** | Server-Sent Events (SSE) |
| **PDF Generation** | FPDF |
| **AI Parser** | OpenAI GPT-3.5-turbo (optional) |
| **HTTP Client** | Requests, aiohttp |

---

## Version History

| Version | Codename | Key Changes |
|---------|----------|-------------|
| V1 | — | Basic single-profile scraper |
| V2 | — | Added bulk scraping, REST API |
| V3 | — | Admin dashboard, client view, persistent database |
| **V4** | **Persona** | Detail sub-page navigation, Task Bucket, SSE live updates, profile ranking, PDF export, name-based search & extract |
