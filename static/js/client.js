
            let activeProfileData = null;
            let activeBulkData = null;

            function escapeHtml(text) {
                if (!text) return '';
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }

            // --- DIRECT SEARCH & EXTRACT ---
            function showSearchError(msg) {
                const statusDiv = document.getElementById('searchStatus');
                statusDiv.innerHTML = `<div class="status-panel failed" style="display:flex; padding: 10px; margin-bottom: 0;"><i class="fas fa-exclamation-triangle"></i><div>${msg}</div></div>`;
                setTimeout(() => { statusDiv.innerHTML = ''; }, 5000);
            }
            function showSearchSuccess(msg) {
                const statusDiv = document.getElementById('searchStatus');
                statusDiv.innerHTML = `<div class="status-panel success" style="display:flex; padding: 10px; margin-bottom: 0; align-items:center; flex-direction:row;"><i class="fas fa-check-circle" style="color:var(--success-color);"></i><div>${msg}</div></div>`;
                setTimeout(() => { statusDiv.innerHTML = ''; }, 5000);
            }
            function showSearchInfo(msg) {
                const statusDiv = document.getElementById('searchStatus');
                statusDiv.innerHTML = `<div class="status-panel in_progress" style="display:flex; padding: 10px; margin-bottom: 0; align-items:center; flex-direction:row;"><i class="fas fa-info-circle"></i><div>${msg}</div></div>`;
            }



            let currentPollInterval = null;
            let currentRefNumber = null;

            function showRefBadge(refNum) {
                if (!refNum) return;
                currentRefNumber = refNum;
                document.getElementById('refBadgeNumber').textContent = refNum;
                document.getElementById('refBadgeContainer').classList.add('show');
            }

            function copyRefNumber() {
                if (!currentRefNumber) return;
                navigator.clipboard.writeText(currentRefNumber).then(() => {
                    const btn = document.querySelector('.ref-copy-btn');
                    const orig = btn.innerHTML;
                    btn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                    btn.style.color = 'var(--success-color)';
                    setTimeout(() => { btn.innerHTML = orig; btn.style.color = ''; }, 2000);
                }).catch(() => {
                    // Fallback for older browsers
                    const el = document.createElement('textarea');
                    el.value = currentRefNumber;
                    document.body.appendChild(el);
                    el.select();
                    document.execCommand('copy');
                    document.body.removeChild(el);
                });
            }

            async function searchAndExtract() {
                const fileInput = document.getElementById('clientUploadFile');
                if (fileInput && fileInput.files.length > 0) {
                    await clientUploadFile(true);
                    return;
                }

                const username = document.getElementById('usernameKeyword').value.trim();
                let firstName = document.getElementById('firstName').value.trim();
                let lastName = document.getElementById('lastName').value.trim();
                const company = document.getElementById('company').value.trim();
                const contactEmail = document.getElementById('contactEmail') ? document.getElementById('contactEmail').value.trim() : '';
                const contactPhone = document.getElementById('contactPhone') ? document.getElementById('contactPhone').value.trim() : '';
                
                const btn = document.getElementById('btnDirectSearchExtract');

                if (contactEmail || contactPhone) {
                    btn.disabled = true;
                    btn.innerHTML = '<i class="fas fa-spinner spinner"></i> Searching Contact...';
                    showSearchInfo('<i class="fas fa-id-card"></i> Searching Contact Info (Requires Premium)...');

                    try {
                        const res = await fetch('/api/scraper/search-contact-info', {
                            method: 'POST', headers: {'Content-Type':'application/json'},
                            body: JSON.stringify({ email: contactEmail, phone: contactPhone })
                        });
                        const data = await res.json();
                        if (res.status === 403 && data.error === 'PREMIUM_REQUIRED') {
                            showSearchError(`⚠️ ${data.message}`);
                        } else if (data.success) {
                            if (data.results && data.results.length > 0) {
                                const url = data.results[0].profile_url;
                                const bRes = await fetch('/api/client/scrape', {
                                    method: 'POST', headers: {'Content-Type':'application/json'},
                                    body: JSON.stringify({ name: url }) // Queue the found URL
                                });
                                const bData = await bRes.json();
                                if (bData.status === 'queued' || bData.status === 'pending' || bData.status === 'in_progress') {
                                    const searchName = contactEmail || contactPhone;
                                    showSearchInfo('<i class="fas fa-layer-group"></i> <strong>Found contact & Queued</strong> — waiting for results...');
                                    addToSearchHistory(searchName, bData.reference_number, 'queued');
                                    if (currentPollInterval) clearInterval(currentPollInterval);
                                    currentPollInterval = setInterval(() => pollScrapeStatus(searchName, btn, bData.reference_number), 4000);
                                    document.getElementById('btnQueueAnother').style.display = 'inline-block';
                                } else if (bData.cached) {
                                    const searchName = contactEmail || contactPhone;
                                    renderBulkProfiles(bData.profiles, searchName);
                                    showSearchSuccess(`Loaded contact profile from cache.`);
                                    addToSearchHistory(searchName, bData.reference_number, 'completed', {profiles_count: bData.profiles.length});
                                    btn.disabled = false;
                                    btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';
                                } else {
                                    showSearchError('Error queuing found profile: ' + (bData.error || 'Unknown'));
                                }
                            } else {
                                showSearchError('No matches found for that contact info.');
                            }
                        } else {
                            showSearchError('Error: ' + data.error);
                        }
                    } catch (e) {
                        showSearchError('Network error: ' + e.message);
                    } finally {
                        if (!currentPollInterval && btn.disabled && btn.innerHTML.includes('Searching')) {
                            btn.disabled = false;
                            btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';
                        }
                    }
                    return;
                }

                if (username) { firstName = username; lastName = ''; }
                if (!firstName && !lastName) { showSearchError('Please provide a Username, Name, Contact Info, OR upload a file to search.'); return; }

                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner spinner"></i> Adding to queue...';
                showSearchInfo('<i class="fas fa-layer-group"></i> Adding to Task Bucket queue...');

                const searchName = firstName || lastName ? `${firstName} ${lastName}`.trim() : username;

                try {
                    const res = await fetch('/api/client/scrape', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: searchName })
                    });
                    const data = await res.json();

                    if (res.status === 200 && data.cached) {
                        // Already in DB — show immediately
                        renderBulkProfiles(data.profiles, searchName);
                        showSearchSuccess(`Loaded ${data.profiles.length} profiles from cache.`);
                        if (data.reference_number) showRefBadge(data.reference_number);
                        addToSearchHistory(searchName, data.reference_number, 'completed', {profiles_count: data.profiles.length});
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';

                    } else if (res.status === 202 && data.status === 'queued') {
                        // Successfully added to bucket
                        const taskId = data.reference_number;
                        if (taskId) showRefBadge(taskId);
                        showSearchInfo('<i class="fas fa-layer-group"></i> <strong>Queued in Task Bucket</strong> — the worker will process it automatically. Results will appear here when done.');
                        btn.innerHTML = '<i class="fas fa-clock"></i> Waiting in queue...';
                        addToSearchHistory(searchName, taskId, 'queued');
                        if (currentPollInterval) clearInterval(currentPollInterval);
                        currentPollInterval = setInterval(() => pollScrapeStatus(searchName, btn, taskId), 4000);
                        document.getElementById('btnQueueAnother').style.display = 'inline-block';

                    } else if (res.status === 202 && (data.status === 'pending' || data.status === 'in_progress')) {
                        // Already queued/running in bucket
                        const taskId = data.reference_number;
                        if (taskId) showRefBadge(taskId);
                        showSearchInfo('<i class="fas fa-layer-group"></i> Already in Task Bucket — checking progress...');
                        btn.innerHTML = '<i class="fas fa-clock"></i> Processing...';
                        addToSearchHistory(searchName, taskId, data.status);
                        if (currentPollInterval) clearInterval(currentPollInterval);
                        currentPollInterval = setInterval(() => pollScrapeStatus(searchName, btn, taskId), 4000);
                        document.getElementById('btnQueueAnother').style.display = 'inline-block';

                    } else if (res.status === 401) {
                        showSearchError('<i class="fas fa-lock"></i> LinkedIn session not authenticated. Please contact the admin.');
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';

                    } else {
                        showSearchError(data.error || 'Failed to queue task');
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';
                    }
                } catch (e) {
                    showSearchError('Error: ' + e.message);
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';
                }
            }

            async function clientUploadFile(isMainButton = false) {
                const fileInput = document.getElementById('clientUploadFile');
                if (!fileInput.files.length) {
                    showSearchError('Please select a CSV or JSON file first.');
                    return;
                }
                const file = fileInput.files[0];
                const formData = new FormData();
                formData.append('file', file);
                
                const btn = isMainButton ? document.getElementById('btnDirectSearchExtract') : document.getElementById('btnClientUpload');
                if (!btn) return;
                
                btn.disabled = true;
                const originalText = btn.innerHTML;
                btn.innerHTML = '<i class="fas fa-spinner spinner"></i> Uploading...';
                showSearchInfo('<i class="fas fa-upload"></i> Uploading file to task bucket...');

                try {
                    const res = await fetch('/api/bucket/upload', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await res.json();
                    if (data.success) {
                        showSearchSuccess(`✅ ${data.message} They will be processed automatically.`);
                        fileInput.value = ''; // Reset input
                    } else {
                        showSearchError('Upload error: ' + data.error);
                    }
                } catch (e) {
                    showSearchError('Network error: ' + e.message);
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                }
            }

            async function pollScrapeStatus(name, btn, taskId) {
                try {
                    // Poll by task_id (most accurate) or fall back to name
                    let url = '/api/client/scrape-status?name=' + encodeURIComponent(name);
                    if (taskId && !taskId.startsWith('cached_')) {
                        url = '/api/client/scrape-status?task_id=' + encodeURIComponent(taskId) + '&name=' + encodeURIComponent(name);
                    }
                    const res = await fetch(url);
                    const data = await res.json();

                    if (res.status === 202 && data.status === 'pending') {
                        const pos = data.queue_position || '?';
                        const total = data.queue_total || '?';
                        let posHtml = '';
                        if (pos > 1) {
                            posHtml = `<br><span class="queue-position-badge"><i class="fas fa-layer-group"></i> Position ${pos} of ${total} in queue</span>`;
                        } else {
                            posHtml = `<br><span class="queue-position-badge"><i class="fas fa-layer-group"></i> Next in queue (${total} total)</span>`;
                        }
                        showSearchInfo(`<i class="fas fa-clock"></i> <strong>Queued</strong> — waiting for current task to finish...${posHtml}`);
                        btn.innerHTML = `<i class="fas fa-clock"></i> Queue #${pos}`;
                        updateSearchHistory(name, 'pending', taskId, {queue_position: pos, queue_total: total});

                    } else if (res.status === 202 && data.status === 'in_progress') {
                        showSearchInfo('<i class="fas fa-spinner spinner"></i> <strong>Scraping now</strong> — the worker is extracting LinkedIn profiles...');
                        btn.innerHTML = '<i class="fas fa-spinner spinner"></i> Scraping...';
                        updateSearchHistory(name, 'in_progress', taskId);

                    } else if (res.status === 200 && data.status === 'completed') {
                        clearInterval(currentPollInterval);
                        currentPollInterval = null;
                        renderBulkProfiles(data.profiles, name);
                        showSearchSuccess(`✅ Done! ${data.profiles.length} profile(s) extracted successfully.`);
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';
                        document.getElementById('btnQueueAnother').style.display = 'none';
                        updateSearchHistory(name, 'completed', taskId, {profiles_count: data.profiles.length});

                    } else if (data.status === 'failed') {
                        clearInterval(currentPollInterval);
                        currentPollInterval = null;
                        showSearchError('❌ Scrape failed: ' + (data.error || 'Unknown error'));
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';
                        document.getElementById('btnQueueAnother').style.display = 'none';
                        updateSearchHistory(name, 'failed', taskId, {error: data.error});

                    } else {
                        clearInterval(currentPollInterval);
                        currentPollInterval = null;
                        showSearchError(data.error || 'Scrape failed or returned empty.');
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';
                        document.getElementById('btnQueueAnother').style.display = 'none';
                        updateSearchHistory(name, 'failed', taskId);
                    }
                } catch (e) {
                    console.error('Polling error', e);
                }
            }

            function prepareNextSearch() {
                // Clear the active UI poll so it stops updating the main area
                if (currentPollInterval) {
                    clearInterval(currentPollInterval);
                    currentPollInterval = null;
                }
                
                // Clear the inputs
                document.getElementById('usernameKeyword').value = '';
                document.getElementById('firstName').value = '';
                document.getElementById('lastName').value = '';
                document.getElementById('company').value = '';
                
                // Reset buttons
                const btn = document.getElementById('btnDirectSearchExtract');
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-download"></i> Search &amp; Extract All';
                document.getElementById('btnQueueAnother').style.display = 'none';
                
                // Clear the status text and ref badge
                document.getElementById('searchStatus').innerHTML = '';
                document.getElementById('refBadgeContainer').classList.remove('show');
                
                showSearchInfo('Ready to add another search to the queue! You can monitor the previous search progress in the "My Searches" section below.');
            }

            // ---- REFERENCE NUMBER LOOKUP ----
            let refPollInterval = null;

            function showRefPanel(state, msg, extraHtml = '') {
                const panel = document.getElementById('refResultPanel');
                panel.className = `ref-result-panel ${state} show`;
                panel.innerHTML = `<div>${msg}</div>${extraHtml}`;
            }

            function clearRefPanel() {
                const panel = document.getElementById('refResultPanel');
                panel.className = 'ref-result-panel';
                panel.innerHTML = '';
            }

            async function lookupByReference() {
                const refInput = document.getElementById('refNumberInput').value.trim();
                if (!refInput) {
                    showRefPanel('error', '<i class="fas fa-exclamation-circle"></i> Please enter a reference number.');
                    return;
                }

                const btn = document.getElementById('btnRefLookup');
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner spinner"></i> Looking up...';
                clearRefPanel();

                // Clear any existing poll for reference lookup
                if (refPollInterval) { clearInterval(refPollInterval); refPollInterval = null; }

                try {
                    const res = await fetch('/api/client/lookup-by-reference', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ reference_number: refInput })
                    });
                    const data = await res.json();

                    if (res.status === 404) {
                        showRefPanel('not_found',
                            '<i class="fas fa-search"></i> <strong>Reference number not found.</strong><br>' +
                            '<span style="font-size:0.85rem; opacity:0.85;">Please check the number and try again. ' +
                            'Reference numbers are case-sensitive.</span>'
                        );
                    } else if (res.status === 202 && (data.status === 'in_progress' || data.status === 'pending')) {
                        const statusLabel = data.status === 'pending' ? 'Queued' : 'Still scraping';
                        showRefPanel('in_progress',
                            `<i class="fas fa-spinner spinner"></i> <strong>${statusLabel}...</strong><br>` +
                            `<span style="font-size:0.85rem; opacity:0.85;">${escapeHtml(data.message || '')}</span><br>` +
                            `<span style="font-size:0.8rem; opacity:0.7;">Auto-checking every 5 seconds. Please wait.</span>`
                        );
                        // Auto-poll until done
                        refPollInterval = setInterval(() => pollReferenceStatus(refInput), 5000);
                    } else if (!data.success && data.status === 'failed') {
                        showRefPanel('failed',
                            `<i class="fas fa-times-circle"></i> <strong>Scrape failed.</strong><br>` +
                            `<span style="font-size:0.85rem; opacity:0.85;">${escapeHtml(data.error || 'Unknown error occurred.')}</span>`
                        );
                    } else if (data.success && data.status === 'completed') {
                        handleRefLookupSuccess(data);
                    } else {
                        showRefPanel('error',
                            `<i class="fas fa-exclamation-triangle"></i> ${escapeHtml(data.error || 'Unexpected response from server.')}`
                        );
                    }
                } catch (e) {
                    showRefPanel('error', `<i class="fas fa-wifi"></i> Connection error: ${escapeHtml(e.message)}`);
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-search"></i> Lookup';
                }
            }

            async function pollReferenceStatus(refNum) {
                try {
                    const res = await fetch('/api/client/lookup-by-reference', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ reference_number: refNum })
                    });
                    const data = await res.json();

                    if (res.status === 202 && (data.status === 'in_progress' || data.status === 'pending')) {
                        const statusLabel = data.status === 'pending' ? 'Queued' : 'Still scraping';
                        // Still going — update message
                        showRefPanel('in_progress',
                            `<i class="fas fa-spinner spinner"></i> <strong>${statusLabel}...</strong><br>` +
                            `<span style="font-size:0.85rem; opacity:0.85;">${escapeHtml(data.message || '')}</span><br>` +
                            `<span style="font-size:0.8rem; opacity:0.7;">Auto-checking every 5 seconds. Please wait.</span>`
                        );
                    } else {
                        clearInterval(refPollInterval);
                        refPollInterval = null;
                        if (data.success && data.status === 'completed') {
                            handleRefLookupSuccess(data);
                        } else {
                            showRefPanel('failed',
                                `<i class="fas fa-times-circle"></i> <strong>${escapeHtml(data.status || 'Error')}:</strong> ` +
                                escapeHtml(data.error || 'Scrape did not complete successfully.')
                            );
                        }
                    }
                } catch (e) {
                    console.error('Ref poll error', e);
                }
            }

            function handleRefLookupSuccess(data) {
                clearRefPanel();
                const profiles = data.profiles || [];
                const total = data.total || profiles.length;
                const personName = data.person_name || 'Search';
                const scrapedAt = data.scraped_at ? new Date(data.scraped_at).toLocaleString() : '';

                if (!profiles.length) {
                    showRefPanel('not_found', '<i class="fas fa-inbox"></i> No profiles found for this reference number.');
                    return;
                }

                // Scroll to reference section
                document.querySelector('.ref-search-card').scrollIntoView({ behavior: 'smooth' });

                // Store profiles on module-level variables so download fns can access them
                window._refLookupProfiles = profiles;
                activeBulkData = profiles;

                // Show inline success banner with metadata + download buttons
                const panel = document.getElementById('refResultPanel');
                panel.className = 'ref-result-panel';
                panel.style.display = 'block';
                panel.style.background = 'rgba(16, 185, 129, 0.08)';
                panel.style.border = '1px solid rgba(16, 185, 129, 0.3)';
                panel.style.borderRadius = '14px';
                panel.style.padding = '20px 22px';
                panel.style.color = '#6ee7b7';
                panel.style.animation = 'fadeIn 0.4s ease';
                panel.style.flexDirection = 'column';
                panel.style.gap = '14px';

                panel.innerHTML = `
                <!-- Header row -->
                <div style="display:flex; align-items:center; gap:12px;">
                    <i class="fas fa-check-circle" style="font-size:1.5rem; color:#10b981; flex-shrink:0;"></i>
                    <div>
                        <div style="font-weight:700; color:white; font-size:1rem;">
                            Results found for reference
                            <span style="font-family:'Courier New',monospace; color:var(--secondary-accent);">
                                #${escapeHtml(data.reference_number)}
                            </span>
                        </div>
                        <div style="font-size:0.82rem; color:var(--text-muted); margin-top:3px;">
                            ${total} profile${total === 1 ? '' : 's'} retrieved
                            ${scrapedAt ? ' &middot; Scraped: ' + escapeHtml(scrapedAt) : ''}
                        </div>
                    </div>
                </div>

                <!-- Divider -->
                <div style="border-top:1px solid rgba(16,185,129,0.2);"></div>

                <!-- Action buttons -->
                <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:center;">
                    <!-- View -->
                    <button class="btn btn-primary"
                        style="padding:11px 22px; width:auto; font-size:0.9rem;"
                        onclick="displayRefResults(window._refLookupProfiles, '${escapeHtml(personName)}')">
                        <i class="fas fa-eye"></i>&nbsp; View ${total} Profile${total === 1 ? '' : 's'}
                    </button>

                    <!-- JSON -->
                    <button class="btn"
                        style="padding:11px 18px; width:auto; font-size:0.88rem;
                               background:rgba(99,102,241,0.15); border:1px solid rgba(99,102,241,0.4);
                               color:#c7d2fe; cursor:pointer; border-radius:10px;
                               display:flex; align-items:center; gap:7px; transition:all 0.25s;"
                        onmouseover="this.style.background='rgba(99,102,241,0.28)'"
                        onmouseout="this.style.background='rgba(99,102,241,0.15)'"
                        onclick="downloadRefResults('json', window._refLookupProfiles)">
                        <i class="fas fa-file-code"></i> Export JSON
                    </button>

                    <!-- CSV -->
                    <button class="btn"
                        style="padding:11px 18px; width:auto; font-size:0.88rem;
                               background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.38);
                               color:#6ee7b7; cursor:pointer; border-radius:10px;
                               display:flex; align-items:center; gap:7px; transition:all 0.25s;"
                        onmouseover="this.style.background='rgba(16,185,129,0.25)'"
                        onmouseout="this.style.background='rgba(16,185,129,0.12)'"
                        onclick="downloadRefResults('csv', window._refLookupProfiles)">
                        <i class="fas fa-file-csv"></i> Download CSV
                    </button>

                    <!-- PDF -->
                    <button class="btn"
                        style="padding:11px 18px; width:auto; font-size:0.88rem;
                               background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.38);
                               color:#fca5a5; cursor:pointer; border-radius:10px;
                               display:flex; align-items:center; gap:7px; transition:all 0.25s;"
                        onmouseover="this.style.background='rgba(239,68,68,0.25)'"
                        onmouseout="this.style.background='rgba(239,68,68,0.12)'"
                        onclick="downloadRefResultsPDF(window._refLookupProfiles)">
                        <i class="fas fa-file-pdf"></i> Download PDF
                    </button>
                </div>
            `;
            }

            function displayRefResults(profiles, searchName) {
                renderBulkProfiles(profiles, searchName);
                document.getElementById('bulkResult').scrollIntoView({ behavior: 'smooth' });
            }

            // ---- Download helpers for Reference Lookup results ----

            async function downloadRefResults(format, profiles) {
                if (!profiles || !profiles.length) {
                    showRefPanel('error', '<i class="fas fa-exclamation-triangle"></i> No data to export.');
                    return;
                }
                try {
                    const res = await fetch('/api/scraper/export', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ data: { profiles }, format })
                    });
                    if (res.ok) {
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `persona_ref_results.${format}`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                    } else {
                        const err = await res.json().catch(() => ({}));
                        showRefPanel('error', `<i class="fas fa-exclamation-triangle"></i> Export failed: ${escapeHtml(err.error || 'Unknown error')}`);
                    }
                } catch (e) {
                    showRefPanel('error', `<i class="fas fa-wifi"></i> Export error: ${escapeHtml(e.message)}`);
                }
            }

            async function downloadRefResultsPDF(profiles) {
                if (!profiles || !profiles.length) {
                    showRefPanel('error', '<i class="fas fa-exclamation-triangle"></i> No data to export.');
                    return;
                }
                try {
                    const isBulk = profiles.length > 1;
                    const endpoint = isBulk ? '/api/export-bulk-pdf' : '/api/export-profile-pdf';
                    const body = isBulk ? { profiles } : { profile: profiles[0] };
                    const filename = isBulk
                        ? 'persona_ref_results_bulk.pdf'
                        : `persona_${(profiles[0].name || 'profile').replace(/\s+/g, '_')}.pdf`;

                    const res = await fetch(endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    });
                    if (res.ok) {
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = filename;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                    } else {
                        const err = await res.json().catch(() => ({}));
                        showRefPanel('error', `<i class="fas fa-exclamation-triangle"></i> PDF export failed: ${escapeHtml(err.error || 'Unknown error')}`);
                    }
                } catch (e) {
                    showRefPanel('error', `<i class="fas fa-wifi"></i> PDF export error: ${escapeHtml(e.message)}`);
                }
            }

            // Auto-polling for scraper status
            setInterval(async () => {
                try {
                    const statsRes = await fetch('/api/scraper/stats');
                    if (statsRes.ok) {
                        const statsData = await statsRes.json();
                        const isAuth = statsData.success && statsData.stats && statsData.stats.is_authenticated;
                        const btn = document.getElementById('btnDirectSearchExtract');
                        if (btn) btn.disabled = !isAuth;
                        const statusDiv = document.getElementById('searchStatus');
                        if (!isAuth && (!statusDiv.innerHTML || statusDiv.innerHTML.includes('ready') || statusDiv.innerHTML.includes('successfully'))) {
                            showSearchInfo('Scraper is currently not authenticated. Waiting for admin to log in...');
                        } else if (isAuth && statusDiv.innerHTML.includes('not authenticated')) {
                            showSearchSuccess('Scraper is authenticated and ready.');
                        }
                    }
                } catch (e) { }
            }, 5000);


            function renderProfile(profile) {
                activeProfileData = profile;
                if (!activeBulkData || !activeBulkData.length) {
                    activeBulkData = [profile];
                }

                // Reset JSON boxes
                document.querySelectorAll('.section-json-box').forEach(box => {
                    box.style.display = 'none';
                    box.textContent = '';
                });
                document.querySelectorAll('.btn-json-toggle').forEach(btn => {
                    btn.innerHTML = '<i class="fas fa-code"></i> JSON';
                });

                const header = document.getElementById('profileHeader');
                const initials = (profile.name || '?').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();

                let headerHtml = '';
                if (profile.profile_picture) {
                    headerHtml += `<img src="${escapeHtml(profile.profile_picture)}" class="avatar" alt="${escapeHtml(profile.name)}">`;
                } else {
                    headerHtml += `<div class="avatar-fallback">${initials}</div>`;
                }

                const taglineText = profile.tagline || profile.headline || '';
                headerHtml += `
                <div class="profile-title-details">
                    <h2>${escapeHtml(profile.name || 'Unknown User')}</h2>
                    ${taglineText ? `<p class="headline" style="color:#c7d2fe; font-size:1.05rem; margin-top:4px;"><i class="fas fa-quote-left" style="color:var(--secondary-accent); font-size:0.85rem; margin-right:5px;"></i> ${escapeHtml(taglineText)}</p>` : ''}
                    ${profile.location ? `<p class="location"><i class="fas fa-map-marker-alt" style="color:var(--secondary-accent);"></i> ${escapeHtml(profile.location)}</p>` : ''}
                    <div style="display:flex; gap:15px; flex-wrap:wrap; margin-top:6px; font-size:0.88rem; color:var(--text-muted);">
                        ${profile.connections ? `<span><i class="fas fa-users" style="color:var(--secondary-accent);"></i> <strong>Connections:</strong> ${escapeHtml(profile.connections)}</span>` : ''}
                        ${profile.followers ? `<span><i class="fas fa-user-plus" style="color:#10b981;"></i> <strong>Followers:</strong> ${escapeHtml(profile.followers)}</span>` : ''}
                    </div>
                    <a href="${escapeHtml(profile.profile_url)}" target="_blank" style="color:var(--secondary-accent); font-size:0.85rem; display:inline-block; margin-top:6px;"><i class="fab fa-linkedin"></i> View on LinkedIn</a>
                </div>
            `;
                header.innerHTML = headerHtml;

                // Sections visibility toggle
                toggleSection('aboutSection', 'aboutText', profile.about, false);
                toggleSection('fullTextSection', 'fullTextContent', profile.full_text, false);

                // Contact Info 
                // We'll dynamically inject this since there wasn't a placeholder container originally
                let contactHtml = '';
                if (profile.contact_info && Object.keys(profile.contact_info).length > 0) {
                    contactHtml = `<div class="timeline-card" style="border-left-color: #eab308; background: rgba(234, 179, 8, 0.1);">`;
                    for (const [k, v] of Object.entries(profile.contact_info)) {
                        contactHtml += `<div style="margin-bottom:4px;"><strong style="text-transform:capitalize; color:#fde047;">${escapeHtml(k)}:</strong> ${escapeHtml(v)}</div>`;
                    }
                    contactHtml += `</div>`;
                }

                // Current Position
                const currentJobSec = document.getElementById('currentJobSection');
                const currentJobCont = document.getElementById('currentJobContainer');
                if (contactHtml || (profile.current_job && (profile.current_job.title || profile.current_job.company))) {
                    let jobHtml = contactHtml; 
                    if (profile.current_job && (profile.current_job.title || profile.current_job.company)) {
                        let job = profile.current_job;
                        jobHtml += `
                        <div class="timeline-card" style="border-left-color: var(--secondary-accent);">
                            <h4>${escapeHtml(job.title)}</h4>
                            <div class="company">${escapeHtml(job.company)}</div>
                            <div class="meta">
                                ${job.duration ? `<span><i class="far fa-clock"></i> ${escapeHtml(job.duration)}</span>` : ''}
                                ${job.location ? `<span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(job.location)}</span>` : ''}
                            </div>
                        </div>
                        `;
                    }
                    currentJobCont.innerHTML = jobHtml;
                    currentJobSec.style.display = 'block';
                } else {
                    currentJobSec.style.display = 'none';
                }

                // Experience
                renderTimelineList('experienceSection', 'experienceContainer', profile.experience, (exp) => `
                <h4>${escapeHtml(exp.title)}</h4>
                <div class="company">${escapeHtml(exp.company)}</div>
                <div class="meta">
                    ${exp.duration ? `<span><i class="far fa-clock"></i> ${escapeHtml(exp.duration)}</span>` : ''}
                    ${exp.location ? `<span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(exp.location)}</span>` : ''}
                </div>
            `);

                // Qualifications
                renderTimelineList('qualificationsSection', 'qualificationsContainer', profile.qualifications, (q) => `
                <h4>${escapeHtml(q.institution)}</h4>
                <div class="company" style="color:var(--text-main);">${escapeHtml(q.degree)}</div>
                ${q.dates ? `<div class="meta"><span><i class="far fa-calendar-alt"></i> ${escapeHtml(q.dates)}</span></div>` : ''}
            `, 'var(--success-color)');

                // Certifications
                renderTimelineList('certificationsSection', 'certificationsContainer', profile.certifications, (c) => `
                <h4>${escapeHtml(c.name)}</h4>
                <div class="company" style="color:var(--text-main);">${escapeHtml(c.issuer)}</div>
                ${c.date ? `<div class="meta"><span><i class="far fa-calendar-alt"></i> ${escapeHtml(c.date)}</span></div>` : ''}
            `, 'var(--warning-color)');

                // Skills
                const skillsSec = document.getElementById('skillsSection');
                const skillsCont = document.getElementById('skillsContainer');
                if (profile.skills && profile.skills.length) {
                    skillsCont.innerHTML = `<div style="display:flex; flex-wrap:wrap; gap:8px; padding:4px 0;">${profile.skills.map(s => `<span style="background:rgba(99,102,241,0.15); border:1px solid rgba(99,102,241,0.3); color:#c7d2fe; padding:5px 12px; border-radius:20px; font-size:0.85rem;">${escapeHtml(s.skill)}${s.endorsements ? ` <small style="opacity:0.6;">(${escapeHtml(s.endorsements)})</small>` : ''}</span>`).join('')}</div>`;
                    skillsSec.style.display = 'block';
                } else { skillsSec.style.display = 'none'; }

                // Languages
                const langSec = document.getElementById('languagesSection');
                const langCont = document.getElementById('languagesContainer');
                if (profile.languages && profile.languages.length) {
                    langCont.innerHTML = `<div style="display:flex; flex-wrap:wrap; gap:8px; padding:4px 0;">${profile.languages.map(l => `<span style="background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); color:#6ee7b7; padding:5px 12px; border-radius:20px; font-size:0.85rem;"><i class="fas fa-language" style="margin-right:5px;"></i>${escapeHtml(l.language)}${l.proficiency ? ` — <small>${escapeHtml(l.proficiency)}</small>` : ''}</span>`).join('')}</div>`;
                    langSec.style.display = 'block';
                } else { langSec.style.display = 'none'; }

                // Volunteer
                renderTimelineList('volunteerSection', 'volunteerContainer', profile.volunteer, (v) => `
                <h4>${escapeHtml(v.role)}</h4>
                <div class="company" style="color:var(--text-main);">${escapeHtml(v.organization)}</div>
                ${v.duration ? `<div class="meta"><span><i class="far fa-clock"></i> ${escapeHtml(v.duration)}</span></div>` : ''}
            `, '#f472b6');

                // Honors & Awards
                renderTimelineList('honorsSection', 'honorsContainer', profile.honors, (h) => `
                <h4>${escapeHtml(h.title)}</h4>
                <div class="company" style="color:var(--text-main);">${escapeHtml(h.issuer)}</div>
                ${h.date ? `<div class="meta"><span><i class="far fa-calendar-alt"></i> ${escapeHtml(h.date)}</span></div>` : ''}
            `, '#fbbf24');

                // Recommendations
                const recSec = document.getElementById('recommendationsSection');
                const recCont = document.getElementById('recommendationsContainer');
                if (profile.recommendations && profile.recommendations.length) {
                    recCont.innerHTML = profile.recommendations.map(r => `
                    <div class="timeline-card" style="border-left-color:#a78bfa;">
                        <h4 style="color:#c4b5fd;">${escapeHtml(r.recommender)}</h4>
                        ${r.title ? `<div class="company" style="color:var(--text-muted); font-size:0.85rem;">${escapeHtml(r.title)}</div>` : ''}
                        ${r.text ? `<p style="color:var(--text-main); margin-top:8px; font-style:italic; font-size:0.9rem;">&ldquo;${escapeHtml(r.text)}&rdquo;</p>` : ''}
                    </div>`).join('');
                    recSec.style.display = 'block';
                } else {
                    recCont.innerHTML = `<div class="timeline-card" style="border-left-color:#f59e0b; background:rgba(245,158,11,0.08); color:#fcd34d;"><i class="fas fa-info-circle"></i> None was received yet</div>`;
                    recSec.style.display = 'block';
                }

                document.getElementById('profileResult').style.display = 'block';
                document.getElementById('profileResult').scrollIntoView({ behavior: 'smooth' });
            }

            function toggleSectionJson(sectionKey, btn) {
                if (!activeProfileData) return;
                const container = document.getElementById(sectionKey + 'Json');
                if (!container) return;

                if (container.style.display === 'none' || !container.style.display) {
                    let dataToDisplay = activeProfileData[sectionKey];
                    container.textContent = JSON.stringify(dataToDisplay, null, 2);
                    container.style.display = 'block';
                    btn.innerHTML = '<i class="fas fa-eye-slash"></i> Hide JSON';
                } else {
                    container.style.display = 'none';
                    btn.innerHTML = '<i class="fas fa-code"></i> JSON';
                }
            }

            function renderBulkProfiles(profiles, searchName) {
                activeBulkData = profiles;
                activeProfileData = null;

                let extractedListHtml = '';
                profiles.forEach((p, idx) => {
                    const initials = (p.name || '?').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
                    const avatar = p.profile_picture
                        ? `<img src="${escapeHtml(p.profile_picture)}" style="width:45px;height:45px;border-radius:50%;object-fit:cover;border:1.5px solid var(--secondary-accent); flex-shrink:0;">`
                        : `<div style="width:45px;height:45px;border-radius:50%;background:linear-gradient(135deg, var(--primary-accent), var(--secondary-accent));color:white;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1rem;border:1.5px solid var(--secondary-accent);flex-shrink:0;">${initials}</div>`;

                    extractedListHtml += `
                    <div class="bulk-profile-card" onclick="viewSingleProfileFromBulk('${escapeHtml(p.profile_url)}')" 
                         style="display:flex; align-items:center; gap:15px; margin-bottom:12px; background: rgba(255,255,255,0.03); padding:12px; border-radius:10px; border:1px solid rgba(255,255,255,0.06); cursor:pointer; transition:all 0.2s;"
                         onmouseover="this.style.background='rgba(255,255,255,0.08)'; this.style.borderColor='var(--secondary-accent)';" 
                         onmouseout="this.style.background='rgba(255,255,255,0.03)'; this.style.borderColor='rgba(255,255,255,0.06)';">
                        ${avatar}
                        <div style="text-align:left; flex-grow:1;">
                            <div style="font-weight:bold; color:white; font-size:1rem; display:flex; justify-content:space-between; align-items:center; gap:10px;">
                                <span>${escapeHtml(p.name)}</span>
                                <span style="font-size:0.75rem; color:var(--secondary-accent); font-weight:normal; white-space:nowrap;"><i class="fas fa-chevron-right"></i> View Details</span>
                            </div>
                            ${p.headline ? `<div style="color:var(--text-muted); font-size:0.83rem; margin-top:2px;">${escapeHtml(p.headline)}</div>` : ''}
                        </div>
                    </div>
                `;
                });

                const container = document.getElementById('bulkProfilesContainer');
                container.innerHTML = `
                <div style="padding: 30px 20px; text-align: center; color: white;">
                    <i class="fas fa-check-circle" style="color: #10b981; font-size: 3rem; margin-bottom: 15px;"></i>
                    <h3 style="font-size: 1.5rem; margin-bottom: 10px;">Scrape Complete for "${escapeHtml(searchName || 'Multi-Profile Search')}"</h3>
                    <p style="color: var(--text-muted); font-size: 1.1rem; margin-bottom: 20px;">Successfully extracted ${profiles.length} profile${profiles.length === 1 ? '' : 's'}. Click on any profile card below to view details, or use the download options.</p>
                    
                    <div style="text-align:left; max-width: 650px; margin: 0 auto; background: rgba(0,0,0,0.2); border-radius:12px; padding:20px; border:1px solid rgba(255,255,255,0.05);">
                        <h4 style="margin-top:0; margin-bottom:15px; color:#c7d2fe; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:10px;">Extracted Profiles (Click to Expand Details)</h4>
                        ${extractedListHtml}
                    </div>
                </div>
            `;
                document.getElementById('bulkResult').style.display = 'block';
                document.getElementById('bulkResult').scrollIntoView({ behavior: 'smooth' });
            }

            window.viewSingleProfileFromBulk = function(profileUrl) {
                const profiles = activeBulkData || window._refLookupProfiles || [];
                const matched = profiles.find(p => p.profile_url === profileUrl);
                if (matched) {
                    renderProfile(matched);
                }
            };


            function toggleSection(sectionId, textId, value, isHtml) {
                const section = document.getElementById(sectionId);
                if (value) {
                    const txt = document.getElementById(textId);
                    if (isHtml) txt.innerHTML = value;
                    else txt.textContent = value;
                    section.style.display = 'block';
                } else {
                    section.style.display = 'none';
                }
            }

            function renderTimelineList(sectionId, containerId, list, renderer, borderColor) {
                const section = document.getElementById(sectionId);
                const container = document.getElementById(containerId);
                if (list && list.length) {
                    let html = '';
                    list.forEach(item => {
                        html += `
                        <div class="timeline-card" ${borderColor ? `style="border-left-color:${borderColor};"` : ''}>
                            ${renderer(item)}
                        </div>
                    `;
                    });
                    container.innerHTML = html;
                    section.style.display = 'block';
                } else {
                    section.style.display = 'none';
                }
            }

            // Export handlers
            async function exportData(format, isBulk = false) {
                const profiles = isBulk ? (activeBulkData || window._refLookupProfiles || (activeProfileData ? [activeProfileData] : [])) : (activeProfileData ? [activeProfileData] : (activeBulkData || window._refLookupProfiles));
                if (!profiles || !profiles.length) {
                    showSearchError('No data to export');
                    return;
                }
                const data = { profiles };
                try {
                    const res = await fetch('/api/scraper/export', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ data, format })
                    });
                    if (res.ok) {
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `linkedin_export_${isBulk || profiles.length > 1 ? 'bulk' : 'profile'}.${format}`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                    } else {
                        showSearchError('Export failed');
                    }
                } catch (e) {
                    showSearchError('Export error: ' + e.message);
                }
            }

            function exportJSON() { exportData('json', false); }
            function exportCSV() { exportData('csv', false); }
            async function exportPDF() {
                const profiles = activeProfileData ? [activeProfileData] : (activeBulkData || window._refLookupProfiles);
                if (!profiles || !profiles.length) { showSearchError('No profile loaded to export.'); return; }
                const isBulk = profiles.length > 1;
                const endpoint = isBulk ? '/api/export-bulk-pdf' : '/api/export-profile-pdf';
                const body = isBulk ? { profiles } : { profile: profiles[0] };
                try {
                    const res = await fetch(endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    });
                    if (res.ok) {
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = isBulk ? `bulk_profiles_export.pdf` : `${(profiles[0].name || 'profile').replace(/\s+/g, '_')}_profile.pdf`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                        showSearchSuccess('PDF exported successfully.');
                    } else {
                        const err = await res.json().catch(() => ({}));
                        showSearchError('PDF export failed: ' + (err.error || 'Unknown error'));
                    }
                } catch (e) {
                    showSearchError('PDF export error: ' + e.message);
                }
            }

            function exportBulkJSON() { exportData('json', true); }
            function exportBulkCSV() { exportData('csv', true); }
            async function exportBulkPDF() {
                const profiles = activeBulkData || window._refLookupProfiles || (activeProfileData ? [activeProfileData] : []);
                if (!profiles || !profiles.length) { showSearchError('No bulk profiles loaded.'); return; }
                try {
                    const res = await fetch('/api/export-bulk-pdf', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ profiles })
                    });
                    if (res.ok) {
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `bulk_profiles_export.pdf`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                        showSearchSuccess('Bulk PDF exported successfully.');
                    } else {
                        const err = await res.json().catch(() => ({}));
                        showSearchError('Bulk PDF export failed: ' + (err.error || 'Unknown error'));
                    }
                } catch (e) {
                    showSearchError('Bulk PDF export error: ' + e.message);
                }
            }
            // ════════════════════════════════════════════════════════════
            // ██  MY SEARCHES — localStorage-based search history      ██
            // ════════════════════════════════════════════════════════════

            const HISTORY_KEY = 'persona_search_history';
            const MAX_HISTORY = 50;

            function getSearchHistory() {
                try {
                    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
                } catch (e) { return []; }
            }

            function saveSearchHistory(history) {
                localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
            }

            function addToSearchHistory(name, refNumber, status, extra = {}) {
                const history = getSearchHistory();
                // Don't duplicate if same name+ref already exists
                const existing = history.find(h => h.name === name && h.ref === refNumber);
                if (existing) {
                    existing.status = status;
                    existing.updated_at = new Date().toISOString();
                    Object.assign(existing, extra);
                    saveSearchHistory(history);
                    renderSearchHistory();
                    return;
                }
                history.unshift({
                    name,
                    ref: refNumber,
                    status,
                    searched_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                    ...extra
                });
                saveSearchHistory(history);
                renderSearchHistory();
            }

            function updateSearchHistory(name, status, refNumber, extra = {}) {
                const history = getSearchHistory();
                // Find by ref first, then by name
                let entry = refNumber ? history.find(h => h.ref === refNumber) : null;
                if (!entry) entry = history.find(h => h.name === name);
                if (entry) {
                    entry.status = status;
                    entry.updated_at = new Date().toISOString();
                    Object.assign(entry, extra);
                    saveSearchHistory(history);
                    renderSearchHistory();
                }
            }

            function clearSearchHistory() {
                localStorage.removeItem(HISTORY_KEY);
                renderSearchHistory();
            }

            function renderSearchHistory() {
                const history = getSearchHistory();
                const container = document.getElementById('searchHistoryList');
                const clearBtn = document.getElementById('btnClearHistory');

                if (!history.length) {
                    container.innerHTML = `
                        <div class="history-empty">
                            <i class="fas fa-inbox"></i>
                            No searches yet. Use the search form above to get started.
                        </div>
                    `;
                    clearBtn.style.display = 'none';
                    return;
                }

                clearBtn.style.display = 'inline-flex';

                const statusIcons = {
                    completed: 'fa-check-circle',
                    pending: 'fa-clock',
                    queued: 'fa-clock',
                    in_progress: 'fa-spinner spinner',
                    failed: 'fa-times-circle'
                };
                const statusLabels = {
                    completed: 'Completed',
                    pending: 'In Queue',
                    queued: 'In Queue',
                    in_progress: 'Scraping',
                    failed: 'Failed'
                };

                let html = '';
                history.forEach((item, idx) => {
                    const icon = statusIcons[item.status] || 'fa-question-circle';
                    const label = statusLabels[item.status] || item.status;
                    const statusClass = item.status === 'queued' ? 'pending' : item.status;
                    const timeAgo = getTimeAgo(item.searched_at);
                    const initials = (item.name || '?').split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();

                    const isViewable = item.status === 'completed';
                    const isActive = item.status === 'pending' || item.status === 'queued' || item.status === 'in_progress';

                    let actionBtn = '';
                    if (isViewable) {
                        actionBtn = `<button class="btn-history-view" onclick="viewHistoryResult(${idx})"><i class="fas fa-eye"></i> View</button>`;
                    } else if (isActive) {
                        const queueInfo = item.queue_position ? ` (#${item.queue_position})` : '';
                        actionBtn = `<button class="btn-history-view" disabled><i class="fas fa-${icon}"></i> ${label}${queueInfo}</button>`;
                    } else if (item.status === 'failed') {
                        actionBtn = `<button class="btn-history-view" onclick="retryHistorySearch(${idx})"><i class="fas fa-redo"></i> Retry</button>`;
                    }

                    let queueBadge = '';
                    if (isActive && item.queue_position && item.queue_position > 1) {
                        queueBadge = `<span style="font-size:0.72rem; color:#c4b5fd;">Position ${item.queue_position} of ${item.queue_total || '?'}</span>`;
                    }

                    html += `
                        <div class="history-item">
                            <div class="history-item-icon ${statusClass}">
                                <i class="fas ${icon}"></i>
                            </div>
                            <div class="history-item-details">
                                <div class="history-item-name">${escapeHtml(item.name)}</div>
                                <div class="history-item-meta">
                                    <span class="history-status-badge ${statusClass}"><i class="fas ${icon}"></i> ${label}</span>
                                    <span>${timeAgo}</span>
                                    ${item.profiles_count ? `<span>${item.profiles_count} profile${item.profiles_count > 1 ? 's' : ''}</span>` : ''}
                                    ${queueBadge}
                                </div>
                            </div>
                            ${actionBtn}
                        </div>
                    `;
                });

                container.innerHTML = html;
            }

            function getTimeAgo(isoDate) {
                if (!isoDate) return '';
                const seconds = Math.floor((new Date() - new Date(isoDate)) / 1000);
                if (seconds < 60) return 'just now';
                const minutes = Math.floor(seconds / 60);
                if (minutes < 60) return `${minutes}m ago`;
                const hours = Math.floor(minutes / 60);
                if (hours < 24) return `${hours}h ago`;
                const days = Math.floor(hours / 24);
                return `${days}d ago`;
            }

            async function viewHistoryResult(idx) {
                const history = getSearchHistory();
                const item = history[idx];
                if (!item) return;

                // Try to fetch by reference number first
                const ref = item.ref;
                if (ref && !ref.startsWith('cached_')) {
                    try {
                        const res = await fetch('/api/client/lookup-by-reference', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ reference_number: ref })
                        });
                        const data = await res.json();
                        if (data.success && data.profiles && data.profiles.length) {
                            renderBulkProfiles(data.profiles, item.name);
                            document.getElementById('bulkResult').scrollIntoView({ behavior: 'smooth' });
                            return;
                        }
                    } catch (e) { console.error('viewHistoryResult ref lookup error', e); }
                }

                // Fallback: fetch by name via scrape-status
                try {
                    const url = '/api/client/scrape-status?name=' + encodeURIComponent(item.name)
                              + (ref ? '&task_id=' + encodeURIComponent(ref) : '');
                    const res = await fetch(url);
                    const data = await res.json();
                    if (data.profiles && data.profiles.length) {
                        renderBulkProfiles(data.profiles, item.name);
                        document.getElementById('bulkResult').scrollIntoView({ behavior: 'smooth' });
                    } else {
                        showSearchError('No profiles found for this search. The data may have been cleared.');
                    }
                } catch (e) {
                    showSearchError('Error loading results: ' + e.message);
                }
            }

            async function retryHistorySearch(idx) {
                const history = getSearchHistory();
                const item = history[idx];
                if (!item) return;

                // Pre-fill the search fields and trigger search
                const names = item.name.split(' ');
                document.getElementById('firstName').value = names[0] || '';
                document.getElementById('lastName').value = names.slice(1).join(' ') || '';
                document.getElementById('usernameKeyword').value = '';
                document.getElementById('company').value = '';

                // Remove the failed entry
                history.splice(idx, 1);
                saveSearchHistory(history);
                renderSearchHistory();

                // Scroll up and trigger search
                document.getElementById('tabDirectSearch').scrollIntoView({ behavior: 'smooth' });
                searchAndExtract();
            }

            // ── Refresh active history items periodically ──
            setInterval(() => {
                const history = getSearchHistory();
                const activeItems = history.filter(h => h.status === 'pending' || h.status === 'queued' || h.status === 'in_progress');
                if (!activeItems.length) return;

                activeItems.forEach(async (item) => {
                    try {
                        let url = '/api/client/scrape-status?name=' + encodeURIComponent(item.name);
                        if (item.ref && !item.ref.startsWith('cached_')) {
                            url = '/api/client/scrape-status?task_id=' + encodeURIComponent(item.ref) + '&name=' + encodeURIComponent(item.name);
                        }
                        const res = await fetch(url);
                        const data = await res.json();

                        if (data.status === 'completed' && data.profiles) {
                            updateSearchHistory(item.name, 'completed', item.ref, {profiles_count: data.profiles.length});
                        } else if (data.status === 'failed') {
                            updateSearchHistory(item.name, 'failed', item.ref, {error: data.error});
                        } else if (data.status === 'pending' || data.status === 'in_progress') {
                            updateSearchHistory(item.name, data.status, item.ref, {
                                queue_position: data.queue_position,
                                queue_total: data.queue_total
                            });
                        }
                    } catch (e) { /* ignore poll errors */ }
                });
            }, 6000);

            // Render on page load
            renderSearchHistory();
        