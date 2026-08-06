# Persona LinkedIn Scraper — Installation & Integration Guide

This guide provides step-by-step instructions for deploying, configuring, and running the Persona LinkedIn Scraper.


## 1. System Prerequisites

Before starting, ensure your system meets the following requirements:
- **Operating System:** Windows 10/11, macOS, or Linux (Windows is highly recommended as process management and crash recovery are optimized for it).
- **Python:** Python 3.9 or higher.
- **Network:** Unrestricted access to `linkedin.com`.
- **LinkedIn Account:** A valid LinkedIn account is required to authenticate the scraper.


## 2. Installation Steps

### Step 2.1: Clone the Repository
Clone or download the project into a directory (e.g., `Persona`).

### Step 2.2: Create a Virtual Environment (Recommended)
Open a terminal in the project directory and run:
```bash
python -m venv venv

# On Windows:
venv\Scripts\activate

# On Mac/Linux:
source venv/bin/activate
```

### Step 2.3: Install Python Dependencies
Install the required packages using `pip`:
```bash
pip install -r req.txt
```
*(If `req.txt` is unavailable, run: `pip install Flask Flask-CORS playwright requests asyncio`)*

### Step 2.4: Install Playwright Browsers
Playwright requires you to download the headless browser binaries. Run this command:
```bash
playwright install chromium
```
*(This downloads the specific Chromium build required for the scraping engine.)*


## 3. Initial Setup & Authentication

Because LinkedIn requires you to be logged in to view profiles, you must perform a **one-time manual login**.

1. **Start the Application:**
   ```bash
   python app.py
   ```
   The Flask server will start at `http://localhost:5000`.

2. **Access the Admin Dashboard:**
   Open your browser and navigate to: `http://localhost:5000/admin`

3. **Initialize the Browser:**
   Click the **"Initialize Scraper"** button. By default, ensure the "Headless" option is **unchecked** for the first run so you can see the browser window.

4. **Login Manually:**
   - A Chromium window will open.
   - It will navigate to the LinkedIn login page.
   - **Manually enter your credentials and log in** within that Chromium window.
   - Wait until the LinkedIn feed loads completely.

5. **Session Persistence:**
   Once logged in, Playwright automatically saves your cookies and session state into the `browser_data/default/` folder. On all future runs, you can run the scraper in Headless mode, and it will remain authenticated.


## 4. Running the System

### Starting the Server
Always activate your virtual environment, then run:
```bash
python app.py
```

### Using the Task Bucket (Background Scraping)
1. Go to the Admin Dashboard (`http://localhost:5000/admin`).
2. Add tasks via the **Task Bucket** section (by entering Names or LinkedIn URLs).
3. The background worker will automatically process the queue.
4. Adjust the **Rest Period** (e.g., 30-75 seconds) in the config panel to avoid LinkedIn rate-limiting.

### Accessing the Client Portal
End-users can access the read-only search portal at `http://localhost:5000/`.


## 5. Maintenance & Troubleshooting

- **WinError 32 (Lock Files) / Browser Won't Start:** 
  The application includes an auto-kill feature for orphan Chromium processes. If the browser fails to launch due to stale lock files, use the **"Emergency Kill Browser"** button in the Admin UI, or manually run `taskkill /F /IM chrome.exe` in the terminal.
- **Session Expiry:** 
  LinkedIn sessions expire over time. If the scraper suddenly reports "Not Authenticated", run the browser in non-headless mode and log in again.
- **Rate Limiting:** 
  LinkedIn actively monitors for bot behavior. **Do not** set the Task Bucket rest delay to 0. A minimum of 30-45 seconds between scrapes is highly recommended.
