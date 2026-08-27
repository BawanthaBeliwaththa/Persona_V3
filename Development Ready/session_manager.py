import pickle
import os
import json
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

class SessionManager:
    def __init__(self, sessions_dir: str = "sessions"):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(exist_ok=True)
    
    def save_session(self, name: str, cookies: List[Dict]) -> bool:
        try:
            session_file = self.sessions_dir / f"{name}.pkl"
            with open(session_file, 'wb') as f:
                pickle.dump({
                    'cookies': cookies,
                    'created_at': datetime.now().isoformat(),
                    'name': name
                }, f)
            print(f"Session saved: {name} ({len(cookies)} cookies)")
            return True
        except Exception as e:
            print(f"Failed to save session: {e}")
            return False
    
    def load_session(self, name: str) -> Optional[List[Dict]]:
        session_file = self.sessions_dir / f"{name}.pkl"
        if session_file.exists():
            try:
                with open(session_file, 'rb') as f:
                    data = pickle.load(f)
                cookies = data.get('cookies', [])
                print(f"Session loaded: {name} ({len(cookies)} cookies)")
                return cookies
            except Exception as e:
                print(f"Failed to load session: {e}")
        return None
    
    def list_sessions(self) -> List[str]:
        sessions = []
        for f in self.sessions_dir.glob("*.pkl"):
            sessions.append(f.stem)
        return sessions
    
    def delete_session(self, name: str) -> bool:
        session_file = self.sessions_dir / f"{name}.pkl"
        if session_file.exists():
            session_file.unlink()
            return True
        return False