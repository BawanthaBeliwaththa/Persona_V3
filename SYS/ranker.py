"""
Sri Lankan LinkedIn Profile Ranker
====================================
A weighted ML scoring model that ranks LinkedIn profiles by:
  1. Profile strength  (completeness + richness of each section)
  2. Field-aligned follower relevance (connections in same job-field category)

Only profiles geo-located in Sri Lanka are considered.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Sri Lanka location keywords
# ---------------------------------------------------------------------------
SL_KEYWORDS: List[str] = [
    "sri lanka", "srilanka", "colombo", "kandy", "galle", "negombo",
    "jaffna", "trincomalee", "batticaloa", "ratnapura", "kurunegala",
    "anuradhapura", "polonnaruwa", "badulla", "matara", "hambantota",
    "nuwara eliya", "kegalle", "kalutara", "gampaha", "puttalam",
    "mannar", "vavuniya", "mullaitivu", "kilinochchi", "ampara",
    "moneragala", "matale", "lk",
]

# ---------------------------------------------------------------------------
# Job-field taxonomy  (category → keyword list)
# ---------------------------------------------------------------------------
FIELD_CATEGORIES: Dict[str, List[str]] = {
    "Software & IT": [
        "software", "developer", "engineer", "devops", "cloud", "sre",
        "backend", "frontend", "fullstack", "full stack", "data engineer",
        "machine learning", "ml", "ai", "artificial intelligence",
        "cyber", "security", "qa", "test", "scrum", "agile", "python",
        "java", "javascript", "typescript", "react", "angular", "node",
        "aws", "azure", "gcp", "docker", "kubernetes",
    ],
    "Data & Analytics": [
        "data science", "data analyst", "business intelligence", "bi",
        "analytics", "tableau", "power bi", "sql", "database", "etl",
        "data warehouse", "big data", "spark", "hadoop",
    ],
    "Finance & Banking": [
        "finance", "financial", "banking", "bank", "accountant", "accounting",
        "cfo", "treasury", "investment", "equity", "audit", "risk",
        "compliance", "actuar", "insurance",
    ],
    "Marketing & Sales": [
        "marketing", "digital marketing", "seo", "sem", "social media",
        "brand", "content", "growth", "sales", "business development",
        "account manager", "crm",
    ],
    "Healthcare & Medicine": [
        "doctor", "physician", "nurse", "medical", "health", "hospital",
        "pharma", "dentist", "surgeon", "therapist", "clinical",
    ],
    "Education & Research": [
        "teacher", "lecturer", "professor", "academic", "research",
        "scientist", "education", "curriculum", "tutor", "phd",
    ],
    "Engineering & Manufacturing": [
        "civil", "mechanical", "electrical", "structural", "manufacturing",
        "production", "quality control", "supply chain", "logistics",
        "procurement", "erp",
    ],
    "Design & Creative": [
        "designer", "graphic", "ux", "ui", "product design", "creative",
        "illustrator", "animator", "film", "video", "photography",
    ],
    "Legal & Compliance": [
        "lawyer", "attorney", "legal", "counsel", "compliance", "paralegal",
        "law",
    ],
    "Management & Leadership": [
        "ceo", "cto", "coo", "vp", "director", "manager", "head of",
        "president", "founder", "co-founder", "executive", "leadership",
    ],
    "HR & People": [
        "human resource", "hr ", "talent", "recruiter", "recruitment",
        "people operations", "training", "l&d",
    ],
}

# ---------------------------------------------------------------------------
# Scoring weights (total = 100 pts for profile, then followers add up to 50)
# ---------------------------------------------------------------------------
WEIGHTS = {
    # Profile completeness (max 100 pts)
    "has_headline":        8,
    "headline_length":     4,   # 0–4 pts based on length
    "has_about":           8,
    "about_length":        6,   # 0–6 pts
    "experience_count":    15,  # 3 pts per exp, max 15
    "experience_quality":  8,   # duration / description richness
    "education_count":     8,   # 4 pts per edu, max 8
    "skills_count":        10,  # 1 pt per skill, max 10
    "certifications":      8,   # 2 pts each, max 8
    "featured":            5,
    "connections_known":   6,   # bonus if connections extracted
    "profile_photo":       4,   # inferred from avatar flag
    "recommendations":     5,
    "volunteer":           3,
    "languages":           2,
    # Field-match followers (max 50 pts)
    "field_match_followers": 50,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return text.lower().strip() if text else ""


def is_sri_lankan(profile: Dict) -> bool:
    """Return True if the profile's location hints at Sri Lanka."""
    location = _normalise(profile.get("location", ""))
    headline  = _normalise(profile.get("headline", ""))
    about     = _normalise(profile.get("about", ""))

    haystack = f"{location} {headline} {about}"
    return any(kw in haystack for kw in SL_KEYWORDS)


def _extract_skills_text(skills_raw: Any) -> str:
    """Extract a single normalized lowercase text string from skills (handles list of str or list of dict)."""
    if not skills_raw:
        return ""
    if isinstance(skills_raw, list):
        items = []
        for s in skills_raw:
            if isinstance(s, str):
                items.append(s.strip())
            elif isinstance(s, dict):
                items.append(str(s.get("skill") or s.get("name") or "").strip())
        return " ".join(filter(None, items)).lower()
    if isinstance(skills_raw, str):
        return skills_raw.strip().lower()
    return ""


def detect_field_category(profile: Dict) -> str:
    """Detect the primary job-field category from headline, about, skills."""
    exps = profile.get("experiences", []) or profile.get("experience", [])
    text = " ".join([
        _normalise(profile.get("headline", "")),
        _normalise(profile.get("about", "")),
        _extract_skills_text(profile.get("skills", [])),
        " ".join(
            f"{e.get('title','')} {e.get('company','')}".lower()
            for e in exps if isinstance(e, dict)
        ),
    ])

    scores: Dict[str, int] = {}
    for category, keywords in FIELD_CATEGORIES.items():
        hit = sum(1 for kw in keywords if kw in text)
        if hit:
            scores[category] = hit

    if not scores:
        return "General"
    return max(scores, key=scores.get)


def _parse_connections(conn_str: str) -> int:
    """Parse LinkedIn connection strings like '500+', '1.2K followers'."""
    if not conn_str:
        return 0
    conn_str = conn_str.lower().replace(",", "").strip()
    # Handle "500+ connections"
    m = re.search(r"(\d+(?:\.\d+)?)\s*([km]?)\+?", conn_str)
    if not m:
        return 0
    val = float(m.group(1))
    suffix = m.group(2)
    if suffix == "k":
        val *= 1000
    elif suffix == "m":
        val *= 1_000_000
    return int(val)


def _experience_quality_score(experiences: List[Dict]) -> float:
    """Score experience items by description richness and multi-role presence."""
    if not experiences:
        return 0.0
    total = 0.0
    for exp in experiences:
        desc = exp.get("description", "")
        dur  = exp.get("duration", "")
        if desc and len(desc) > 80:
            total += 2
        elif desc:
            total += 1
        if dur:
            total += 0.5
    return min(total, WEIGHTS["experience_quality"])


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score_profile(profile: Dict) -> Dict:
    """
    Returns a dict with keys:
      - total_score (0–150)
      - profile_strength (0–100)
      - field_follower_score (0–50)
      - field_category (str)
      - breakdown (dict of component scores)
      - is_sri_lankan (bool)
    """
    breakdown: Dict[str, float] = {}

    # --- Profile completeness ---
    headline = profile.get("headline", "")
    about    = profile.get("about", "")
    exps     = profile.get("experiences", [])
    edus     = profile.get("education", [])
    skills   = profile.get("skills", [])
    certs    = profile.get("certifications", [])
    featured = profile.get("featured", [])
    recs     = profile.get("recommendations", [])
    volunteer= profile.get("volunteer", [])
    langs    = profile.get("languages", [])
    connections_str = profile.get("connections", "")

    # Headline
    breakdown["has_headline"] = WEIGHTS["has_headline"] if headline else 0
    hl_bonus = min(len(headline) / 120 * WEIGHTS["headline_length"], WEIGHTS["headline_length"])
    breakdown["headline_length"] = round(hl_bonus, 2)

    # About
    breakdown["has_about"] = WEIGHTS["has_about"] if about else 0
    ab_bonus = min(len(about) / 800 * WEIGHTS["about_length"], WEIGHTS["about_length"])
    breakdown["about_length"] = round(ab_bonus, 2)

    # Experience
    exp_pts = min(len(exps) * 3, WEIGHTS["experience_count"])
    breakdown["experience_count"] = exp_pts
    breakdown["experience_quality"] = _experience_quality_score(exps)

    # Education
    edu_pts = min(len(edus) * 4, WEIGHTS["education_count"])
    breakdown["education_count"] = edu_pts

    # Skills
    skill_pts = min(len(skills), WEIGHTS["skills_count"])
    breakdown["skills_count"] = skill_pts

    # Certifications
    cert_pts = min(len(certs) * 2, WEIGHTS["certifications"])
    breakdown["certifications"] = cert_pts

    # Featured
    breakdown["featured"] = WEIGHTS["featured"] if featured else 0

    # Connections
    conn_num = _parse_connections(connections_str)
    if conn_num >= 500:
        conn_score = WEIGHTS["connections_known"]
    elif conn_num > 0:
        conn_score = round(conn_num / 500 * WEIGHTS["connections_known"], 2)
    else:
        conn_score = 0
    breakdown["connections_known"] = conn_score

    # Profile photo (heuristic: name avatar is always present; 
    # we give 4 pts as a baseline since we can't verify photo existence)
    breakdown["profile_photo"] = WEIGHTS["profile_photo"]

    # Recommendations
    rec_pts = min(len(recs) * 2.5, WEIGHTS["recommendations"])
    breakdown["recommendations"] = round(rec_pts, 2)

    # Volunteer
    breakdown["volunteer"] = WEIGHTS["volunteer"] if volunteer else 0

    # Languages
    lang_pts = min(len(langs) * 1, WEIGHTS["languages"])
    breakdown["languages"] = lang_pts

    # Premium Account Authority & Verified Status
    is_prem = bool(profile.get("is_premium", False))
    breakdown["is_premium"] = 5.0 if is_prem else 0.0

    # Contact Info Availability
    has_contact = bool(profile.get("contact_info"))
    breakdown["has_contact_info"] = 5.0 if has_contact else 0.0

    profile_strength = round(sum(breakdown.values()), 2)
    profile_strength = min(profile_strength, 100.0)

    # --- Field-match follower score ---
    field_category = detect_field_category(profile)

    # We use connections count as a proxy for followers in the same field.
    # In a real scenario you'd have follower-by-industry data.
    # Scoring: the more connections + richer field signals, the higher the bonus.
    field_text = " ".join([
        _normalise(headline),
        _normalise(about),
        _extract_skills_text(skills),
    ])
    field_keywords = FIELD_CATEGORIES.get(field_category, [])
    field_hit_ratio = sum(1 for kw in field_keywords if kw in field_text) / max(len(field_keywords), 1)

    # Base: connection count contribution (normalised to 0-1, cap at 1000 conns)
    conn_ratio = min(conn_num / 1000, 1.0)

    # Combine: 60% connections, 40% field keyword density
    field_score = round(
        WEIGHTS["field_match_followers"] * (0.6 * conn_ratio + 0.4 * field_hit_ratio),
        2,
    )
    breakdown["field_match_followers"] = field_score

    total = round(profile_strength + field_score, 2)

    return {
        "total_score": total,
        "profile_strength": profile_strength,
        "field_follower_score": field_score,
        "field_category": field_category,
        "is_sri_lankan": is_sri_lankan(profile),
        "connections_count": conn_num,
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rank_sri_lankan_profiles(profiles: List[Dict]) -> List[Dict]:
    """
    Filter to Sri Lankan profiles, score each, sort descending.

    Returns a list of dicts:
      {
        "rank": 1,
        "profile": { ...original profile data... },
        "scoring": { total_score, profile_strength, field_follower_score,
                     field_category, connections_count, breakdown }
      }
    """
    results = []

    for profile in profiles:
        scoring = score_profile(profile)

        # Only include Sri Lankan profiles
        if not scoring["is_sri_lankan"]:
            continue

        results.append({
            "profile": profile,
            "scoring": scoring,
        })

    # Sort by total_score descending
    results.sort(key=lambda x: x["scoring"]["total_score"], reverse=True)

    # Assign ranks
    for i, item in enumerate(results, 1):
        item["rank"] = i

    return results


def get_score_tier(score: float) -> Dict[str, str]:
    """Map a total score to a display tier."""
    if score >= 120:
        return {"label": "Elite", "color": "#7c3aed", "icon": "fa-crown"}
    elif score >= 100:
        return {"label": "Expert", "color": "#059669", "icon": "fa-star"}
    elif score >= 80:
        return {"label": "Strong", "color": "#0a66c2", "icon": "fa-thumbs-up"}
    elif score >= 60:
        return {"label": "Moderate", "color": "#d97706", "icon": "fa-chart-line"}
    else:
        return {"label": "Beginner", "color": "#6b7280", "icon": "fa-seedling"}
