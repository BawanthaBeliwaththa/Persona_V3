# User Acceptance Testing (UAT) Plan - Persona Project

## 1. Overview
User Acceptance Testing will be performed by the intended end-users (Recruiters and Admins) to validate that the Persona platform meets business needs in real-world scenarios.

## 2. UAT Participants
- **System Administrator (1-2 users):** Responsible for UI controls, Task Bucket management, and database exports.
- **Recruitment Analyst (2-3 users):** Responsible for executing searches, reading profile cards, and exporting PDFs.

## 3. UAT Scenarios

### Scenario 1: Bulk Sourcing (Admin)
1. Navigate to the Admin Dashboard.
2. Ensure the scraper is initialized and authenticated.
3. Paste a list of 5 LinkedIn URLs into the Task Bucket.
4. Verify the worker picks them up sequentially.
5. Verify the SSE stream updates the "Pending" and "Completed" counts correctly.
6. **Pass Criteria:** All 5 profiles are scraped successfully without account suspension.

### Scenario 2: Candidate Search (Recruiter)
1. Navigate to the Client Portal.
2. Enter a known candidate's name in the search bar.
3. If the candidate is not in the DB, wait for the background job to finish.
4. Click on the profile card to view the modal.
5. **Pass Criteria:** The modal correctly displays the Experience, Education, and Skills in an easily readable format.

### Scenario 3: Data Export (Recruiter/Analyst)
1. Navigate to a completed profile in the Client Portal.
2. Click "Export PDF".
3. Navigate to the Admin Dashboard.
4. Click "Download Master Database (CSV)".
5. **Pass Criteria:** The PDF generates successfully and is readable. The CSV opens in Excel with correct columns.

## 4. Sign-off
UAT sign-off occurs when all Critical and High severity bugs identified during these scenarios are resolved, and the stakeholders approve the data accuracy.
