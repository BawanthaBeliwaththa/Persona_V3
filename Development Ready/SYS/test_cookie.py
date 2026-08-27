"""
Quick standalone test: verifies li_at cookie can reach a LinkedIn profile.
Run with: python test_cookie.py
"""
import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from dotenv import load_dotenv
load_dotenv()

LI_AT = os.environ.get("LINKEDIN_LI_AT", "").strip()
TEST_URL = "https://www.linkedin.com/in/beliwaththa"

async def main():
    if not LI_AT:
        print("ERROR: LINKEDIN_LI_AT not set in .env")
        return

    print(f"Testing li_at cookie: {LI_AT[:30]}...")
    print(f"Target URL: {TEST_URL}")
    print()

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        # Use a persistent context so we keep cookies between navigations
        context = await p.chromium.launch_persistent_context(
            "browser_data/cookie_test",
            headless=False,  # show browser so you can see what's happening
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # Anti-detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
        """)

        # STEP 1: Prime the domain
        print("[1] Navigating to linkedin.com to prime domain context...")
        try:
            await page.goto("https://www.linkedin.com", wait_until="commit", timeout=20000)
            print(f"    Landed at: {page.url}")
        except Exception as e:
            print(f"    Notice (non-fatal): {e}")
        await asyncio.sleep(2)

        # STEP 2: Inject li_at cookie
        print("[2] Injecting li_at cookie...")
        cookie_val = LI_AT
        if 'li_at=' in cookie_val:
            cookie_val = cookie_val.split('li_at=')[1].split(';')[0].strip()

        await context.add_cookies([
            {'name': 'li_at', 'value': cookie_val, 'domain': '.linkedin.com',     'path': '/', 'httpOnly': True, 'secure': True},
            {'name': 'li_at', 'value': cookie_val, 'domain': '.www.linkedin.com', 'path': '/', 'httpOnly': True, 'secure': True},
        ])
        print("    Cookie injected.")

        # STEP 3: Reload to activate the cookie
        print("[3] Reloading page to activate session...")
        try:
            await page.reload(wait_until="commit", timeout=20000)
            await asyncio.sleep(2)
            print(f"    After reload URL: {page.url}")
        except Exception as e:
            print(f"    Notice (non-fatal): {e}")

        # Check if we're authenticated
        cur = page.url
        if any(bad in cur for bad in ['login', 'authwall', 'uas/authenticate', 'checkpoint']):
            print()
            print("❌ COOKIE IS EXPIRED OR INVALID.")
            print(f"   Landed on: {cur}")
            print("   Fix: Get a fresh li_at cookie from your browser:")
            print("   1. Open Chrome, log into LinkedIn")
            print("   2. Press F12 → Application → Cookies → www.linkedin.com")
            print("   3. Copy the 'li_at' cookie value")
            print("   4. Paste it into SYS/.env as LINKEDIN_LI_AT=<value>")
            await context.close()
            return

        print(f"   ✅ Session active! URL: {cur}")
        print()

        # STEP 4: Navigate to the actual profile
        print(f"[4] Navigating to profile: {TEST_URL}")
        try:
            await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
        except Exception as e:
            print(f"    Navigation notice: {e}")

        final_url = page.url
        print(f"    Final URL: {final_url}")

        if any(bad in final_url for bad in ['login', 'authwall', 'checkpoint']):
            print("❌ Profile navigation redirected to auth page. Cookie may be expired.")
        elif '/in/' in final_url:
            # Try to read the name
            try:
                name = await page.evaluate("() => document.querySelector('h1')?.innerText?.trim() || 'unknown'")
                print(f"✅ SUCCESS! Profile loaded. Name: {name}")
            except Exception:
                print("✅ Profile page loaded (could not read name).")
        else:
            print(f"⚠️  Unexpected landing page: {final_url}")

        print()
        print("Browser will stay open for 10 seconds so you can inspect...")
        await asyncio.sleep(10)
        await context.close()

asyncio.run(main())
