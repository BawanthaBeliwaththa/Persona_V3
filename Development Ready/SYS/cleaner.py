"""
Profile Sanitization, Noise Filtering and Data Formatting Module
================================================================
Cleans raw scraped LinkedIn data, removes UI chrome/footer artifacts,
deduplicates skills and education items, and formats fields for CSV/JSON exports.
"""

from typing import Any, Dict, List, Optional, Set
import re

# ── LinkedIn Noise & Footer Tokens ──────────────────────────────────────────
_LINKEDIN_FOOTER_TOKENS: Set[str] = {
    'accessibility', 'talent solutions', 'community guidelines', 'careers',
    'marketing solutions', 'privacy & terms', 'ad choices', 'advertising',
    'sales solutions', 'mobile', 'small business', 'safety center',
    'linkedin corporation', 'questions?', 'manage your account and privacy',
    'go to your settings.', 'recommendation transparency',
    'learn more about recommended content.', 'select language',
    'visit our help center.', 'about',
    # LinkedIn language names that appear in "select language" dropdown
    'العربية (arabic)', 'বাংলা (bangla)', 'čeština (czech)', 'dansk (danish)',
    'deutsch (german)', 'ελληνικά (greek)', 'english (english)',
    'español (spanish)', 'فارسی (persian)', 'suomi (finnish)',
    'français (french)', 'हिंदी (hindi)', 'magyar (hungarian)',
    'bahasa indonesia (indonesian)', 'italiano (italian)', 'עברית (hebrew)',
    '日本語 (japanese)', '한국어 (korean)', 'मराठी (marathi)',
    'bahasa malaysia (malay)', 'nederlands (dutch)', 'norsk (norwegian)',
    'ਪੰਜਾਬੀ (punjabi)', 'polski (polish)', 'português (portuguese)',
    'română (romanian)', 'русский (russian)', 'svenska (swedish)',
    'తెలుగు (telugu)', 'ภาษาไทย (thai)', 'tagalog (tagalog)',
    'türkçe (turkish)', 'українська (ukrainian)', 'tiếng việt (vietnamese)',
    '简体中文 (chinese (simplified))', '正體中文 (chinese (traditional))',
    'show credential', 'badge',
}

_REAL_LANGUAGE_NAMES: Set[str] = {
    'english', 'sinhalese', 'sinhala', 'tamil', 'french', 'german',
    'spanish', 'portuguese', 'italian', 'dutch', 'russian', 'chinese',
    'japanese', 'korean', 'arabic', 'hindi', 'urdu', 'bengali',
    'malay', 'indonesian', 'turkish', 'polish', 'swedish', 'norwegian',
    'danish', 'finnish', 'greek', 'hebrew', 'thai', 'vietnamese',
    'tagalog', 'punjabi', 'marathi', 'telugu', 'ukrainian', 'romanian',
    'czech', 'hungarian', 'persian', 'farsi',
}


def _clean_value(v: Any) -> Optional[Any]:
    """Return None if a value is null-like, otherwise return stripped string or value."""
    if v is None:
        return None
    if isinstance(v, str):
        stripped = v.strip()
        if stripped.lower() in ('none', 'null', 'n/a', 'na', ''):
            return None
        return stripped
    return v


def _clean_list(lst: List[Any]) -> List[Any]:
    """Remove null/empty items from a list; recursively clean dicts within it."""
    if not lst or not isinstance(lst, list):
        return []
    result = []
    for item in lst:
        if isinstance(item, dict):
            cleaned = clean_profile_dict(item)
            if cleaned:
                result.append(cleaned)
        elif item is not None:
            v = _clean_value(item)
            if v is not None:
                result.append(v)
    return result


def clean_profile_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively remove null/empty keys from a dictionary."""
    if not d or not isinstance(d, dict):
        return {}
    cleaned = {}
    for k, v in d.items():
        if isinstance(v, dict):
            c = clean_profile_dict(v)
            if c:
                cleaned[k] = c
        elif isinstance(v, list):
            c = _clean_list(v)
            if c:
                cleaned[k] = c
        else:
            c = _clean_value(v)
            if c is not None:
                cleaned[k] = c
    return cleaned


def _is_junk_text(text: Optional[str]) -> bool:
    """Return True if the string is recognised LinkedIn footer/UI garbage."""
    if not text:
        return False
    t = text.strip().lower()
    if t in _LINKEDIN_FOOTER_TOKENS:
        return True
    if t.startswith('linkedin corporation'):
        return True
    if 'select language' in t:
        return True
    return False


def _is_junk_entry(entry: Any) -> bool:
    """Return True if a dict entry looks like scraped UI garbage, not real content."""
    if not isinstance(entry, dict):
        return False
    values = [str(v).strip() for v in entry.values() if v]
    if values and all(_is_junk_text(v) for v in values):
        return True
    for key in ('duration', 'date', 'dates'):
        v = entry.get(key, '')
        if v and _is_junk_text(str(v)):
            return True
    return False


def _is_real_language(lang_name: Optional[str]) -> bool:
    """True only if the name looks like a real human language, not a nav item."""
    if not lang_name:
        return False
    t = lang_name.strip().lower()
    if t in _REAL_LANGUAGE_NAMES:
        return True
    if _is_junk_text(t):
        return False
    junk_indicators = [
        'solutions', 'guidelines', 'corporation', 'accessibility',
        'advertising', 'privacy', 'terms', 'choices', 'credential',
        'settings', 'transparency', 'center', 'questions', 'careers',
    ]
    for ind in junk_indicators:
        if ind in t:
            return False
    return False


def _clean_about(about_text: Optional[str]) -> str:
    """Strip footer/language-selector content and 'more...' artifacts from the About field."""
    if not about_text:
        return ''
    cutoff_markers = [
        'Accessibility\nTalent Solutions',
        '\nAccessibility\n',
        'Talent Solutions\nCommunity Guidelines',
        'Select language\n',
        'LinkedIn Corporation',
    ]
    text = about_text
    for marker in cutoff_markers:
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx].strip()

    for junk in ['… more', '...more', '... more', '…more', 'more...', '... see more', 'see more', '…']:
        if text.endswith(junk):
            text = text[:-len(junk)].strip()

    lines = text.split('\n')
    clean_lines = []
    for ln in lines:
        s = ln.strip()
        if not s or _is_junk_text(s):
            continue
        s = s.replace('… more', '').replace('...more', '').replace('more...', '').replace('…', '')
        if s.lower() in ('about', 'see more', 'show more'):
            continue
        clean_lines.append(s)
    return '\n'.join(clean_lines).strip()


def _clean_experience_list(exp_list: List[Any]) -> List[Dict[str, Any]]:
    """Remove junk entries from experience; keep only real jobs."""
    if not exp_list:
        return []
    result = []
    seen = set()
    for e in exp_list:
        if not isinstance(e, dict):
            continue
        if _is_junk_entry(e):
            continue
        title = (e.get('title') or '').strip()
        company = (e.get('company') or '').strip()
        if _is_junk_text(title) or _is_junk_text(company):
            continue
        if not title and not company:
            continue
        key = (title.lower(), company.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(e)
    return result


def _clean_education_list(edu_list: List[Any]) -> List[Dict[str, Any]]:
    """Remove junk entries from education/qualifications."""
    if not edu_list:
        return []
    result = []
    seen = set()
    for e in edu_list:
        if not isinstance(e, dict):
            continue
        if _is_junk_entry(e):
            continue
        inst = (e.get('institution') or '').strip()
        degree = (e.get('degree') or '').strip()
        if _is_junk_text(inst) or _is_junk_text(degree):
            continue
        if not inst and not degree:
            continue
        if inst.lower().startswith('skills:') or degree.lower().startswith('skills:'):
            continue
        key = (inst.lower(), degree.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(e)
    return result


def _clean_certification_list(cert_list: List[Any]) -> List[Dict[str, Any]]:
    """Remove junk entries from certifications."""
    if not cert_list:
        return []
    result = []
    seen = set()
    for c in cert_list:
        if not isinstance(c, dict):
            continue
        if _is_junk_entry(c):
            continue
        name = (c.get('name') or '').strip()
        issuer = (c.get('issuer') or '').strip()
        if _is_junk_text(name) or _is_junk_text(issuer):
            continue
        if name.lower() in ('show credential', 'badge', ''):
            continue
        if issuer.lower().startswith('skills:'):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(c)
    return result


def _clean_languages_list(lang_list: List[Any]) -> List[Dict[str, Any]]:
    """Keep only real human languages, discard footer-nav garbage."""
    if not lang_list:
        return []
    result = []
    seen = set()
    for l in lang_list:
        if not isinstance(l, dict):
            continue
        lang_name = (l.get('language') or '').strip()
        if not lang_name or not _is_real_language(lang_name):
            continue
        key = lang_name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(l)
    return result


def _clean_honors_list(hon_list: List[Any]) -> List[Dict[str, Any]]:
    """Remove junk entries from honors/awards."""
    if not hon_list:
        return []
    result = []
    seen = set()
    for h in hon_list:
        if not isinstance(h, dict):
            continue
        if _is_junk_entry(h):
            continue
        title = (h.get('title') or '').strip()
        issuer = (h.get('issuer') or '').strip()
        if _is_junk_text(title) or _is_junk_text(issuer):
            continue
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(h)
    return result


def _clean_recommendations_list(rec_list: List[Any]) -> List[Dict[str, Any]]:
    """Remove junk entries from recommendations."""
    if not rec_list:
        return []
    result = []
    for r in rec_list:
        if not isinstance(r, dict):
            continue
        if _is_junk_entry(r):
            continue
        recommender = (r.get('recommender') or '').strip()
        text_val = (r.get('text') or '').strip()
        title = (r.get('title') or '').strip()
        if _is_junk_text(recommender) or _is_junk_text(title):
            continue
        if "haven't received" in recommender.lower() or 'try asking' in title.lower():
            continue
        if not recommender and not text_val:
            continue
        result.append(r)
    return result


def _clean_skills_list(skills_list: List[Any]) -> List[Dict[str, str]]:
    """Deduplicate and remove junk from skills list."""
    if not skills_list:
        return []
    seen = set()
    result = []
    for s in skills_list:
        if isinstance(s, dict):
            name = (s.get('skill') or s.get('name') or '').strip()
        elif isinstance(s, str):
            name = s.strip()
        else:
            continue
        if not name or _is_junk_text(name):
            continue
        if len(name) > 80:
            continue
        if ' at ' in name.lower() and 'intern' in name.lower():
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({'skill': name})
    return result


def _clean_volunteer_list(vol_list: List[Any]) -> List[Dict[str, Any]]:
    """Remove junk entries from volunteer experience."""
    if not vol_list:
        return []
    result = []
    seen = set()
    junk_indicators = [
        'questions?', 'manage your account', 'recommendation transparency',
        'help center', 'settings', 'recommended content', 'select language',
        'mobile', 'visit our help center.'
    ]
    for v in vol_list:
        if not isinstance(v, dict):
            continue
        if _is_junk_entry(v):
            continue
        role = (v.get('role') or '').strip()
        org = (v.get('organization') or v.get('company') or '').strip()
        if _is_junk_text(role) or _is_junk_text(org):
            continue
        if not role and not org:
            continue
        r_low = role.lower()
        o_low = org.lower()
        if any(ind in r_low or ind in o_low for ind in junk_indicators):
            continue
        if ('(' in o_low and ')' in o_low) or ('(' in r_low and ')' in r_low):
            continue
        if _is_real_language(org) or _is_real_language(role):
            continue
        key = (role.lower(), org.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(v)
    return result


def sanitize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep-clean a raw scraped profile:
    - Strips LinkedIn footer/nav junk from every section
    - Removes null/empty values
    - Deduplicates skills
    - Cleans the About text
    Returns a new dict with clean, structured data.
    """
    if not profile or not isinstance(profile, dict):
        return {}

    p = dict(profile)

    # Clean About field
    p['about'] = _clean_about(p.get('about', '') or '')

    # Clean list sections
    p['experience'] = _clean_experience_list(p.get('experience') or p.get('experiences') or [])
    p['experiences'] = p['experience']
    p['qualifications'] = _clean_education_list(p.get('qualifications') or p.get('education') or [])
    p['education'] = p['qualifications']
    p['certifications'] = _clean_certification_list(p.get('certifications') or [])
    p['languages'] = _clean_languages_list(p.get('languages') or [])
    p['honors'] = _clean_honors_list(p.get('honors') or [])
    p['recommendations'] = _clean_recommendations_list(p.get('recommendations') or [])
    p['skills'] = _clean_skills_list(p.get('skills') or [])
    p['volunteer'] = _clean_volunteer_list(p.get('volunteer') or [])
    p['contact_info'] = p.get('contact_info') or {}

    # Clean current_job
    cj = p.get('current_job')
    if cj and isinstance(cj, dict):
        if _is_junk_entry(cj):
            p['current_job'] = {}

    # Clean top-level fields
    for field in ('name', 'headline', 'location', 'profile_url', 'profile_picture',
                  'connections', 'scraped_at'):
        v = p.get(field)
        if v is not None and isinstance(v, str):
            cleaned = v.strip()
            if cleaned.lower() in ('none', 'null', 'n/a', 'na', ''):
                p[field] = ''
            else:
                p[field] = cleaned

    # Preserve is_premium boolean and contact_info dictionary
    p['is_premium'] = bool(profile.get('is_premium', False))
    if 'contact_info' in profile and isinstance(profile['contact_info'], dict) and profile['contact_info']:
        p['contact_info'] = profile['contact_info']

    # Remove empty lists/dicts to keep JSON clean
    for k in list(p.keys()):
        v = p[k]
        if v == [] or v == {} or v == '':
            if k not in ('name', 'headline', 'location', 'profile_url', 'is_premium', 'contact_info'):
                del p[k]

    return p


# Backward-compatible alias
def clean_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    return sanitize_profile(profile)


# ── CSV Format Helpers ───────────────────────────────────────────────────────

def format_contact_info_for_csv(contact_info: Any) -> str:
    """Turn contact_info dict into a readable string."""
    if not contact_info or not isinstance(contact_info, dict):
        return ''
    parts = []
    for k, v in contact_info.items():
        if v:
            parts.append(f"{str(k).capitalize()}: {v}")
    return '; '.join(parts)


def format_experience_for_csv(exp_list: List[Any]) -> str:
    """Turn experience list into a human-readable semicolon-separated string."""
    if not exp_list:
        return ''
    parts = []
    for e in exp_list:
        if not isinstance(e, dict):
            continue
        title = (e.get('title') or '').strip()
        company = (e.get('company') or '').strip()
        dur = (e.get('duration') or '').strip()
        pieces = []
        if title:
            pieces.append(title)
        if company:
            pieces.append(f'at {company}')
        if dur:
            pieces.append(f'({dur})')
        if pieces:
            parts.append(' '.join(pieces))
    return '; '.join(parts)


def format_education_for_csv(edu_list: List[Any]) -> str:
    """Turn education/qualifications list into a readable string."""
    if not edu_list:
        return ''
    parts = []
    for e in edu_list:
        if not isinstance(e, dict):
            continue
        inst = (e.get('institution') or '').strip()
        degree = (e.get('degree') or '').strip()
        dates = (e.get('dates') or '').strip()
        pieces = []
        if inst:
            pieces.append(inst)
        if degree:
            pieces.append(degree)
        if dates:
            pieces.append(f'({dates})')
        if pieces:
            parts.append(' | '.join(pieces))
    return '; '.join(parts)


def format_certifications_for_csv(cert_list: List[Any]) -> str:
    """Turn certifications list into a readable string."""
    if not cert_list:
        return ''
    parts = []
    for c in cert_list:
        if not isinstance(c, dict):
            continue
        name = (c.get('name') or '').strip()
        issuer = (c.get('issuer') or '').strip()
        date = (c.get('date') or '').strip()
        pieces = []
        if name:
            pieces.append(name)
        if issuer:
            pieces.append(f'by {issuer}')
        if date:
            pieces.append(f'({date})')
        if pieces:
            parts.append(' '.join(pieces))
    return '; '.join(parts)


def format_skills_for_csv(skills_list: List[Any]) -> str:
    """Turn skills list into a comma-separated readable string."""
    if not skills_list:
        return ''
    parts = []
    for s in skills_list:
        if isinstance(s, dict):
            name = (s.get('skill') or s.get('name') or '').strip()
            if name:
                parts.append(name)
        elif isinstance(s, str):
            s = s.strip()
            if s:
                parts.append(s)
    return ', '.join(parts)


def format_current_job_for_csv(job: Any) -> str:
    """Turn current_job dict into a readable Title at Company string."""
    if not job or not isinstance(job, dict):
        return ''
    title = (job.get('title') or '').strip()
    company = (job.get('company') or '').strip()
    if title and company:
        return f'{title} at {company}'
    return title or company
