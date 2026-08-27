import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from playwright.async_api import async_playwright

email = os.environ.get("LINKEDIN_EMAIL", "nexa.core.official.1@gmail.com")
password = os.environ.get("LINKEDIN_PASSWORD", "Hello@2026@2026")

async def test():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")
        page = await ctx.new_page()
        print("Navigating to https://www.linkedin.com/login ...")
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(2)
        
        # Find visible inputs
        all_emails = await page.query_selector_all('input[type="email"], input[type="text"], input:not([type="hidden"]):not([type="checkbox"])')
        email_inp = None
        for inp in all_emails:
            if await inp.is_visible():
                email_inp = inp
                break
                
        if email_inp:
            await email_inp.fill(email)
            print("Filled visible email input.")
            
        all_passes = await page.query_selector_all('input[type="password"]')
        pass_inp = None
        for inp in all_passes:
            if await inp.is_visible():
                pass_inp = inp
                break
                
        if pass_inp:
            await pass_inp.fill(password)
            print("Filled visible password input.")
            
        # Click Sign In
        all_btns = await page.query_selector_all('button')
        sign_btn = None
        for btn in all_btns:
            text = (await btn.inner_text()).strip().lower()
            if 'sign in' in text and await btn.is_visible():
                sign_btn = btn
                break
                
        if sign_btn:
            await sign_btn.click()
            print("Clicked Sign in button.")
        else:
            await page.keyboard.press("Enter")
            print("Pressed Enter.")
            
        print("Waiting 12s to see landing page...")
        await asyncio.sleep(12)
        print("Landed URL:", page.url)
        print("Page Title:", await page.title())
        
        cookies = await ctx.cookies()
        li_at_cookie = next((c for c in cookies if c['name'] == 'li_at'), None)
        if li_at_cookie:
            print("SUCCESS! Fresh li_at cookie:")
            print(li_at_cookie['value'])
        else:
            print("No li_at cookie yet (checkpoint/CAPTCHA challenge).")
            
        await b.close()

asyncio.run(test())
