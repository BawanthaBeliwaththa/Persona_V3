import urllib.request
import json
import re
from bs4 import BeautifulSoup

url = 'https://www.linkedin.com/in/beliwaththa'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Sec-Ch-Ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1'
}

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"Status: {resp.status}")
        html = resp.read().decode('utf-8', errors='ignore')
        print(f"HTML Length: {len(html)}")
        soup = BeautifulSoup(html, 'html.parser')
        print(f"Title: {soup.title.string if soup.title else 'No Title'}")
        
        # Extract JSON-LD data
        for s in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(s.string)
                print("JSON-LD found:")
                print(json.dumps(data, indent=2))
            except Exception as je:
                pass
except urllib.error.HTTPError as e:
    print(f"HTTPError: {e.code}")
    for k, v in e.headers.items():
        print(f"  {k}: {v}")
except Exception as ex:
    print(f"Exception: {ex}")
