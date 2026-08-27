import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from playwright.async_api import async_playwright

li_at = os.environ.get("LINKEDIN_LI_AT", "").strip()
if "li_at=" in li_at:
    li_at = li_at.split("li_at=")[1].split(";")[0].strip()

async def test():
    async with async_playwright() as p:
        # Launch real Google Chrome with stealth flags
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
            ]
        )
        
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )
        
        # Comprehensive evasion script
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        
        if li_at:
            await ctx.add_cookies([
                {"name": "li_at", "value": li_at, "domain": ".linkedin.com", "path": "/", "httpOnly": True, "secure": True},
                {"name": "bcookie", "value": '"v=2&11111111-2222-3333-4444-555555555555"', "domain": ".linkedin.com", "path": "/", "secure": True}
            ])
            print(f"Injected li_at ({len(li_at)} chars)...")
            
        page = await ctx.new_page()
        
        target = "https://www.linkedin.com/in/beliwaththa"
        print(f"Navigating to {target}...")
        try:
            resp = await page.goto(target, wait_until="domcontentloaded", timeout=30000)
            print(f"Status: {resp.status if resp else 'N/A'}")
            print(f"Page URL: {page.url}")
            print(f"Page Title: {await page.title()}")
            
            # Check content
            h1 = await page.evaluate("() => document.querySelector('h1')?.innerText")
            print(f"H1 Header: {h1}")
            
            sub = await page.evaluate("() => document.querySelector('.text-body-medium')?.innerText")
            print(f"Headline: {sub}")
            
            is_premium = await page.evaluate("() => !!document.querySelector('.pv-member-badge--premium, svg.premium-icon, [data-test-premium-icon]')")
            print(f"Is Premium: {is_premium}")
            
            # Check body length
            body_len = await page.evaluate("() => document.body.innerText.length")
            print(f"Body Text Length: {body_len} chars")
            
        except Exception as e:
            print(f"Navigation error: {e}")
            
        await browser.close()

asyncio.run(test())
