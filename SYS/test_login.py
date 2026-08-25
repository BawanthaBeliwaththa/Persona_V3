import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from core import LinkedInScraper

async def test():
    email = os.environ.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD", "")
    print(f"Testing credential login for {email}...")
    
    # Launch scraper without the bad li_at cookie
    scraper = LinkedInScraper(headless=False, browser_type="chromium", session_name="test_login_session")
    await scraper.initialize()
    
    # Attempt login
    success = await scraper.login(email=email, password=password)
    print(f"Login success: {success}, Authenticated: {scraper.is_authenticated}, Verification required: {scraper.verification_required}")
    
    if scraper.is_authenticated:
        print("Scraping profile: https://www.linkedin.com/in/beliwaththa ...")
        profile = await scraper.extract_profile("https://www.linkedin.com/in/beliwaththa")
        print("Name:", profile.get("name"))
        print("Headline:", profile.get("headline"))
        print("Premium:", profile.get("is_premium"))
        print("Contact Info:", profile.get("contact_info"))
        
    await scraper.close()

asyncio.run(test())
