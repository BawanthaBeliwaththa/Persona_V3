# Changelog - Persona Project

All notable changes to this project will be documented in this file.

## [4.0.0] - 2026-08-02
### Added
- **Deep Extraction Strategy:** Scraper now visits `/details/experience/`, `/details/education/`, etc. for complete list data.
- **Task Bucket System:** Added background queue for unattended scraping.
- **SSE Live Updates:** Real-time progress broadcasting to the Admin Dashboard.
- **Profile Ranker:** (Planned for future release) 0-150 point scoring model with Tier classifications.
- **Contact Info Extraction:** Added native support for extracting emails/phone numbers via `/overlay/contact-info/` (requires Premium).

### Fixed
- Fixed bug where `browser_data` file locks caused `WinError 32` crashes on startup by adding a forceful process killer.
- Fixed UI noise pollution by implementing a robust text cleaner (`_is_noise()`) that strips LinkedIn footer text.

## [3.1.0] - (Legacy)
### Added
- Export to PDF functionality.
- Initial Client Portal search feature.

### Changed
- Migrated from BeautifulSoup to Playwright for main page DOM parsing.
