import asyncio
from playwright.async_api import async_playwright

async def debug():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")
        page = await ctx.new_page()
        print("Navigating to https://www.linkedin.com/login ...")
        resp = await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=25000)
        print("URL:", page.url)
        print("Status:", resp.status if resp else "None")
        title = await page.title()
        print("Title:", title)
        
        inputs = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('input, button')).map(el => ({
                tag: el.tagName,
                type: el.type,
                name: el.name,
                id: el.id,
                placeholder: el.placeholder,
                text: el.innerText
            }));
        }''')
        print("Inputs found:", len(inputs))
        for inp in inputs:
            print(" ", inp)
            
        await b.close()

asyncio.run(debug())
