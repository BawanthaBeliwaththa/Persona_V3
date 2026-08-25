import asyncio
import os
import sys
from dotenv import load_dotenv
load_dotenv()
from playwright.async_api import async_playwright
import urllib.request

li_at = os.environ.get("LINKEDIN_LI_AT", "").strip()

async def test_auth():
    print(f"LI_AT (len={len(li_at)}): {li_at[:25]}...{li_at[-10:]}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Test A: Unauthenticated public profile view
        print("\n--- Test A: Guest/Public profile view ---")
        ctx_guest = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            locale="en-US"
        )
        p_guest = await ctx_guest.new_page()
        try:
            res = await p_guest.goto("https://www.linkedin.com/in/beliwaththa", wait_until="domcontentloaded", timeout=25000)
            print(f"Guest Status: {res.status if res else 'None'}, URL: {p_guest.url}")
            title = await p_guest.title()
            print(f"Guest Title: {title}")
            h1 = await p_guest.evaluate("() => document.querySelector('h1')?.innerText")
            print(f"Guest H1: {h1}")
        except Exception as e:
            print(f"Guest Error: {e}")
        await ctx_guest.close()

        # Test B: With li_at cookie and JSESSIONID
        print("\n--- Test B: With li_at + JSESSIONID ---")
        ctx_auth = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            locale="en-US"
        )
        cookies = [
            {"name": "li_at", "value": li_at, "domain": ".linkedin.com", "path": "/", "httpOnly": True, "secure": True},
            {"name": "JSESSIONID", "value": '"ajax:0000000000000000000"', "domain": ".linkedin.com", "path": "/", "secure": True},
            {"name": "bcookie", "value": '"v=2&00000000-0000-0000-0000-000000000000"', "domain": ".linkedin.com", "path": "/", "secure": True}
        ]
        await ctx_auth.add_cookies(cookies)
        p_auth = await ctx_auth.new_page()
        try:
            res = await p_auth.goto("https://www.linkedin.com/in/beliwaththa", wait_until="domcontentloaded", timeout=25000)
            print(f"Auth Status: {res.status if res else 'None'}, URL: {p_auth.url}")
            title = await p_auth.title()
            print(f"Auth Title: {title}")
            h1 = await p_auth.evaluate("() => document.querySelector('h1')?.innerText")
            print(f"Auth H1: {h1}")
        except Exception as e:
            print(f"Auth Error: {e}")
        await ctx_auth.close()

        await browser.close()

asyncio.run(test_auth())
