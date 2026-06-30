import json
from typing import Dict, Optional

class LLMParser:
    def __init__(self, use_ai: bool = False, api_key: str = None):
        self.use_ai = use_ai
        self.client = None
        
        if use_ai and api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=api_key)
                print("AI parser initialized")
            except ImportError:
                print("OpenAI package not installed")
                self.use_ai = False
            except Exception as e:
                print(f"Failed to initialize AI parser: {e}")
                self.use_ai = False
    
    def parse_profile_html(self, html: str) -> Optional[Dict]:
        if not self.use_ai or not self.client:
            return None
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "Extract LinkedIn profile data as JSON. Fields: name, headline, location, about, experiences, education, skills. Return only JSON."
                    },
                    {
                        "role": "user",
                        "content": f"Extract from HTML:\n{html[:10000]}"
                    }
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            content = response.choices[0].message.content
            
            try:
                start = content.find('{')
                end = content.rfind('}') + 1
                if start >= 0 and end > start:
                    json_str = content[start:end]
                    return json.loads(json_str)
            except:
                pass
            
            return None
            
        except Exception as e:
            print(f"AI parsing error: {e}")
            return None
