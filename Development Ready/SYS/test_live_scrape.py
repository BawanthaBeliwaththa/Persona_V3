"""
Live End-to-End Scraper Diagnostic
===================================
Runs outside FastAPI/worker system to directly test:
  1. Browser launch
  2. LinkedIn login (credentials from .env)
  3. Search for a known person
  4. Profile extraction
  5. Results printing

Run: python test_live_scrape.py
"""
import asyncio
import sys
import json
import os
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Load .env from same directory
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from core import LinkedInScraper

TEST_NAME     = "Jeff Weiner"           # well-known public figure with rich profile
TEST_FIRST    = "Jeff"
TEST_LAST     = "Weiner"
TEST_COMPANY  = "LinkedIn"
TEST_URL      = "https://www.linkedin.com/in/jeffweiner08"  # fallback direct URL test

async def main():
    email    = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")
    li_at    = os.environ.get("LINKEDIN_LI_AT", "")

    print(f"\n{'='*60}")
    print(f"  PERSONA V3 — Live Diagnostic Test")
    print(f"{'='*60}")
    print(f"  Email   : {email}")
    print(f"  li_at   : {'SET' if li_at else 'NOT SET'}")
    print(f"  Headless: false")
    print(f"{'='*60}\n")

    scraper = LinkedInScraper(headless=False, browser_type="chromium", session_name="test_diag")

    try:
        # ── 1. Initialize browser ────────────────────────────────────────
        print("[STEP 1] Initializing browser...")
        await scraper.initialize()
        print(f"  → is_authenticated after init: {scraper.is_authenticated}")

        # ── 2. Login if not already authenticated ────────────────────────
        if not scraper.is_authenticated:
            print("\n[STEP 2] Logging in...")
            if li_at:
                ok = await scraper.login_with_cookie(li_at)
                print(f"  → Cookie login result: {ok}")
            elif email and password:
                ok = await scraper.login(email, password)
                print(f"  → Credential login result: {ok}")
            else:
                print("  ✗ No credentials found in .env! Add LINKEDIN_EMAIL + LINKEDIN_PASSWORD or LINKEDIN_LI_AT.")
                return
        else:
            print("[STEP 2] Already logged in, skipping login step.")

        print(f"  → is_authenticated: {scraper.is_authenticated}")
        if not scraper.is_authenticated:
            print("  ✗ Authentication FAILED. Check credentials in .env")
            input("  Press Enter to close browser and exit...")
            return

        # ── 3. Test Search ───────────────────────────────────────────────
        print(f"\n[STEP 3] Searching for '{TEST_FIRST} {TEST_LAST}' @ '{TEST_COMPANY}'...")
        search_results = await scraper.search_people(TEST_FIRST, TEST_LAST, TEST_COMPANY, max_results=3)
        print(f"  → Search returned {len(search_results)} result(s)")
        for i, r in enumerate(search_results):
            print(f"    [{i+1}] {r.get('name', '?')} — {r.get('profile_url', '?')}")

        # ── 4. Test Direct URL Extraction ────────────────────────────────
        print(f"\n[STEP 4] Extracting profile directly from URL: {TEST_URL}")
        profile = await scraper.extract_profile(TEST_URL)

        if profile.get("error"):
            print(f"  ✗ Extraction error: {profile['error']}")
        else:
            print(f"  ✔ Extracted: {profile.get('name', '?')}")
            print(f"    Headline  : {profile.get('headline', '')[:80]}")
            print(f"    Location  : {profile.get('location', '')}")
            print(f"    Experience: {len(profile.get('experience', []))} entries")
            print(f"    Education : {len(profile.get('qualifications', []))} entries")
            print(f"    Skills    : {len(profile.get('skills', []))} entries")
            print(f"    Premium   : {profile.get('is_premium', False)}")
            print(f"\n  Full JSON preview:\n  {json.dumps({k:v for k,v in list(profile.items())[:10]}, indent=2)[:800]}")

            # Save result to a local test output file
            out = Path(__file__).parent / "test_output.json"
            out.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\n  Saved full profile to: {out}")

        # ── 5. Search + Extract one result ────────────────────────────────
        if search_results:
            print(f"\n[STEP 5] Extracting first search result: {search_results[0]['profile_url']}")
            p2 = await scraper.extract_profile(search_results[0]['profile_url'])
            if p2.get("error"):
                print(f"  ✗ Error: {p2['error']}")
            else:
                print(f"  ✔ Extracted: {p2.get('name','?')} | {p2.get('headline','')[:60]}")
        else:
            print("\n[STEP 5] Skipped — no search results to extract.")

        print(f"\n{'='*60}")
        print("  Diagnostic complete. Check the console output above.")
        print(f"{'='*60}")

    except Exception as e:
        import traceback
        print(f"\n✗ FATAL ERROR: {e}")
        traceback.print_exc()
    finally:
        input("\n  Press Enter to close browser and exit...")
        await scraper.close()

if __name__ == "__main__":
    asyncio.run(main())
