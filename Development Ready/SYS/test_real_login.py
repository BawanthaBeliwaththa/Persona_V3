import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
from core import LinkedInScraper

async def test():
    email = os.environ.get("LINKEDIN_EMAIL", "nexa.core.official.1@gmail.com")
    password = os.environ.get("LINKEDIN_PASSWORD", "Hello@2026@2026")
    print(f"Testing real credential login for {email} (li_at bypassed)...")
    
    # Temporarily unset LINKEDIN_LI_AT in process env
    os.environ["LINKEDIN_LI_AT"] = ""
    os.environ["LI_AT"] = ""
    
    scraper = LinkedInScraper(headless=False, browser_type="chromium", session_name="real_cred_session")
    await scraper.initialize()
    
    # Call login with li_at="" so it does email + password form fill
    success = await scraper.login(email=email, password=password, li_at="")
    print(f"Login result: success={success}, authenticated={scraper.is_authenticated}, verification_required={scraper.verification_required}")
    print(f"Current page URL: {scraper.page.url}")
    
    if scraper.is_authenticated:
        print("Extracting profile https://www.linkedin.com/in/beliwaththa ...")
        profile = await scraper.extract_profile("https://www.linkedin.com/in/beliwaththa")
        print("Name:", profile.get("name"))
        print("Headline:", profile.get("headline"))
        print("Premium:", profile.get("is_premium"))
        print("Contact Info:", profile.get("contact_info"))
        
    await asyncio.sleep(5)
    await scraper.close()

asyncio.run(test())
