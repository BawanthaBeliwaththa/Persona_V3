
        let state = { initialized: false, authenticated: false, currentProfiles: [], stats: { searches: 0, profiles: 0 } };
        let settings = { headless: false, browserType: 'chromium' };

        function escapeHtml(text) { if (!text) return ''; const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }
        function showToast(msg, type) { const container = document.getElementById('toastContainer'); const toast = document.createElement('div'); toast.className = 'toast'; toast.style.borderLeftColor = type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'; toast.innerHTML = `<span>${msg}</span>`; container.appendChild(toast); setTimeout(() => toast.remove(), 4000); }
        function showAlert(elId, msg, type) { const el = document.getElementById(elId); if (el) el.innerHTML = `<div class="alert alert-${type}">${msg}</div>`; setTimeout(() => { if (el.querySelector('.alert')) el.innerHTML = ''; }, 5000); }
        function updateUIState() {
            document.getElementById('btnInit').disabled = state.initialized;
            document.getElementById('btnLogin').disabled = !state.initialized || state.authenticated;
            document.getElementById('btnClose').disabled = !state.initialized;
            // Search bucket button is always enabled — queueing doesn't need auth
            const btn = document.getElementById('btnSearchExtract');
            if (btn) btn.disabled = false;
        }
        function switchTab(tab) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            document.getElementById(tab + 'Tab').classList.add('active');
            // Find the matching tab button by data or text
            const allTabBtns = Array.from(document.querySelectorAll('.tab-btn'));
            const match = allTabBtns.find(btn => {
                const txt = (btn.textContent || '').toLowerCase().trim();
                return txt.startsWith(tab.toLowerCase());
            });
            if (match) match.classList.add('active');
            state.activeTab = tab;
            if (tab === 'approvals') { loadApprovals(); }
            else if (tab === 'search') { loadPendingScrapes(); }
            else if (tab === 'bucket') { loadBucketStatus(); }
        }

        async function initializeScraper() {
            const btn = document.getElementById('btnInit'); btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Initializing...';
            showAlert('setupStatus', 'Initializing browser...', 'info');
            try {
                const res = await fetch('/api/scraper/init', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ headless: settings.headless, browser_type: settings.browserType, session_name: document.getElementById('sessionName').value }) });
                const data = await res.json();
                if (data.success) { state.initialized = true; showToast('Browser initialized', 'success'); showAlert('setupStatus', '✅ Browser ready', 'success'); }
                else {
                    showAlert('setupStatus', '❌ Init failed: ' + data.error, 'error');
                    // If init failed due to a locked profile, suggest using Force Kill
                    if (data.error && (data.error.includes('locked') || data.error.includes('another process'))) {
                        showAlert('setupStatus', '💡 Tip: Click "Force Kill Browser" to close stale Chromium processes, then try again.', 'info');
                    }
                }
            } catch (e) { showAlert('setupStatus', 'Error: ' + e.message, 'error'); }
            finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-play"></i> Initialize Browser'; updateUIState(); }
        }
        async function killBrowser() {
            const btn = document.getElementById('btnKill'); btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Killing...';
            showAlert('setupStatus', 'Force-killing browser processes...', 'info');
            try {
                const res = await fetch('/api/scraper/kill-browser', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    state.initialized = false; state.authenticated = false;
                    showToast('Browser processes terminated', 'success');
                    showAlert('setupStatus', '✅ All browser processes killed. You can now Initialize again.', 'success');
                } else {
                    showAlert('setupStatus', '❌ Kill failed: ' + data.error, 'error');
                }
            } catch (e) { showAlert('setupStatus', 'Error: ' + e.message, 'error'); }
            finally { btn.disabled = false; btn.innerHTML = '<i class="fas fa-skull"></i> Force Kill Browser'; updateUIState(); }
        }

        async function loginToLinkedIn() {
            const email = document.getElementById('email').value.trim(), pwd = document.getElementById('password').value;
            if (!email || !pwd) { showAlert('setupStatus', 'Enter email and password', 'warning'); return; }
            const btn = document.getElementById('btnLogin'); btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Logging in...';
            try {
                const res = await fetch('/api/scraper/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: pwd }) });
                const data = await res.json();
                if (data.success) { state.authenticated = true; showToast('Login successful', 'success'); showAlert('setupStatus', 'Logged in', 'success'); }
                else { showAlert('setupStatus', 'Login failed', 'error'); }
            } catch (e) { showAlert('setupStatus', 'Error: ' + e.message, 'error'); }
            finally { btn.disabled = false; btn.innerHTML = 'Login'; updateUIState(); }
        }
        async function closeScraper() { await fetch('/api/scraper/close', { method: 'POST' }); state.initialized = false; state.authenticated = false; updateUIState(); clearResults(); showToast('Scraper closed', 'info'); }
        function clearResults() { state.currentProfiles = []; document.getElementById('resultsContainer').innerHTML = 'No results.'; document.getElementById('profileDetail').innerHTML = ''; showToast('Results cleared', 'info'); }
        async function exportData(format) { if (!state.currentProfiles.length) { showToast('No data to export', 'warning'); return; } try { const res = await fetch('/api/scraper/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data: { profiles: state.currentProfiles }, format }) }); if (res.ok) { const blob = await res.blob(); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `linkedin_export.${format}`; a.click(); URL.revokeObjectURL(url); showToast(`Exported as ${format}`, 'success'); } else { showToast('Export failed', 'error'); } } catch (e) { showToast('Export error: ' + e.message, 'error'); } }
        async function exportFullTextAsPDF() {
            if (!state.currentProfiles.length) { showToast('No profiles to export', 'warning'); return; }
            let content = '';
            state.currentProfiles.forEach((p, i) => {
                content += `PROFILE ${i + 1}: ${p.name || 'Unknown'}
URL: ${p.profile_url || 'N/A'}
Headline: ${p.headline || 'N/A'}
Location: ${p.location || 'N/A'}
Connections: ${p.connections || 'N/A'}
Scraped At: ${p.scraped_at || 'N/A'}

--- ABOUT ---
${p.about || 'N/A'}

--- CURRENT POSITION ---
Title: ${p.current_job?.title || 'N/A'}
Company: ${p.current_job?.company || 'N/A'}
Duration: ${p.current_job?.duration || 'N/A'}
Location: ${p.current_job?.location || 'N/A'}

--- WORK EXPERIENCE ---
${(p.experience || []).map((e, j) => `${j+1}. ${e.title || ''} at ${e.company || ''} | ${e.duration || ''} | ${e.location || ''}`).join('\n') || 'N/A'}

--- EDUCATION ---
${(p.qualifications || []).map((q, j) => `${j+1}. ${q.institution} - ${q.degree} (${q.dates})`).join('\n') || 'N/A'}

--- CERTIFICATIONS ---
${(p.certifications || []).map((c, j) => `${j+1}. ${c.name} | ${c.issuer} | ${c.date}`).join('\n') || 'N/A'}

--- SKILLS ---
${(p.skills || []).map(s => `${s.skill}${s.endorsements ? ' (' + s.endorsements + ')' : ''}`).join(', ') || 'N/A'}

--- LANGUAGES ---
${(p.languages || []).map(l => `${l.language}${l.proficiency ? ' - ' + l.proficiency : ''}`).join(', ') || 'N/A'}

--- VOLUNTEER EXPERIENCE ---
${(p.volunteer || []).map((v, j) => `${j+1}. ${v.role} at ${v.organization} | ${v.duration || ''}`).join('\n') || 'N/A'}

--- HONORS & AWARDS ---
${(p.honors || []).map((h, j) => `${j+1}. ${h.title} | ${h.issuer} | ${h.date}`).join('\n') || 'N/A'}

--- RECOMMENDATIONS ---
${(p.recommendations || []).map((r, j) => `${j+1}. From: ${r.recommender}\n   Title: ${r.title}\n   "${r.text}"`).join('\n\n') || 'N/A'}

${'='.repeat(80)}

`;
            });
            try {
                const res = await fetch('/api/export-text-pdf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: content }) });
                if (res.ok) { const blob = await res.blob(); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `linkedin_full_profile.pdf`; a.click(); URL.revokeObjectURL(url); showToast('PDF exported successfully', 'success'); }
                else { showToast('Export failed', 'error'); }
            } catch (e) { showToast('Export error: ' + e.message, 'error'); }
        }

        // ── NEW: Add search to bucket instead of scraping directly ──
        async function addSearchToBucket() {
            const username   = document.getElementById('usernameKeyword').value.trim();
            let firstName    = document.getElementById('firstName').value.trim();
            let lastName     = document.getElementById('lastName').value.trim();
            const company    = document.getElementById('company').value.trim();
            const maxResults = parseInt(document.getElementById('maxResults').value) || 5;

            // If username field has a URL, add directly as URL task
            if (username && (username.startsWith('http') || username.startsWith('linkedin.com'))) {
                const url = username.startsWith('http') ? username : 'https://' + username;
                const res = await fetch('/api/bucket/add', {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ queries: [url] })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(`✅ URL task added to bucket`, 'success');
                    showAlert('searchStatus', '✅ Added to Task Bucket — the worker will scrape it automatically.', 'success');
                    document.getElementById('usernameKeyword').value = '';
                    switchTab('bucket');
                } else showToast('Error: ' + data.error, 'error');
                return;
            }

            // Name-based: use username as firstName if provided
            if (username) { firstName = username; lastName = ''; }
            
            const contactEmail = document.getElementById('contactEmail').value.trim();
            const contactPhone = document.getElementById('contactPhone').value.trim();

            if (contactEmail || contactPhone) {
                const btn = document.getElementById('btnSearchExtract');
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner spin"></i> Searching...';
                try {
                    const res = await fetch('/api/scraper/search-contact-info', {
                        method: 'POST', headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({ email: contactEmail, phone: contactPhone })
                    });
                    const data = await res.json();
                    if (res.status === 403 && data.error === 'PREMIUM_REQUIRED') {
                        showAlert('searchStatus', `⚠️ ${data.message}`, 'warning');
                    } else if (data.success) {
                        showToast(`Found ${data.total} contact matches`, 'success');
                        if (data.results && data.results.length > 0) {
                            // Automatically add the first profile URL to bucket
                            const url = data.results[0].profile_url;
                            await fetch('/api/bucket/add', {
                                method: 'POST', headers: {'Content-Type':'application/json'},
                                body: JSON.stringify({ queries: [url] })
                            });
                            showAlert('searchStatus', '✅ Found contact and added to Task Bucket.', 'success');
                            switchTab('bucket');
                        } else {
                            showAlert('searchStatus', 'No matches found for that contact info.', 'info');
                        }
                    } else {
                        showAlert('searchStatus', 'Error: ' + data.error, 'error');
                    }
                } catch(e) {
                    showAlert('searchStatus', 'Network error: ' + e.message, 'error');
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-layer-group"></i> Add to Task Bucket';
                }
                return;
            }

            if (!firstName && !lastName) {
                showAlert('searchStatus', 'Enter a name, username, LinkedIn URL, or Contact Info', 'warning');
                return;
            }

            const btn = document.getElementById('btnSearchExtract');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner spin"></i> Adding…';
            try {
                const res = await fetch('/api/bucket/add-search', {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ first_name: firstName, last_name: lastName, company, max_results: maxResults })
                });
                const data = await res.json();
                if (data.success) {
                    const label = [firstName, lastName].filter(Boolean).join(' ') + (company ? ` @ ${company}` : '');
                    showToast(`✅ "${label}" added to Task Bucket`, 'success');
                    showAlert('searchStatus', `✅ Added to Task Bucket — the worker will search & scrape automatically. <a href="#" onclick="switchTab('bucket');return false;" style="color:#1d4ed8;font-weight:600;">Watch progress →</a>`, 'success');
                    // Clear inputs
                    ['usernameKeyword','firstName','lastName','company'].forEach(id => {
                        const el = document.getElementById(id); if (el) el.value = '';
                    });
                    // Auto-switch to bucket tab after 1.2s
                    setTimeout(() => switchTab('bucket'), 1200);
                } else {
                    showAlert('searchStatus', 'Error: ' + data.error, 'error');
                }
            } catch(e) {
                showAlert('searchStatus', 'Network error: ' + e.message, 'error');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-layer-group"></i> Add to Task Bucket';
            }
        }

        // Legacy direct-scrape (kept for internal admin use but not shown in UI)
        async function searchAndExtract() {
            return addSearchToBucket();
        }

        // Bulk Upload
        async function bucketUploadFile() {
            const fileInput = document.getElementById('bucketUploadFile');
            if (!fileInput.files.length) {
                showToast('Please select a file first', 'warning');
                return;
            }
            const file = fileInput.files[0];
            const formData = new FormData();
            formData.append('file', file);
            
            showToast('Uploading file...', 'info');
            try {
                const res = await fetch('/api/bucket/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    fileInput.value = ''; // Reset input
                    loadBucketStatus(); // Refresh bucket UI
                } else {
                    showToast('Upload error: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('Network error: ' + e.message, 'error');
            }
        }


        function displayExtractedProfiles(profiles) {
            const container = document.getElementById('resultsContainer');
            if (!profiles.length) { container.innerHTML = '<p>No extracted profiles.</p>'; return; }
            
            let html = `
                <table style="width: 100%; border-collapse: collapse; text-align: left; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); color:#1f2937; margin-bottom: 20px;">
                    <thead>
                        <tr style="background: #f3f4f6; border-bottom: 2px solid #e5e7eb;">
                            <th style="padding: 12px 16px; font-weight:600; font-size:14px; width:60px;">Profile</th>
                            <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Name</th>
                            <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Headline / Job Title</th>
                            <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Company</th>
                            <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Location</th>
                            <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Scraped At</th>
                            <th style="padding: 12px 16px; font-weight:600; font-size:14px; text-align:center;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            
            profiles.forEach((p, idx) => {
                const jobTitle = p.current_job ? (p.current_job.title || 'N/A') : 'N/A';
                const company = p.current_job ? (p.current_job.company || 'N/A') : 'N/A';
                const scrapedAt = p.scraped_at ? new Date(p.scraped_at).toLocaleString() : 'N/A';
                
                const initials = (p.name || '?').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
                const avatarHtml = p.profile_picture 
                    ? `<img src="${escapeHtml(p.profile_picture)}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;border:2px solid #0a66c2;">`
                    : `<div style="width:40px;height:40px;border-radius:50%;background: linear-gradient(135deg, #0a66c2, #004182);color:white;display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:14px;">${initials}</div>`;
                
                html += `
                    <tr style="border-bottom: 1px solid #f3f4f6;">
                        <td style="padding: 12px 16px; text-align:center;">${avatarHtml}</td>
                        <td style="padding: 12px 16px; font-weight:600; color:#111827;">${escapeHtml(p.name || 'Unknown')}</td>
                        <td style="padding: 12px 16px; font-size:13px;">${escapeHtml(jobTitle)}</td>
                        <td style="padding: 12px 16px; font-size:13px; color:#4b5563;">${escapeHtml(company)}</td>
                        <td style="padding: 12px 16px; font-size:13px; color:#4b5563;">${escapeHtml(p.location || 'N/A')}</td>
                        <td style="padding: 12px 16px; font-size:13px; color:#6b7280;">${scrapedAt}</td>
                        <td style="padding: 12px 16px; text-align:center;">
                            <div style="display:flex; gap:8px; justify-content:center; align-items:center;">
                                <button class="btn btn-primary" style="padding:4px 8px; font-size:12px; border-radius:4px; margin:0;" onclick="showProfileDetail(${idx})">View Details</button>
                                <button class="btn btn-outline" style="padding:4px 8px; font-size:12px; border-radius:4px; margin:0;" onclick="exportDataSingle(${idx}, 'json')">JSON</button>
                                <button class="btn btn-outline" style="padding:4px 8px; font-size:12px; border-radius:4px; margin:0; border-color:#ef4444; color:#ef4444;" onclick="exportFullTextAsPDFSingle(${idx})">PDF</button>
                            </div>
                        </td>
                    </tr>
                `;
            });
            html += '</tbody></table>';
            container.innerHTML = html;
        }
        function showProfileDetail(index) {
            state.activeProfileIndex = index;
            const p = state.currentProfiles[index];
            if (!p) return;
            const detailDiv = document.getElementById('profileDetail');
            let html = `<div style="text-align:center;">${p.profile_picture ? `<img src="${p.profile_picture}" class="profile-pic">` : `<div style="width:100px;height:100px;border-radius:50%;background:#0a66c2;color:white;display:flex;align-items:center;justify-content:center;font-size:32px;margin:0 auto 12px;">${(p.name?.[0] || '?')}</div>`}</div>`;
            html += `<h2>${escapeHtml(p.name || 'Unknown')}</h2>`;
            if (p.headline) html += `<p style="color:#555;font-size:15px;margin-top:4px;">${escapeHtml(p.headline)}</p>`;
            if (p.location) html += `<p style="color:#888;font-size:14px;"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(p.location)}</p>`;
            if (p.connections) html += `<p style="color:#888;font-size:13px;margin-top:2px;"><i class="fas fa-users"></i> ${escapeHtml(p.connections)}</p>`;
            if (p.profile_url) html += `<p style="margin-top:4px;"><a href="${escapeHtml(p.profile_url)}" target="_blank" style="color:#0a66c2;"><i class="fab fa-linkedin"></i> View on LinkedIn</a></p>`;

            // About
            if (p.about) {
                html += `<div class="section-title" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fas fa-user"></i> About</span>
                            <button class="btn-json-toggle" onclick="toggleAdminSectionJson('about', this)" style="background:rgba(10,102,194,0.1); border:1px solid rgba(10,102,194,0.3); color:#0a66c2; font-size:12px; cursor:pointer; font-weight:600; padding:2px 8px; border-radius:4px;"><i class="fas fa-code"></i> JSON</button>
                         </div>`;
                html += `<div class="full-text-box" style="max-height:200px;">${escapeHtml(p.about)}</div>`;
                html += `<pre class="section-json-box" id="aboutJson" style="display:none; background:#f3f4f6; border:1px solid #e5e7eb; padding:12px; border-radius:10px; font-family:monospace; font-size:12px; color:#1e1b4b; margin-top:10px; white-space:pre-wrap; overflow-x:auto;"></pre>`;
            }

            // Contact Info
            if (p.contact_info && Object.keys(p.contact_info).length > 0) {
                html += `<div class="section-title" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fas fa-address-book"></i> Contact Info</span>
                            <button class="btn-json-toggle" onclick="toggleAdminSectionJson('contact_info', this)" style="background:rgba(10,102,194,0.1); border:1px solid rgba(10,102,194,0.3); color:#0a66c2; font-size:12px; cursor:pointer; font-weight:600; padding:2px 8px; border-radius:4px;"><i class="fas fa-code"></i> JSON</button>
                         </div>`;
                html += `<div style="background:#fefce8;padding:14px;border-radius:10px;border-left:4px solid #eab308;margin-bottom:12px;">`;
                for (const [k, v] of Object.entries(p.contact_info)) {
                    html += `<div style="margin-bottom:4px;"><strong style="text-transform:capitalize;">${escapeHtml(k)}:</strong> ${escapeHtml(v)}</div>`;
                }
                html += `</div>`;
                html += `<pre class="section-json-box" id="contact_infoJson" style="display:none; background:#f3f4f6; border:1px solid #e5e7eb; padding:12px; border-radius:10px; font-family:monospace; font-size:12px; color:#1e1b4b; margin-top:10px; white-space:pre-wrap; overflow-x:auto;"></pre>`;
            }

            // Current Job
            if (p.current_job && (p.current_job.title || p.current_job.company)) {
                html += `<div class="section-title" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fas fa-briefcase"></i> Current Job</span>
                            <button class="btn-json-toggle" onclick="toggleAdminSectionJson('current_job', this)" style="background:rgba(10,102,194,0.1); border:1px solid rgba(10,102,194,0.3); color:#0a66c2; font-size:12px; cursor:pointer; font-weight:600; padding:2px 8px; border-radius:4px;"><i class="fas fa-code"></i> JSON</button>
                         </div>`;
                html += `<div style="background:#f0f7ff;padding:14px;border-radius:10px;border-left:4px solid #0a66c2;">`;
                if (p.current_job.title) html += `<div style="font-weight:700;font-size:16px;">${escapeHtml(p.current_job.title)}</div>`;
                if (p.current_job.company) html += `<div style="color:#555;">${escapeHtml(p.current_job.company)}</div>`;
                if (p.current_job.duration) html += `<div style="color:#888;font-size:13px;">${escapeHtml(p.current_job.duration)}</div>`;
                if (p.current_job.location) html += `<div style="color:#888;font-size:13px;"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(p.current_job.location)}</div>`;
                html += `</div>`;
                html += `<pre class="section-json-box" id="current_jobJson" style="display:none; background:#f3f4f6; border:1px solid #e5e7eb; padding:12px; border-radius:10px; font-family:monospace; font-size:12px; color:#1e1b4b; margin-top:10px; white-space:pre-wrap; overflow-x:auto;"></pre>`;
            }

            // Experience (all entries)
            if (p.experience && p.experience.length) {
                html += `<div class="section-title" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fas fa-briefcase"></i> Experience</span>
                            <button class="btn-json-toggle" onclick="toggleAdminSectionJson('experience', this)" style="background:rgba(10,102,194,0.1); border:1px solid rgba(10,102,194,0.3); color:#0a66c2; font-size:12px; cursor:pointer; font-weight:600; padding:2px 8px; border-radius:4px;"><i class="fas fa-code"></i> JSON</button>
                         </div>`;
                p.experience.forEach(exp => {
                    html += `<div style="background:#f0f7ff;padding:14px;border-radius:10px;margin-bottom:12px;border-left:4px solid #0a66c2;">`;
                    if (exp.title) html += `<div style="font-weight:700;font-size:16px;">${escapeHtml(exp.title)}</div>`;
                    if (exp.company) html += `<div style="color:#555;font-weight:600;margin-top:2px;">${escapeHtml(exp.company)}</div>`;
                    if (exp.duration) html += `<div style="color:#888;font-size:13px;margin-top:2px;">${escapeHtml(exp.duration)}</div>`;
                    if (exp.location) html += `<div style="color:#888;font-size:13px;margin-top:2px;"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(exp.location)}</div>`;
                    html += `</div>`;
                });
                html += `<pre class="section-json-box" id="experienceJson" style="display:none; background:#f3f4f6; border:1px solid #e5e7eb; padding:12px; border-radius:10px; font-family:monospace; font-size:12px; color:#1e1b4b; margin-top:10px; white-space:pre-wrap; overflow-x:auto;"></pre>`;
            }

            // Qualifications / Education
            if (p.qualifications && p.qualifications.length) {
                html += `<div class="section-title" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fas fa-graduation-cap"></i> Education</span>
                            <button class="btn-json-toggle" onclick="toggleAdminSectionJson('qualifications', this)" style="background:rgba(10,102,194,0.1); border:1px solid rgba(10,102,194,0.3); color:#0a66c2; font-size:12px; cursor:pointer; font-weight:600; padding:2px 8px; border-radius:4px;"><i class="fas fa-code"></i> JSON</button>
                         </div>`;
                p.qualifications.forEach(q => {
                    html += `<div style="background:#f9fafb;padding:10px 14px;border-radius:8px;margin-bottom:8px;border:1px solid #e5e7eb;">`;
                    if (q.institution) html += `<div style="font-weight:600;">${escapeHtml(q.institution)}</div>`;
                    if (q.degree) html += `<div style="color:#555;">${escapeHtml(q.degree)}</div>`;
                    if (q.dates) html += `<div style="color:#888;font-size:13px;">${escapeHtml(q.dates)}</div>`;
                    html += `</div>`;
                });
                html += `<pre class="section-json-box" id="qualificationsJson" style="display:none; background:#f3f4f6; border:1px solid #e5e7eb; padding:12px; border-radius:10px; font-family:monospace; font-size:12px; color:#1e1b4b; margin-top:10px; white-space:pre-wrap; overflow-x:auto;"></pre>`;
            }

            // Certifications
            if (p.certifications && p.certifications.length) {
                html += `<div class="section-title" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fas fa-certificate"></i> Certifications</span>
                            <button class="btn-json-toggle" onclick="toggleAdminSectionJson('certifications', this)" style="background:rgba(10,102,194,0.1); border:1px solid rgba(10,102,194,0.3); color:#0a66c2; font-size:12px; cursor:pointer; font-weight:600; padding:2px 8px; border-radius:4px;"><i class="fas fa-code"></i> JSON</button>
                         </div>`;
                p.certifications.forEach(c => {
                    html += `<div style="background:#fffbeb;padding:10px 14px;border-radius:8px;margin-bottom:8px;border:1px solid #fde68a;">`;
                    if (c.name) html += `<div style="font-weight:600;">${escapeHtml(c.name)}</div>`;
                    if (c.issuer) html += `<div style="color:#555;">${escapeHtml(c.issuer)}</div>`;
                    if (c.date) html += `<div style="color:#888;font-size:13px;">${escapeHtml(c.date)}</div>`;
                    html += `</div>`;
                });
                html += `<pre class="section-json-box" id="certificationsJson" style="display:none; background:#f3f4f6; border:1px solid #e5e7eb; padding:12px; border-radius:10px; font-family:monospace; font-size:12px; color:#1e1b4b; margin-top:10px; white-space:pre-wrap; overflow-x:auto;"></pre>`;
            }

            // Skills
            if (p.skills && p.skills.length) {
                html += `<div class="section-title" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fas fa-tools"></i> Skills</span>
                            <button class="btn-json-toggle" onclick="toggleAdminSectionJson('skills', this)" style="background:rgba(10,102,194,0.1); border:1px solid rgba(10,102,194,0.3); color:#0a66c2; font-size:12px; cursor:pointer; font-weight:600; padding:2px 8px; border-radius:4px;"><i class="fas fa-code"></i> JSON</button>
                         </div>`;
                html += `<div style="display:flex;flex-wrap:wrap;gap:8px;padding:4px 0;">`;
                p.skills.forEach(s => {
                    html += `<span style="background:#dbeafe;color:#1e40af;padding:5px 12px;border-radius:20px;font-size:13px;font-weight:600;">${escapeHtml(s.skill)}${s.endorsements ? ` <small style="opacity:0.6;">(${escapeHtml(s.endorsements)})</small>` : ''}</span>`;
                });
                html += `</div>`;
                html += `<pre class="section-json-box" id="skillsJson" style="display:none; background:#f3f4f6; border:1px solid #e5e7eb; padding:12px; border-radius:10px; font-family:monospace; font-size:12px; color:#1e1b4b; margin-top:10px; white-space:pre-wrap; overflow-x:auto;"></pre>`;
            }

            // Languages
            if (p.languages && p.languages.length) {
                html += `<div class="section-title"><i class="fas fa-language"></i> Languages</div>`;
                html += `<div style="display:flex;flex-wrap:wrap;gap:8px;padding:4px 0;">`;
                p.languages.forEach(l => {
                    html += `<span style="background:#d1fae5;color:#065f46;padding:5px 12px;border-radius:20px;font-size:13px;font-weight:600;">${escapeHtml(l.language)}${l.proficiency ? ` &mdash; <small>${escapeHtml(l.proficiency)}</small>` : ''}</span>`;
                });
                html += `</div>`;
            }

            // Volunteer
            if (p.volunteer && p.volunteer.length) {
                html += `<div class="section-title"><i class="fas fa-hands-helping"></i> Volunteer Experience</div>`;
                p.volunteer.forEach(v => {
                    html += `<div style="background:#fdf2f8;padding:10px 14px;border-radius:8px;margin-bottom:8px;border-left:4px solid #ec4899;">`;
                    if (v.role) html += `<div style="font-weight:600;">${escapeHtml(v.role)}</div>`;
                    if (v.organization) html += `<div style="color:#555;">${escapeHtml(v.organization)}</div>`;
                    if (v.duration) html += `<div style="color:#888;font-size:13px;">${escapeHtml(v.duration)}</div>`;
                    html += `</div>`;
                });
            }

            // Honors & Awards
            if (p.honors && p.honors.length) {
                html += `<div class="section-title"><i class="fas fa-trophy"></i> Honors &amp; Awards</div>`;
                p.honors.forEach(h => {
                    html += `<div style="background:#fffbeb;padding:10px 14px;border-radius:8px;margin-bottom:8px;border-left:4px solid #f59e0b;">`;
                    if (h.title) html += `<div style="font-weight:600;">${escapeHtml(h.title)}</div>`;
                    if (h.issuer) html += `<div style="color:#555;">${escapeHtml(h.issuer)}</div>`;
                    if (h.date) html += `<div style="color:#888;font-size:13px;">${escapeHtml(h.date)}</div>`;
                    html += `</div>`;
                });
            }

            // Recommendations
            if (p.recommendations && p.recommendations.length) {
                html += `<div class="section-title"><i class="fas fa-star"></i> Recommendations</div>`;
                p.recommendations.forEach(r => {
                    html += `<div style="background:#f5f3ff;padding:14px;border-radius:10px;margin-bottom:10px;border-left:4px solid #7c3aed;">`;
                    if (r.recommender) html += `<div style="font-weight:700;color:#5b21b6;">${escapeHtml(r.recommender)}</div>`;
                    if (r.title) html += `<div style="color:#777;font-size:13px;">${escapeHtml(r.title)}</div>`;
                    if (r.text) html += `<p style="margin-top:8px;font-style:italic;color:#374151;">&ldquo;${escapeHtml(r.text)}&rdquo;</p>`;
                    html += `</div>`;
                });
            }

            // Full text
            if (p.full_text) {
                html += `<div class="section-title" style="display:flex; justify-content:space-between; align-items:center;">
                            <span><i class="fas fa-file-alt"></i> Full Profile Raw Text</span>
                            <button class="btn-json-toggle" onclick="toggleAdminSectionJson('full_text', this)" style="background:rgba(10,102,194,0.1); border:1px solid rgba(10,102,194,0.3); color:#0a66c2; font-size:12px; cursor:pointer; font-weight:600; padding:2px 8px; border-radius:4px;"><i class="fas fa-code"></i> JSON</button>
                         </div>`;
                html += `<div class="full-text-box" style="max-height:400px; overflow-y:auto; margin-bottom: 20px;">${escapeHtml(p.full_text)}</div>`;
                html += `<pre class="section-json-box" id="full_textJson" style="display:none; background:#f3f4f6; border:1px solid #e5e7eb; padding:12px; border-radius:10px; font-family:monospace; font-size:12px; color:#1e1b4b; margin-top:10px; white-space:pre-wrap; overflow-x:auto;"></pre>`;
            }

            if (p.error) html += `<div class="alert alert-error">Error: ${escapeHtml(p.error)}</div>`;

            // Export buttons
            html += `<div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:24px; margin-bottom:8px; padding-top:16px; border-top:2px solid #e5e7eb;">
                        <button onclick="exportDataSingle(${index}, 'json')" class="btn btn-outline" style="border-color:#0a66c2;color:#0a66c2;"><i class="fas fa-file-code"></i> Export JSON</button>
                        <button onclick="exportDataSingle(${index}, 'csv')" class="btn btn-outline" style="border-color:#10b981;color:#10b981;"><i class="fas fa-file-csv"></i> Export CSV</button>
                        <button onclick="exportFullTextAsPDFSingle(${index})" class="btn btn-outline" style="border-color:#ef4444;color:#ef4444;"><i class="fas fa-file-pdf"></i> Export PDF</button>
                        ${p.profile_url ? `<a href="${escapeHtml(p.profile_url)}" target="_blank" class="btn btn-primary" style="text-decoration:none; margin-left:auto;"><i class="fab fa-linkedin"></i> View on LinkedIn</a>` : ''}
                     </div>`;

            detailDiv.innerHTML = html;
            detailDiv.scrollIntoView({ behavior: 'smooth' });
        }

        function toggleAdminSectionJson(sectionKey, btn) {
            const index = state.activeProfileIndex;
            const p = state.currentProfiles[index];
            if (!p) return;
            const container = document.getElementById(sectionKey + 'Json');
            if (!container) return;
            
            if (container.style.display === 'none' || !container.style.display) {
                let dataToDisplay = p[sectionKey];
                container.textContent = JSON.stringify(dataToDisplay, null, 2);
                container.style.display = 'block';
                btn.innerHTML = '<i class="fas fa-eye-slash"></i> Hide JSON';
            } else {
                container.style.display = 'none';
                btn.innerHTML = '<i class="fas fa-code"></i> JSON';
            }
        }

        // --- monitoring functions ---
        async function loadApprovals() {
            const container = document.getElementById('approvalsTableContainer');
            container.innerHTML = '<p><i class="fas fa-spinner fa-spin"></i> Loading requests...</p>';
            try {
                const res = await fetch('/api/admin/approvals');
                const data = await res.json();
                if (data.success) {
                    if (!data.approvals.length) {
                        container.innerHTML = '<p style="color:#6b7280;">No requests yet. Requests appear here automatically when clients submit scrapes.</p>';
                        return;
                    }

                    // Status badge colours
                    const statusConfig = {
                        in_progress: { color: '#1d4ed8', bg: '#dbeafe', label: '⏳ In Progress' },
                        completed:   { color: '#065f46', bg: '#d1fae5', label: '✅ Completed' },
                        failed:      { color: '#991b1b', bg: '#fee2e2', label: '❌ Failed' },
                        pending:     { color: '#92400e', bg: '#fef3c7', label: '🕐 Pending' }
                    };

                    let html = `
                        <table style="width: 100%; border-collapse: collapse; text-align: left; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); color:#1f2937;">
                            <thead>
                                <tr style="background: #f3f4f6; border-bottom: 2px solid #e5e7eb;">
                                    <th style="padding: 14px 20px; font-weight:600;">Reference #</th>
                                    <th style="padding: 14px 20px; font-weight:600;">Person / Profile</th>
                                    <th style="padding: 14px 20px; font-weight:600;">Requested At</th>
                                    <th style="padding: 14px 20px; font-weight:600;">Completed At</th>
                                    <th style="padding: 14px 20px; font-weight:600;">Status</th>
                                    <th style="padding: 14px 20px; font-weight:600;">Action</th>
                                </tr>
                            </thead>
                            <tbody>
                    `;
                    data.approvals.forEach(req => {
                        const cfg = statusConfig[req.status] || { color: '#374151', bg: '#f3f4f6', label: req.status };
                        const requestedAt = req.requested_at ? new Date(req.requested_at).toLocaleString() : '—';
                        const completedAt = req.scraped_at ? new Date(req.scraped_at).toLocaleString() : '—';
                        const profileLink = req.profile_url 
                            ? `<a href="${escapeHtml(req.profile_url)}" target="_blank" style="color:#0a66c2; font-size:12px; display:block; margin-top:2px;">${escapeHtml(req.person_name || req.profile_url)}</a>`
                            : escapeHtml(req.person_name || '—');

                        const actionBtn = req.status === 'failed'
                            ? `<button class="btn btn-outline" style="padding:5px 10px; font-size:12px; border-radius:6px; border-color:#f59e0b; color:#d97706;" onclick="retryRequest('${escapeHtml(req.request_id)}')">
                                <i class="fas fa-redo"></i> Retry
                               </button>`
                            : req.status === 'completed'
                            ? `<a href="/api/client/download/json?return_code=${escapeHtml(req.request_id)}" class="btn btn-outline" style="padding:5px 10px; font-size:12px; border-radius:6px; border-color:#3b82f6; color:#3b82f6; text-decoration:none;">
                                <i class="fas fa-file-code"></i> JSON
                               </a>`
                            : `<span style="color:#9ca3af; font-size:12px;">—</span>`;

                        html += `
                            <tr style="border-bottom: 1px solid #f3f4f6;">
                                <td style="padding: 14px 20px; font-family: monospace; font-size:14px; font-weight:700; color:#0a66c2;">#${escapeHtml(req.request_id)}</td>
                                <td style="padding: 14px 20px;">${profileLink}</td>
                                <td style="padding: 14px 20px; font-size:13px; color:#6b7280;">${requestedAt}</td>
                                <td style="padding: 14px 20px; font-size:13px; color:#6b7280;">${completedAt}</td>
                                <td style="padding: 14px 20px;">
                                    <span style="background:${cfg.bg}; color:${cfg.color}; padding:4px 10px; border-radius:20px; font-size:12px; font-weight:700;">${cfg.label}</span>
                                    ${req.error ? `<div style="color:#ef4444; font-size:11px; margin-top:4px;">${escapeHtml(req.error)}</div>` : ''}
                                </td>
                                <td style="padding: 14px 20px;">${actionBtn}</td>
                            </tr>
                        `;
                    });
                    html += '</tbody></table>';
                    container.innerHTML = html;
                } else {
                    container.innerHTML = `<p style="color:#ef4444;">Error loading requests: ${data.error}</p>`;
                }
            } catch (e) {
                container.innerHTML = `<p style="color:#ef4444;">Connection error: ${e.message}</p>`;
            }
        }

        async function retryRequest(requestId) {
            try {
                const res = await fetch('/api/admin/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ request_id: requestId })
                });
                const data = await res.json();
                if (data.success) {
                    showToast('Re-scrape triggered for request #' + requestId, 'success');
                    loadApprovals();
                } else {
                    showToast('Failed to retry: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('Connection error: ' + e.message, 'error');
            }
        }

        async function scrapeRequestedName(requestId, personName) {
            
            showToast(`Searching & scraping profile for "${personName}" using active session...`, 'info');
            
            const container = document.getElementById('approvalsTableContainer');
            const originalHTML = container.innerHTML;
            container.innerHTML = `<div style="text-align:center; padding: 40px; color:#1f2937;">
                <i class="fas fa-spinner fa-spin fa-2x" style="color:#0a66c2; margin-bottom:12px;"></i>
                <p style="font-weight:600;">LinkedIn Scraper is searching and extracting profile for "${escapeHtml(personName)}"...</p>
                <p style="font-size:13px; color:#6b7280; margin-top:4px;">Please wait. This will take a few seconds.</p>
            </div>`;
            
            try {
                const res = await fetch('/api/admin/scrape-requested-name', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ request_id: requestId, person_name: personName })
                });
                const data = await res.json();
                
                if (data.success) {
                    showToast(`Successfully extracted profile for "${personName}"!`, 'success');
                    
                    state.currentProfiles.push(data.profile);
                    state.stats.profiles++;
                    
                    await loadApprovals();
                    
                    displayExtractedProfiles(state.currentProfiles);
                    showProfileDetail(state.currentProfiles.length - 1);
                    switchTab('results');
                } else {
                    showToast('Failed to scrape: ' + data.error, 'error');
                    container.innerHTML = originalHTML;
                }
            } catch (e) {
                showToast('Connection error during extraction: ' + e.message, 'error');
                container.innerHTML = originalHTML;
            }
        }

        async function loadPendingScrapes() {
            const container = document.getElementById('pendingScrapesTableContainer');
            if (!container) return;
            try {
                const res = await fetch('/api/admin/approvals');
                const data = await res.json();
                if (data.success) {
                    let reqs = data.approvals;
                    
                    if (!reqs.length) {
                        container.innerHTML = '<p style="color:#6b7280; font-style:italic;">No scrape requests found.</p>';
                        return;
                    }

                    // Status badge colours
                    const statusConfig = {
                        in_progress: { color: '#1d4ed8', bg: '#dbeafe', label: '⏳ In Progress' },
                        completed:   { color: '#065f46', bg: '#d1fae5', label: '✅ Completed' },
                        failed:      { color: '#991b1b', bg: '#fee2e2', label: '❌ Failed' },
                        pending:     { color: '#92400e', bg: '#fef3c7', label: '🕐 Pending' }
                    };
                    
                    let html = `
                        <div style="margin-bottom:10px;">
                            <button class="btn btn-outline" style="font-size:12px; padding:4px 12px;" onclick="loadPendingScrapes()"><i class="fas fa-sync"></i> Refresh</button>
                        </div>
                        <table style="width: 100%; border-collapse: collapse; text-align: left; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); color:#1f2937; margin-top:10px;">
                            <thead>
                                <tr style="background: #f3f4f6; border-bottom: 2px solid #e5e7eb;">
                                    <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Requested Name</th>
                                    <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Request ID</th>
                                    <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Requested At</th>
                                    <th style="padding: 12px 16px; font-weight:600; font-size:14px;">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                    `;
                    reqs.forEach((req) => {
                        const dateStr = new Date(req.requested_at).toLocaleString();
                        const cfg = statusConfig[req.status] || { color: '#374151', bg: '#f3f4f6', label: req.status };
                        html += `
                            <tr style="border-bottom: 1px solid #f3f4f6;">
                                <td style="padding: 12px 16px; font-weight:600; color:#111827;">${escapeHtml(req.person_name)}</td>
                                <td style="padding: 12px 16px; font-family: monospace; font-size:13px;">${escapeHtml(req.request_id)}</td>
                                <td style="padding: 12px 16px; font-size:13px; color:#6b7280;">${dateStr}</td>
                                <td style="padding: 12px 16px;">
                                    <span style="background:${cfg.bg}; color:${cfg.color}; padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: 600;">${cfg.label}</span>
                                </td>
                            </tr>
                        `;
                    });
                    html += '</tbody></table>';
                    container.innerHTML = html;
                } else {
                    container.innerHTML = `<p style="color:#ef4444;">Error loading requests: ${data.error}</p>`;
                }
            } catch (e) {
                container.innerHTML = `<p style="color:#ef4444;">Connection error: ${e.message}</p>`;
            }
        }

        async function scrapeFromSearchTab(requestId, personName) {
            
            showToast(`Searching & scraping profile for "${personName}" using active session...`, 'info');
            
            const container = document.getElementById('pendingScrapesTableContainer');
            const originalHTML = container.innerHTML;
            container.innerHTML = `<div style="text-align:center; padding: 40px; color:#1f2937;">
                <i class="fas fa-spinner fa-spin fa-2x" style="color:#0a66c2; margin-bottom:12px;"></i>
                <p style="font-weight:600;">LinkedIn Scraper is searching and extracting profile for "${escapeHtml(personName)}"...</p>
                <p style="font-size:13px; color:#6b7280; margin-top:4px;">Please wait. This will take a few seconds.</p>
            </div>`;
            
            try {
                const res = await fetch('/api/admin/scrape-requested-name', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ request_id: requestId, person_name: personName })
                });
                const data = await res.json();
                
                if (data.success) {
                    showToast(`Successfully extracted profile for "${personName}"!`, 'success');
                    
                    state.currentProfiles.push(data.profile);
                    state.stats.profiles++;
                    
                    await loadPendingScrapes();
                    
                    displayExtractedProfiles(state.currentProfiles);
                    showProfileDetail(state.currentProfiles.length - 1);
                    switchTab('results');
                } else {
                    showToast('Failed to scrape: ' + data.error, 'error');
                    container.innerHTML = originalHTML;
                }
            } catch (e) {
                showToast('Connection error during extraction: ' + e.message, 'error');
                container.innerHTML = originalHTML;
            }
        }

        async function exportDataSingle(index, format) {
            const p = state.currentProfiles[index];
            if (!p) return;
            try {
                const res = await fetch('/api/scraper/export', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ data: { profiles: [p] }, format })
                });
                if (res.ok) {
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `${escapeHtml(p.name || 'profile')}_export.${format}`;
                    a.click();
                    URL.revokeObjectURL(url);
                    showToast(`Exported ${p.name || 'profile'} as ${format}`, 'success');
                } else {
                    showToast('Export failed', 'error');
                }
            } catch (e) {
                showToast('Export error: ' + e.message, 'error');
            }
        }

        async function exportFullTextAsPDFSingle(index) {
            const p = state.currentProfiles[index];
            if (!p) return;
            try {
                const res = await fetch('/api/export-profile-pdf', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ profile: p })
                });
                if (res.ok) {
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `${(p.name || 'profile').replace(/\s+/g, '_')}_profile.pdf`;
                    a.click();
                    URL.revokeObjectURL(url);
                    showToast('PDF exported successfully', 'success');
                } else {
                    showToast('Export failed', 'error');
                }
            } catch (e) {
                showToast('Export error: ' + e.message, 'error');
            }
        }

        async function destroyMasterDatabase() {
            if (!confirm("WARNING: This will permanently destroy all cached profiles, scraping requests, and master database data! Are you absolutely sure?")) return;
            try {
                const res = await fetch('/api/admin/destroy-db', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    alert("All database records destroyed successfully.");
                    location.reload();
                } else {
                    alert("Error: " + data.error);
                }
            } catch (e) {
                console.error(e);
                alert("Failed to destroy database.");
            }
        }

        async function loadMasterProfiles() {
            try {
                const res = await fetch('/api/admin/db-profiles');
                const data = await res.json();
                if (data.success && data.profiles && data.profiles.length > 0) {
                    state.currentProfiles = data.profiles;
                    displayExtractedProfiles(state.currentProfiles);
                }
            } catch (e) {
                console.error("Error loading master database profiles:", e);
            }
        }

        async function updateStats() {
            try {
                const res = await fetch('/api/scraper/stats');
                const data = await res.json();
                if (data.success && data.stats) {
                    state.initialized = data.stats.is_browser_running;
                    state.authenticated = data.stats.is_authenticated;
                    updateUIState();
                } else if (data.error === 'Not initialized') {
                    state.initialized = false;
                    state.authenticated = false;
                    updateUIState();
                }
            } catch (e) { console.error(e); }
        }

        updateUIState();
        loadPendingScrapes();
        loadMasterProfiles();

        // Auto-polling for Admin UI real-time updates
        setInterval(() => {
            updateStats();
            if (state.activeTab === 'approvals') loadApprovals();
            else if (state.activeTab === 'search') loadPendingScrapes();
            else if (state.activeTab === 'bucket') loadBucketStatus();
        }, 5000);

        // ══════════════════════════════════════════════════════════
        // TASK BUCKET functions
        // ══════════════════════════════════════════════════════════

        // Rest-period countdown state
        let _restTimer = null;
        let _restTotal = 0;
        let _restElapsed = 0;

        function _startRestBar(seconds) {
            _restTotal = seconds;
            _restElapsed = 0;
            document.getElementById('bucketRestBar').style.display = 'flex';
            document.getElementById('bucketRestMsg').textContent = `Resting ${seconds}s before next task…`;
            document.getElementById('bucketRestFill').style.width = '100%';
            clearInterval(_restTimer);
            _restTimer = setInterval(() => {
                _restElapsed += 1;
                const pct = Math.max(0, 100 - (_restElapsed / _restTotal) * 100);
                document.getElementById('bucketRestFill').style.width = pct + '%';
                document.getElementById('bucketRestMsg').textContent =
                    `Resting — ${Math.max(0, _restTotal - _restElapsed)}s remaining…`;
                if (_restElapsed >= _restTotal) {
                    clearInterval(_restTimer);
                    document.getElementById('bucketRestBar').style.display = 'none';
                }
            }, 1000);
        }

        function _stopRestBar() {
            clearInterval(_restTimer);
            document.getElementById('bucketRestBar').style.display = 'none';
        }

        async function loadBucketStatus() {
            try {
                const res = await fetch('/api/bucket/status');
                const data = await res.json();
                if (!data.success) return;

                const s = data.summary;
                document.getElementById('bSumPending').textContent  = s.pending      || 0;
                document.getElementById('bSumActive').textContent   = s.in_progress  || 0;
                document.getElementById('bSumDone').textContent     = s.completed    || 0;
                document.getElementById('bSumFailed').textContent   = s.failed       || 0;
                document.getElementById('bSumTotal').textContent    = s.total        || 0;

                // Update pending badge on tab button
                const badge = document.getElementById('bucketPendingBadge');
                if (s.pending > 0) {
                    badge.style.display = 'inline';
                    badge.textContent = s.pending;
                } else {
                    badge.style.display = 'none';
                }

                // Worker status badge
                const dot    = document.getElementById('workerDot');
                const label  = document.getElementById('workerStatus');
                const pauseB = document.getElementById('btnBucketPause');
                const resumeB= document.getElementById('btnBucketResume');
                dot.className = 'worker-dot';
                if (!data.worker_running) {
                    dot.classList.add('stopped');
                    label.textContent = 'Worker stopped';
                    pauseB.disabled  = true;
                    resumeB.disabled = false;
                } else if (data.worker_paused) {
                    dot.classList.add('paused');
                    label.textContent = 'Worker paused';
                    pauseB.disabled  = true;
                    resumeB.disabled = false;
                } else {
                    dot.classList.add('running');
                    label.textContent = 'Worker running';
                    pauseB.disabled  = false;
                    resumeB.disabled = true;
                }

                // Rest seconds input
                document.getElementById('bucketRestInput').value = data.rest_seconds ?? 30;

                // Render task table
                renderBucketTable(data.tasks || []);
            } catch(e) { console.error('bucket status error', e); }
        }

        function renderBucketTable(tasks) {
            const container = document.getElementById('bucketTaskList');
            if (!tasks.length) {
                container.innerHTML = '<p style="color:#9ca3af;font-style:italic;">Queue is empty. Use the Search tab to add scrape tasks.</p>';
                return;
            }

            const badgeCfg = {
                pending:     { cls:'badge-pending',   icon:'fa-clock',        label:'Pending'     },
                in_progress: { cls:'badge-progress',  icon:'fa-circle-notch', label:'Scraping…',  spin:true },
                completed:   { cls:'badge-completed', icon:'fa-check-circle', label:'Done'        },
                failed:      { cls:'badge-failed',    icon:'fa-times-circle', label:'Failed'      },
            };

            const typeInfo = {
                search: { icon:'🔍', label:'Name Search' },
                url:    { icon:'🔗', label:'Direct URL'  },
                name:   { icon:'👤', label:'Name'        },
            };

            let html = `
            <table class="bucket-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Search / Query</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Result</th>
                        <th>Added</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>`;

            tasks.forEach((t, i) => {
                const bcfg = badgeCfg[t.status] || { cls:'badge-pending', icon:'fa-question', label: t.status };
                const spinClass = bcfg.spin ? ' spin' : '';
                const badge = `<span class="badge ${bcfg.cls}"><i class="fas ${bcfg.icon}${spinClass}"></i>${bcfg.label}</span>`;

                const ti = typeInfo[t.type] || { icon:'👤', label: t.type };

                // Build query display with search params if available
                let queryDisplay = escapeHtml(t.query);
                if (t.type === 'search' && t.search_params) {
                    const sp = t.search_params;
                    const parts = [];
                    if (sp.first_name) parts.push(`<strong>${escapeHtml(sp.first_name)}</strong>`);
                    if (sp.last_name)  parts.push(`<strong>${escapeHtml(sp.last_name)}</strong>`);
                    if (sp.company)    parts.push(`<em style="color:#6b7280;">@ ${escapeHtml(sp.company)}</em>`);
                    queryDisplay = parts.join(' ');
                    if (sp.max_results) queryDisplay += ` <span style="background:#ede9fe;color:#6d28d9;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700;">top ${sp.max_results}</span>`;
                }

                // Result cell
                let resultCell = '—';
                if (t.status === 'in_progress') {
                    resultCell = `<span style="color:#1d4ed8;font-size:11px;"><i class="fas fa-spinner spin"></i> Working…</span>`;
                } else if (t.result_name) {
                    const cnt = t.profiles_found ? ` <span style="background:#d1fae5;color:#065f46;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700;">${t.profiles_found} profile${t.profiles_found>1?'s':''}</span>` : '';
                    resultCell = `<span style="color:#065f46;font-weight:600;">${escapeHtml(t.result_name)}</span>${cnt}`;
                } else if (t.error) {
                    resultCell = `<span style="color:#991b1b;font-size:11px;" title="${escapeHtml(t.error)}">⚠ ${escapeHtml(t.error.substring(0,50))}${t.error.length>50?'…':''}</span>`;
                }

                const addedAt = t.added_at ? new Date(t.added_at).toLocaleString([], {dateStyle:'short',timeStyle:'short'}) : '—';
                const canRemove = t.status === 'pending';

                html += `
                    <tr>
                        <td style="color:#9ca3af;font-size:11px;">${i + 1}</td>
                        <td style="max-width:240px;">${ti.icon} ${queryDisplay}</td>
                        <td style="font-size:11px;color:#6b7280;white-space:nowrap;">${ti.label}</td>
                        <td>${badge}</td>
                        <td style="max-width:200px;">${resultCell}</td>
                        <td style="font-size:11px;color:#9ca3af;white-space:nowrap;">${addedAt}</td>
                        <td>${canRemove
                            ? `<button onclick="bucketRemoveTask('${escapeHtml(t.id)}')" style="background:#fee2e2;color:#991b1b;border:none;padding:3px 9px;border-radius:6px;cursor:pointer;font-size:11px;"><i class="fas fa-times"></i> Remove</button>`
                            : '<span style="color:#d1d5db;font-size:11px;">—</span>'}
                        </td>
                    </tr>`;
            });

            html += '</tbody></table>';
            container.innerHTML = html;
        }


        async function bucketAddTasks() {
            const raw = document.getElementById('bucketTaskInput').value.trim();
            if (!raw) { showToast('Enter at least one name or URL', 'warning'); return; }
            const queries = raw.split('\n').map(l => l.trim()).filter(Boolean);
            const btn = document.getElementById('btnBucketAdd');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner spin"></i> Adding…';
            try {
                const res = await fetch('/api/bucket/add', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ queries })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(`✅ Added ${data.added} task(s) to the bucket`, 'success');
                    document.getElementById('bucketTaskInput').value = '';
                    await loadBucketStatus();
                } else {
                    showToast('Error: ' + data.error, 'error');
                }
            } catch(e) { showToast('Network error: ' + e.message, 'error'); }
            finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-paper-plane"></i> Add to Bucket';
            }
        }

        async function bucketClear(clearAll) {
            const label = clearAll ? 'ALL tasks' : 'completed & failed tasks';
            if (!confirm(`Remove ${label} from the bucket?`)) return;
            const res  = await fetch('/api/bucket/clear', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ all: clearAll })
            });
            const data = await res.json();
            if (data.success) {
                showToast(`Removed ${data.removed} task(s)`, 'info');
                await loadBucketStatus();
            } else showToast('Error: ' + data.error, 'error');
        }

        async function bucketPause() {
            await fetch('/api/bucket/pause', { method:'POST' });
            showToast('Worker will pause after current task', 'info');
            setTimeout(loadBucketStatus, 500);
        }

        async function bucketResume() {
            await fetch('/api/bucket/resume', { method:'POST' });
            showToast('Worker resumed ▶', 'success');
            setTimeout(loadBucketStatus, 500);
        }

        async function bucketSaveConfig() {
            const secs = parseInt(document.getElementById('bucketRestInput').value);
            if (isNaN(secs) || secs < 0) { showToast('Enter a valid number of seconds (≥ 0)', 'warning'); return; }
            const res  = await fetch('/api/bucket/config', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ rest_seconds: secs })
            });
            const data = await res.json();
            if (data.success) showToast(`Rest period set to ${secs}s`, 'success');
            else showToast('Error: ' + data.error, 'error');
        }

        async function bucketRemoveTask(taskId) {
            const res  = await fetch('/api/bucket/remove', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ task_id: taskId })
            });
            const data = await res.json();
            if (data.success) { showToast('Task removed', 'info'); await loadBucketStatus(); }
            else showToast('Error: ' + data.error, 'error');
        }

        // SSE live updates — instantly refresh admin when a client scrape completes
        (function connectAdminSSE() {
            const es = new EventSource('/api/admin/events');
            es.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);

                    if (msg.type === 'new_scrape') {
                        loadMasterProfiles();
                        updateStats();
                        loadPendingScrapes();
                        loadApprovals();
                        const toast = document.createElement('div');
                        toast.textContent = `✅ New scrape completed: "${msg.name}" — ${msg.count} profile(s) added`;
                        toast.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;background:#10b981;color:white;padding:14px 22px;border-radius:12px;font-weight:600;font-size:.95rem;box-shadow:0 8px 24px rgba(0,0,0,.3);';
                        document.body.appendChild(toast);
                        setTimeout(() => toast.remove(), 5000);

                    } else if (msg.type === 'request_started') {
                        loadPendingScrapes(); loadApprovals();
                        const toast = document.createElement('div');
                        toast.textContent = `⏳ New scrape started for: "${msg.name}"`;
                        toast.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;background:#3b82f6;color:white;padding:14px 22px;border-radius:12px;font-weight:600;font-size:.95rem;box-shadow:0 8px 24px rgba(0,0,0,.3);';
                        document.body.appendChild(toast);
                        setTimeout(() => toast.remove(), 5000);

                    } else if (msg.type === 'bucket_update' || msg.type === 'bucket_tasks_added' ||
                               msg.type === 'bucket_cleared' || msg.type === 'bucket_paused' ||
                               msg.type === 'bucket_resumed') {
                        // Refresh bucket panel whenever anything changes
                        if (state.activeTab === 'bucket') loadBucketStatus();
                        // Update pending badge even on other tabs
                        fetch('/api/bucket/status').then(r => r.json()).then(data => {
                            const badge = document.getElementById('bucketPendingBadge');
                            const p = data.summary?.pending || 0;
                            badge.style.display = p > 0 ? 'inline' : 'none';
                            badge.textContent = p;
                        }).catch(() => {});

                    } else if (msg.type === 'bucket_rest') {
                        _startRestBar(msg.seconds);
                        if (state.activeTab === 'bucket') loadBucketStatus();
                    }
                } catch(e) {}
            };
            es.onerror = () => { es.close(); setTimeout(connectAdminSSE, 3000); };
        })();
    