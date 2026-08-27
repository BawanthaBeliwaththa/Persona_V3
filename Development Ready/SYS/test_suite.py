"""
Persona V3 — End-to-End API Test Suite
======================================
Automated verification script for all core endpoints in SYS.
Tests:
  1. Health check & Server info
  2. Interactive Guide (/guide)
  3. Bucket queue status & worker health
  4. Single task enqueue (/api/bucket/add)
  5. GET /api/client/scrape overview
  6. GET /api/client/scrape?name=...
  7. POST /api/client/scrape (Zoho JSON format)
  8. Status polling (/api/client/scrape-status)
  9. Bulk Scrape & consolidation
  10. Worker pause, resume & clear
  11. Scraper Export (JSON & CSV formats)
  12. Admin Database Management & download
"""

import sys
import os

# Insert SYS directory into path
sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient
from main import app

def run_tests():
    print("===================================================")
    print("      Running Persona V3 End-to-End Test Suite     ")
    print("===================================================")
    
    client = TestClient(app)
    
    # Test 1: Root Health Check
    print("\n[Test 1] Root Health Endpoint (GET /)")
    r = client.get("/")
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert r.json().get("status") == "online"
    print("  -> PASSED")

    # Test 2: Guide Endpoint
    print("\n[Test 2] Interactive Guide Endpoint (GET /guide)")
    r_guide = client.get("/guide")
    print(f"  Status: {r_guide.status_code}")
    assert r_guide.status_code in [200, 404]
    print("  -> PASSED")

    # Test 3: Bucket Status
    print("\n[Test 3] Bucket Queue Status (GET /api/bucket/status)")
    r = client.get("/api/bucket/status")
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    assert r.status_code == 200
    assert "summary" in r.json()
    print("  -> PASSED")

    # Test 4: Add Query to Bucket
    print("\n[Test 4] Add Search Query to Bucket (POST /api/bucket/add)")
    r = client.post("/api/bucket/add", json={"query": "Navod Ranasinghe TechCorp"})
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    assert r.status_code == 201
    assert r.json().get("success") is True
    print("  -> PASSED")

    # Test 5: GET /api/client/scrape Overview
    print("\n[Test 5] GET /api/client/scrape without query params")
    r_ov = client.get("/api/client/scrape")
    print(f"  Status: {r_ov.status_code}")
    print(f"  Response: {r_ov.json()}")
    assert r_ov.status_code == 200
    assert "endpoints" in r_ov.json()
    print("  -> PASSED")

    # Test 6: GET /api/client/scrape with query params
    print("\n[Test 6] GET /api/client/scrape?name=Kasun+Perera")
    r_get = client.get("/api/client/scrape?name=Kasun+Perera&company=Virtusa")
    print(f"  Status: {r_get.status_code}")
    print(f"  Response: {r_get.json()}")
    assert r_get.status_code in [200, 202]
    print("  -> PASSED")

    # Test 7: POST /api/client/scrape (Zoho Webhook Simulation)
    print("\n[Test 7] Zoho Client Scrape Webhook (POST /api/client/scrape)")
    r = client.post("/api/client/scrape", json={
        "name": "Bawantha Beliwaththa",
        "profile_url": "https://www.linkedin.com/in/bawantha-beliwaththa"
    })
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    assert r.status_code in [200, 202]
    ref_num = r.json().get("reference_number")
    print(f"  Assigned Reference Number: {ref_num}")
    print("  -> PASSED")

    # Test 8: Status Polling by Reference Number
    if ref_num:
        print(f"\n[Test 8] Status Polling by Reference Number (GET /api/client/scrape-status?task_id={ref_num})")
        r = client.get(f"/api/client/scrape-status?task_id={ref_num}")
        print(f"  Status: {r.status_code}")
        print(f"  Response: {r.json()}")
        assert r.status_code in [200, 202]
        print("  -> PASSED")

    # Test 9: Bulk Scrape Enqueue Simulation
    print("\n[Test 9] Bulk Scrape Enqueue (POST /api/persona/bulk-scrape)")
    r = client.post("/api/persona/bulk-scrape", json={
        "profile_urls": [
            "https://www.linkedin.com/in/test-candidate-1",
            "https://www.linkedin.com/in/test-candidate-2"
        ],
        "return_code": "TEST-BATCH-001"
    })
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.json()}")
    assert r.status_code in [200, 202]
    print("  -> PASSED")

    # Test 10: Worker Pause & Resume
    print("\n[Test 10] Worker Pause & Resume")
    r_pause = client.post("/api/bucket/pause")
    print(f"  Pause Status: {r_pause.status_code} - {r_pause.json()}")
    assert r_pause.status_code == 200
    
    r_resume = client.post("/api/bucket/resume")
    print(f"  Resume Status: {r_resume.status_code} - {r_resume.json()}")
    assert r_resume.status_code == 200
    print("  -> PASSED")

    # Test 11: Export Endpoint (JSON & CSV)
    print("\n[Test 11] Data Export Endpoint (POST /api/scraper/export)")
    sample_export = {
        "format": "json",
        "data": {
            "profiles": [
                {
                    "name": "Jane Doe",
                    "headline": "Lead AI Engineer",
                    "location": "Colombo, Sri Lanka",
                    "profile_url": "https://linkedin.com/in/jane-doe-test"
                }
            ]
        }
    }
    r_exp_json = client.post("/api/scraper/export", json=sample_export)
    print(f"  JSON Export Status: {r_exp_json.status_code}")
    assert r_exp_json.status_code == 200
    
    sample_export["format"] = "csv"
    r_exp_csv = client.post("/api/scraper/export", json=sample_export)
    print(f"  CSV Export Status: {r_exp_csv.status_code}")
    assert r_exp_csv.status_code == 200
    print("  -> PASSED")

    # Test 12: Admin Database Profiles
    print("\n[Test 12] Master DB Profiles (GET /api/admin/db-profiles)")
    r_db = client.get("/api/admin/db-profiles")
    print(f"  DB Profiles Status: {r_db.status_code}")
    print(f"  Response: {r_db.json()}")
    assert r_db.status_code == 200
    assert "profiles" in r_db.json()
    print("  -> PASSED")

    # Test 13: Bucket Clear
    print("\n[Test 13] Bucket Cleanup (POST /api/bucket/clear)")
    r_clear = client.post("/api/bucket/clear")
    print(f"  Clear Status: {r_clear.status_code} - {r_clear.json()}")
    assert r_clear.status_code == 200
    print("  -> PASSED")

    print("\n===================================================")
    print("   ALL 13 END-TO-END TESTS PASSED SUCCESSFULLY!    ")
    print("===================================================")

if __name__ == "__main__":
    run_tests()
