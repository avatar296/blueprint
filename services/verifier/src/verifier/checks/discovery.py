"""Semantic DOM discovery — careers + contact via element scoring.

Instead of regex-matching href paths, this module extracts every navigable
element (links, buttons) from the rendered DOM with their visible text,
ARIA labels, and structural context (nav/header/footer).  A scoring system
ranks each element for "careers-ness" or "contact-ness", and the highest-
scoring element above a threshold is followed.

Fallbacks:
- If no careers link is found via scoring, probe /careers and /jobs.
- If no contact info is found, navigate to the best contact/about link
  or probe /contact, /contact-us.
- If the domain is parked, attempt Facebook About page extraction.
"""

import asyncio
import base64
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import Page, Error as PlaywrightError, async_playwright
from playwright_stealth import Stealth

log = logging.getLogger("verifier.checks.discovery")

# ── ATS platform signatures ─────────────────────────────────────
_ATS_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("greenhouse", re.compile(r"boards\.greenhouse\.io/", re.IGNORECASE), "greenhouse.io"),
    ("greenhouse", re.compile(r"job-boards\.greenhouse\.io/", re.IGNORECASE), "greenhouse.io"),
    ("lever", re.compile(r"jobs\.lever\.co/", re.IGNORECASE), "lever.co"),
    ("workday", re.compile(r"\.wd\d+\.myworkdayjobs\.com", re.IGNORECASE), "myworkdayjobs.com"),
    ("workday", re.compile(r"myworkdayjobs\.com", re.IGNORECASE), "myworkdayjobs.com"),
    ("icims", re.compile(r"careers-.*\.icims\.com", re.IGNORECASE), "icims.com"),
    ("icims", re.compile(r"\.icims\.com/jobs", re.IGNORECASE), "icims.com"),
    ("taleo", re.compile(r"\.taleo\.net", re.IGNORECASE), "taleo.net"),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/", re.IGNORECASE), "ashbyhq.com"),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/", re.IGNORECASE), "smartrecruiters.com"),
    ("bamboohr", re.compile(r"\.bamboohr\.com/careers", re.IGNORECASE), "bamboohr.com"),
    ("paycom", re.compile(r"paycomonline\.net", re.IGNORECASE), "paycomonline.net"),
    ("jobvite", re.compile(r"jobs\.jobvite\.com", re.IGNORECASE), "jobvite.com"),
    ("adp", re.compile(r"workforcenow\.adp\.com", re.IGNORECASE), "adp.com"),
    ("ultipro", re.compile(r"recruiting\.ultipro\.com", re.IGNORECASE), "ultipro.com"),
    # SAP SuccessFactors
    ("successfactors", re.compile(r"\.successfactors\.com", re.IGNORECASE), "successfactors.com"),
    ("successfactors", re.compile(r"jobs\.sap\.com", re.IGNORECASE), "sap.com"),
    ("successfactors", re.compile(r"performancemanager\d*\.successfactors\.com", re.IGNORECASE), "successfactors.com"),
    # Eightfold
    ("eightfold", re.compile(r"\.eightfold\.ai", re.IGNORECASE), "eightfold.ai"),
    # Phenom
    ("phenom", re.compile(r"\.phenom\.com", re.IGNORECASE), "phenom.com"),
    ("phenom", re.compile(r"jobs\..*\.com/.*phenom", re.IGNORECASE), "phenom.com"),
    # Avature
    ("avature", re.compile(r"\.avature\.net", re.IGNORECASE), "avature.net"),
    # Brassring / Kenexa (IBM)
    ("brassring", re.compile(r"\.brassring\.com", re.IGNORECASE), "brassring.com"),
    # Cornerstone OnDemand
    ("cornerstone", re.compile(r"\.csod\.com", re.IGNORECASE), "csod.com"),
    # Ceridian / Dayforce
    ("dayforce", re.compile(r"\.dayforcehcm\.com", re.IGNORECASE), "dayforcehcm.com"),
    ("dayforce", re.compile(r"\.dayforce\.com", re.IGNORECASE), "dayforce.com"),
    # Rippling
    ("rippling", re.compile(r"ats\.rippling\.com", re.IGNORECASE), "rippling.com"),
    # JazzHR
    ("jazzhr", re.compile(r"\.applytojob\.com", re.IGNORECASE), "applytojob.com"),
    # Recruitee
    ("recruitee", re.compile(r"\.recruitee\.com", re.IGNORECASE), "recruitee.com"),
    # Personio
    ("personio", re.compile(r"\.jobs\.personio\.com", re.IGNORECASE), "personio.com"),
]

_ATS_CONTENT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"powered\s+by\s+greenhouse", re.IGNORECASE)),
    ("greenhouse", re.compile(r"id=['\"]grnhse_app['\"]", re.IGNORECASE)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board", re.IGNORECASE)),
    ("lever", re.compile(r"powered\s+by\s+lever", re.IGNORECASE)),
    ("lever", re.compile(r"lever-jobs-container", re.IGNORECASE)),
    ("workday", re.compile(r"powered\s+by\s+workday", re.IGNORECASE)),
    ("workday", re.compile(r"myworkdayjobs\.com", re.IGNORECASE)),
    ("icims", re.compile(r"powered\s+by\s+icims", re.IGNORECASE)),
    ("icims", re.compile(r"icims\.com/jobs", re.IGNORECASE)),
    ("bamboohr", re.compile(r"powered\s+by\s+bamboohr", re.IGNORECASE)),
    ("jobvite", re.compile(r"powered\s+by\s+jobvite", re.IGNORECASE)),
    ("smartrecruiters", re.compile(r"powered\s+by\s+smartrecruiters", re.IGNORECASE)),
    ("successfactors", re.compile(r"powered\s+by\s+sap\s+successfactors", re.IGNORECASE)),
    ("successfactors", re.compile(r"successfactors\.com", re.IGNORECASE)),
    ("eightfold", re.compile(r"eightfold\.ai", re.IGNORECASE)),
    ("phenom", re.compile(r"powered\s+by\s+phenom", re.IGNORECASE)),
    ("phenom", re.compile(r"phenom\.com", re.IGNORECASE)),
    ("avature", re.compile(r"avature\.net", re.IGNORECASE)),
]

# ── Email extraction ─────────────────────────────────────────────
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_JUNK_EMAIL_RE = re.compile(
    r"noreply@|no-reply@|donotreply@|do-not-reply@"
    r"|@example\.com|@sentry\.io|@wixpress\.com"
    r"|\.(png|jpg|jpeg|gif|svg|webp|ico)$",
    re.IGNORECASE,
)

# ── Phone extraction ─────────────────────────────────────────────
_PHONE_RE = re.compile(
    r"(\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?[2-9]\d{2}[-.\s]?\d{4}"
)

_NAV_TIMEOUT = 15_000  # ms — per-page navigation timeout
_COMPANY_TIMEOUT = 60  # seconds — total budget per company

# ── Careers text signals ─────────────────────────────────────────
_CAREERS_EXACT = {
    "careers", "career", "jobs", "open positions", "open roles",
    "job openings", "opportunities", "vacancies",
}
_CAREERS_PHRASES = [
    "join our team", "join the team", "work with us", "work for us",
    "we're hiring", "we are hiring", "life at", "come work",
    "career opportunities", "job opportunities", "current openings",
    "view openings", "see openings", "explore careers", "explore jobs",
]

# ── Contact text signals ─────────────────────────────────────────
_CONTACT_EXACT = {"contact", "contact us", "get in touch", "reach out"}
_CONTACT_PHRASES = [
    "about us", "about", "reach us", "connect with us",
    "talk to us", "speak with us", "get started",
]

# ── Exclusions ───────────────────────────────────────────────────
_SOCIAL_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "linkedin.com",
    "instagram.com", "youtube.com", "tiktok.com", "pinterest.com",
    "github.com",
}
_EXCLUDED_HREF_RE = re.compile(r"^(mailto:|tel:|#|javascript:)", re.IGNORECASE)
_EXCLUDED_TEXT_RE = re.compile(
    r"^(log\s*in|sign\s*in|sign\s*up|register|my\s*account|portal|dashboard|"
    r"employee\s*login|client\s*login|patient\s*portal)$",
    re.IGNORECASE,
)

# Known ATS domains — cross-domain links to these are acceptable
_ATS_DOMAINS = {d for _, _, d in _ATS_PATTERNS}

# Negative signals that disqualify a link from being a careers page
_CAREERS_NEGATIVE_RE = re.compile(
    r"store.locator|find.a.store|shop.now|promo|save.now|coupon|deal"
    r"|log.?in|sign.?in|my.?account|patient.portal"
    r"|who.we.are|investor.relations|annual.report"
    r"|store.finder|locate.a.store",
    re.IGNORECASE,
)


def _root_domain(url: str) -> str:
    """Extract registrable domain: 'https://www.jobs.target.com/page' → 'target.com'."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    # Handle co.uk, com.au style TLDs
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov"):
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host

# ── JS snippet to extract navigable elements from the DOM ────────
_EXTRACT_ELEMENTS_JS = """
() => {
    const results = [];
    const els = document.querySelectorAll('a[href], button');
    for (const el of els) {
        const href = el.getAttribute('href') || '';
        const text = (el.innerText || '').trim().substring(0, 200);
        const aria = (el.getAttribute('aria-label') || '').trim();
        const title = (el.getAttribute('title') || '').trim();
        const rect = el.getBoundingClientRect();
        const visible = rect.width > 0 && rect.height > 0;
        const inNav = !!el.closest('nav');
        const inHeader = !!el.closest('header');
        const inFooter = !!el.closest('footer');
        results.push({ href, text, aria, title, visible, inNav, inHeader, inFooter });
    }
    return results;
}
"""


def _clean_email(raw: str) -> str | None:
    email = raw.strip().lower()
    if _JUNK_EMAIL_RE.search(email):
        return None
    if _EMAIL_RE.fullmatch(email):
        return email
    return None


def _clean_phone(raw: str) -> str | None:
    phone = raw.strip()
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return None
    return phone


def _detect_ats_in_url(url: str) -> tuple[str | None, str | None]:
    """Check a single URL for ATS platform signatures."""
    for platform, url_re, _ in _ATS_PATTERNS:
        if url_re.search(url):
            return platform, url
    return None, None


def _detect_ats_in_hrefs(hrefs: list[str]) -> tuple[str | None, str | None]:
    """Scan a list of hrefs for ATS platform signatures."""
    for href in hrefs:
        for platform, url_re, domain in _ATS_PATTERNS:
            if url_re.search(href) or domain in href.lower():
                return platform, href
    return None, None


def _extract_contact_from_text(text: str) -> tuple[str | None, str | None]:
    """Extract first valid email and phone from visible text."""
    email: str | None = None
    phone: str | None = None

    for raw in _EMAIL_RE.findall(text):
        email = _clean_email(raw)
        if email:
            break

    for m in _PHONE_RE.finditer(text):
        phone = _clean_phone(m.group())
        if phone:
            break

    return email, phone


def _extract_jsonld_contact(jsonld_texts: list[str]) -> tuple[str | None, str | None]:
    """Extract telephone/email from JSON-LD Organization blocks."""
    for raw in jsonld_texts:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        items = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            items = data["@graph"]

        for item in items:
            if not isinstance(item, dict):
                continue
            t = item.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if not any(
                tp in ("Organization", "Corporation", "LocalBusiness",
                       "MedicalOrganization", "Hospital")
                for tp in types
            ):
                continue

            phone = item.get("telephone")
            email = item.get("email")
            clean_p = _clean_phone(phone) if phone else None
            clean_e = _clean_email(email) if email else None
            if clean_p or clean_e:
                return clean_e, clean_p

    return None, None


async def _extract_page_data(page: Page) -> dict:
    """Extract hrefs, mailto/tel links, JSON-LD, and visible text from current page."""
    hrefs = await page.eval_on_selector_all(
        "a[href]", "els => els.map(e => e.getAttribute('href'))"
    )

    mailto_vals = await page.eval_on_selector_all(
        'a[href^="mailto:"]',
        "els => els.map(e => e.getAttribute('href').replace(/^mailto:/i, '').split('?')[0])",
    )

    tel_vals = await page.eval_on_selector_all(
        'a[href^="tel:"]',
        "els => els.map(e => e.getAttribute('href').replace(/^tel:/i, ''))",
    )

    jsonld_texts = await page.eval_on_selector_all(
        'script[type="application/ld+json"]',
        "els => els.map(e => e.textContent)",
    )

    try:
        body_text = await page.inner_text("body", timeout=3000)
    except PlaywrightError:
        body_text = ""

    return {
        "hrefs": hrefs or [],
        "mailto": mailto_vals or [],
        "tel": tel_vals or [],
        "jsonld": jsonld_texts or [],
        "text": body_text[:20_000],
    }


async def _extract_navigable_elements(page: Page) -> list[dict]:
    """Run in-browser JS to collect every <a> and <button> with semantic context."""
    try:
        return await page.evaluate(_EXTRACT_ELEMENTS_JS)
    except PlaywrightError:
        log.debug("Failed to extract navigable elements", exc_info=True)
        return []


# ── Scoring functions ────────────────────────────────────────────

def _is_excluded(el: dict) -> bool:
    """Return True if the element should be skipped entirely."""
    href = el.get("href", "")
    text = el.get("text", "")

    if _EXCLUDED_HREF_RE.match(href):
        return True
    if _EXCLUDED_TEXT_RE.match(text):
        return True

    # Skip social media links
    try:
        domain = urlparse(href).netloc.lower()
        # Strip www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        if domain in _SOCIAL_DOMAINS:
            return True
    except Exception:
        pass

    return False


def _structural_modifier(el: dict) -> float:
    """Bonus multiplier for elements in nav/header/footer."""
    if el.get("inNav") or el.get("inHeader"):
        return 1.1
    if el.get("inFooter"):
        return 1.05
    return 1.0


def _visibility_modifier(el: dict) -> float:
    """Penalty for invisible elements."""
    return 1.0 if el.get("visible") else 0.3


def _score_for_careers(el: dict, *, base_domain: str = "") -> float:
    """Score an element for careers/jobs relevance (0.0 – 1.0).

    *base_domain*: registrable domain of the company homepage.  If provided,
    links pointing to a different domain (unless it's a known ATS) score 0.
    """
    if _is_excluded(el):
        return 0.0

    text = el.get("text", "").strip().lower()
    href = el.get("href", "").lower()
    aria = el.get("aria", "").strip().lower()
    title_attr = el.get("title", "").strip().lower()

    # ── Negative keyword exclusion ────────────────────────────
    # Text or href path matching store-locator / promo / login / etc. → reject
    if _CAREERS_NEGATIVE_RE.search(text):
        return 0.0
    if href:
        href_path = urlparse(href).path
        if _CAREERS_NEGATIVE_RE.search(href_path):
            return 0.0

    # ── Cross-domain penalty ──────────────────────────────────
    # If the link points off-site and isn't a known ATS, reject it.
    if base_domain and href:
        link_domain = _root_domain(href)
        if link_domain and link_domain != base_domain:
            # Allow known ATS domains
            if not any(ats in link_domain for ats in _ATS_DOMAINS):
                return 0.0

    score = 0.0

    # Tier 4: ATS domain in href (very strong signal)
    for _, url_re, _ in _ATS_PATTERNS:
        if url_re.search(href):
            score = max(score, 0.90)
            break

    # Tier 1: Exact text match
    if text in _CAREERS_EXACT:
        score = max(score, 0.95)

    # Tier 2: Phrase in text
    for phrase in _CAREERS_PHRASES:
        if phrase in text:
            score = max(score, 0.80)
            break

    # Tier 3: ARIA/title attribute
    for signal in (aria, title_attr):
        if signal:
            if signal in _CAREERS_EXACT:
                score = max(score, 0.70)
            else:
                for phrase in _CAREERS_PHRASES:
                    if phrase in signal:
                        score = max(score, 0.70)
                        break

    # Tier 5: href path fallback
    if score == 0.0 and href:
        path = urlparse(href).path.lower()
        career_paths = {"/careers", "/career", "/jobs", "/join-us",
                        "/work-with-us", "/hiring", "/openings", "/vacancies"}
        for cp in career_paths:
            if path == cp or path.startswith(cp + "/"):
                score = max(score, 0.50)
                break

    # Apply modifiers
    if score > 0:
        score *= _structural_modifier(el)
        score *= _visibility_modifier(el)
        score = min(score, 1.0)

    return score


def _score_for_contact(el: dict) -> float:
    """Score an element for contact/about relevance (0.0 – 1.0)."""
    if _is_excluded(el):
        return 0.0

    score = 0.0
    text = el.get("text", "").strip().lower()
    href = el.get("href", "").lower()
    aria = el.get("aria", "").strip().lower()
    title_attr = el.get("title", "").strip().lower()

    # Tier 1: Exact text match
    if text in _CONTACT_EXACT:
        score = max(score, 0.95)

    # Tier 2: Phrase in text
    for phrase in _CONTACT_PHRASES:
        if phrase in text:
            score = max(score, 0.80)
            break

    # Tier 3: ARIA/title attribute
    for signal in (aria, title_attr):
        if signal:
            if signal in _CONTACT_EXACT:
                score = max(score, 0.70)
            else:
                for phrase in _CONTACT_PHRASES:
                    if phrase in signal:
                        score = max(score, 0.70)
                        break

    # Tier 5: href path fallback
    if score == 0.0 and href:
        path = urlparse(href).path.lower()
        contact_paths = {"/contact-us", "/contact", "/about-us", "/about",
                         "/get-in-touch"}
        for cp in contact_paths:
            if path == cp or path.startswith(cp + "/"):
                score = max(score, 0.50)
                break

    # Apply modifiers
    if score > 0:
        score *= _structural_modifier(el)
        score *= _visibility_modifier(el)
        score = min(score, 1.0)

    return score


def _best_element(
    elements: list[dict],
    scorer,
    threshold: float = 0.4,
) -> dict | None:
    """Return the highest-scoring element above threshold, or None."""
    best = None
    best_score = 0.0
    for el in elements:
        s = scorer(el)
        if s >= threshold and s > best_score:
            best = el
            best_score = s
    return best


def _resolve_href(href: str, base_url: str) -> str | None:
    """Resolve an element's href to an absolute URL, or None if not navigable."""
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    if href.startswith("/") or not urlparse(href).scheme:
        return urljoin(base_url, href)
    return href


# ── LLM fallback ─────────────────────────────────────────────────

_MAX_LLM_CANDIDATES = 30

_LLM_SYSTEM_PROMPT = (
    "You pick the best navigation element from a webpage for a given goal. "
    "Reply with ONLY the element number (e.g. '7') or 'NONE' if no element matches. "
    "Do not explain."
)

_LLM_PICK_RE = re.compile(r"^\s*(\d+)\s*$")


def _prepare_elements_for_llm(elements: list[dict]) -> list[dict]:
    """Filter and number elements for LLM consumption."""
    candidates = []
    for i, el in enumerate(elements):
        if _is_excluded(el):
            continue
        if not el.get("visible"):
            continue
        text = el.get("text", "").strip()
        aria = el.get("aria", "").strip()
        if not text and not aria:
            continue
        href = el.get("href", "").strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        candidates.append({**el, "idx": i})

    if len(candidates) > _MAX_LLM_CANDIDATES:
        structural = [c for c in candidates
                      if c.get("inNav") or c.get("inHeader") or c.get("inFooter")]
        other = [c for c in candidates
                 if not (c.get("inNav") or c.get("inHeader") or c.get("inFooter"))]
        candidates = structural + other[:_MAX_LLM_CANDIDATES - len(structural)]
        candidates = candidates[:_MAX_LLM_CANDIDATES]

    return candidates


def _build_llm_prompt(candidates: list[dict], goal: str) -> str:
    """Build a compact prompt listing candidate elements."""
    if goal == "careers":
        instruction = (
            "Which element most likely leads to this company's careers or jobs page? "
            "Look for links about working at the company, open positions, hiring, "
            "team culture, or an applicant tracking system."
        )
    else:
        instruction = (
            "Which element most likely leads to this company's contact page? "
            "Look for links about contacting the company, getting in touch, "
            "reaching the team, or finding email/phone info."
        )

    lines = [instruction, "", "Elements:"]
    for i, c in enumerate(candidates):
        text = c.get("text", "")[:80]
        href = c.get("href", "")[:120]
        aria = c.get("aria", "")[:40]
        location = []
        if c.get("inNav"):
            location.append("nav")
        if c.get("inHeader"):
            location.append("header")
        if c.get("inFooter"):
            location.append("footer")
        loc_str = ",".join(location) if location else "body"

        line = f"{i} | {text}"
        if aria and aria.lower() != text.lower():
            line += f" [aria: {aria}]"
        line += f" | {href} | {loc_str}"
        lines.append(line)

    return "\n".join(lines)


_LLM_CAREERS_SANITY_RE = re.compile(
    r"career|careers|jobs?|hiring|openings|positions|vacancies|applicant"
    r"|work.with.us|join.our.team|join.the.team|we.re.hiring|talent"
    r"|employment|recruit|human.resources",
    re.IGNORECASE,
)


def _validate_llm_pick(el: dict, goal: str) -> bool:
    """Sanity-check an LLM-picked element.

    Returns True if the element has at least some relevance to the goal.
    This catches cases where the vision model picks random UI elements.
    """
    if goal != "careers":
        return True  # only gating careers picks for now

    text = el.get("text", "").strip().lower()
    href = el.get("href", "").lower()
    aria = el.get("aria", "").strip().lower()

    for signal in (text, href, aria):
        if _LLM_CAREERS_SANITY_RE.search(signal):
            return True

    # Also check href path
    try:
        path = urlparse(href).path.lower()
        if any(kw in path for kw in ("/career", "/jobs", "/hiring", "/openings", "/talent")):
            return True
    except Exception:
        pass

    return False


def _parse_llm_response(data: dict, candidates: list[dict]) -> dict | None:
    """Extract the chosen element from Ollama's response."""
    try:
        content = data["message"]["content"].strip()
    except (KeyError, TypeError):
        log.debug("Unexpected Ollama response structure: %s", data)
        return None

    if content.upper() == "NONE":
        return None

    m = _LLM_PICK_RE.match(content)
    if not m:
        numbers = re.findall(r"\b(\d+)\b", content)
        if not numbers:
            log.debug("LLM returned unparseable response: %r", content)
            return None
        idx = int(numbers[0])
    else:
        idx = int(m.group(1))

    if 0 <= idx < len(candidates):
        log.debug(
            "LLM picked element %d: text=%r href=%r",
            idx, candidates[idx].get("text", ""), candidates[idx].get("href", ""),
        )
        return candidates[idx]

    log.debug("LLM returned out-of-range index %d (max %d)", idx, len(candidates) - 1)
    return None


async def _llm_pick_element(
    elements: list[dict],
    goal: str,
    *,
    ollama_base_url: str,
    model: str = "llama3",
    timeout: float = 10.0,
) -> dict | None:
    """Ask Ollama to pick the best element for a goal. Returns element or None."""
    if not elements:
        return None

    candidates = _prepare_elements_for_llm(elements)
    if not candidates:
        return None

    prompt = _build_llm_prompt(candidates, goal)
    url = f"{ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 50},
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=3.0),
        ) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        log.debug("Ollama unreachable at %s — skipping LLM fallback", ollama_base_url)
        return None
    except httpx.TimeoutException:
        log.debug("Ollama timed out after %.1fs for %s pick", timeout, goal)
        return None
    except (httpx.HTTPError, Exception):
        log.debug("Ollama call failed for %s pick", goal, exc_info=True)
        return None

    return _parse_llm_response(data, candidates)


# ── Vision LLM fallback ──────────────────────────────────────────

_ANNOTATE_ELEMENTS_JS = """
(indices) => {
    const els = document.querySelectorAll('a[href], button');
    for (let i = 0; i < indices.length; i++) {
        const elIdx = indices[i];
        if (elIdx >= els.length) continue;
        const el = els[elIdx];
        const rect = el.getBoundingClientRect();
        const badge = document.createElement('div');
        badge.className = '__bp_vision_badge';
        badge.textContent = String(i);
        badge.style.cssText = (
            'position:fixed;z-index:999999;background:red;color:white;'
            + 'font-size:14px;font-weight:bold;padding:2px 6px;border-radius:50%;'
            + 'pointer-events:none;line-height:1.2;min-width:20px;text-align:center;'
            + 'left:' + rect.left + 'px;top:' + rect.top + 'px;'
        );
        document.body.appendChild(badge);
    }
}
"""

_REMOVE_ANNOTATIONS_JS = """
() => {
    for (const el of document.querySelectorAll('.__bp_vision_badge')) {
        el.remove();
    }
}
"""

_VISION_SYSTEM_PROMPT = (
    "You are analyzing a screenshot of a webpage. Red numbered badges have been "
    "overlaid on navigable elements (links and buttons). "
    "Reply with ONLY the badge number (e.g. '7') of the best matching element, "
    "or 'NONE' if no element matches the goal. Do not explain."
)


def _build_vision_prompt(goal: str) -> str:
    """Build a user prompt for the vision model."""
    if goal == "careers":
        return (
            "Which numbered badge marks the link most likely to lead to this "
            "company's careers or jobs page? Look for navigation to open positions, "
            "hiring, or applicant tracking systems."
        )
    return (
        "Which numbered badge marks the link most likely to lead to this "
        "company's contact page? Look for navigation to contact info, "
        "email, phone, or getting in touch."
    )


async def _vision_pick_element(
    page: Page,
    elements: list[dict],
    goal: str,
    *,
    ollama_base_url: str,
    model: str = "minicpm-v",
    timeout: float = 15.0,
) -> dict | None:
    """Screenshot page with numbered badges and ask a vision model to pick."""
    if not elements:
        return None

    candidates = _prepare_elements_for_llm(elements)
    if not candidates:
        return None

    indices = [c["idx"] for c in candidates]

    try:
        await page.evaluate(_ANNOTATE_ELEMENTS_JS, indices)
    except PlaywrightError:
        log.debug("Failed to inject vision badges", exc_info=True)
        return None

    try:
        screenshot_bytes = await page.screenshot()
    except PlaywrightError:
        log.debug("Failed to take screenshot for vision LLM", exc_info=True)
        return None
    finally:
        try:
            await page.evaluate(_REMOVE_ANNOTATIONS_JS)
        except PlaywrightError:
            pass

    b64_image = base64.b64encode(screenshot_bytes).decode("ascii")

    url = f"{ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_vision_prompt(goal),
                "images": [b64_image],
            },
        ],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 50},
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=3.0),
        ) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        log.debug("Ollama unreachable at %s — skipping vision fallback", ollama_base_url)
        return None
    except httpx.TimeoutException:
        log.debug("Vision LLM timed out after %.1fs for %s pick", timeout, goal)
        return None
    except (httpx.HTTPError, Exception):
        log.debug("Vision LLM call failed for %s pick", goal, exc_info=True)
        return None

    return _parse_llm_response(data, candidates)


# ── ATS detection on a careers page ──────────────────────────────

_LOGIN_SIGNAL_RE = re.compile(
    r"(log\s*in|sign\s*in|forgot.password|reset.password|username.and.password)",
    re.IGNORECASE,
)
_CAREERS_PAGE_RE = re.compile(
    r"(careers|jobs|open.positions|openings|hiring|join.our.team|work.with.us)",
    re.IGNORECASE,
)


async def _navigate_and_detect_ats(
    page: Page, careers_url: str, *, base_domain: str = ""
) -> dict:
    """Navigate to a careers URL and detect ATS platform via 4 layers."""
    result = {"careers_url": careers_url, "ats_platform": None, "ats_url": None}

    try:
        resp = await page.goto(
            careers_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT
        )
        if not resp or resp.status >= 400:
            return result
    except PlaywrightError:
        log.debug("Failed to navigate to careers URL %s", careers_url)
        return result

    final_url = page.url
    result["careers_url"] = final_url

    # ── Post-navigation validation ────────────────────────────
    # If the final URL is off-domain (after redirects) and not a known ATS, discard.
    if base_domain:
        final_domain = _root_domain(final_url)
        if final_domain and final_domain != base_domain:
            if not any(ats in final_domain for ats in _ATS_DOMAINS):
                log.debug(
                    "Careers link redirected off-domain: %s → %s — discarding",
                    base_domain, final_domain,
                )
                result["careers_url"] = None
                return result

    # Check for login pages masquerading as careers
    try:
        snippet = await page.inner_text("body", timeout=3000)
        snippet = snippet[:5000]
    except PlaywrightError:
        snippet = ""

    if _LOGIN_SIGNAL_RE.search(snippet) and not _CAREERS_PAGE_RE.search(snippet):
        log.debug("Careers link landed on login page: %s — discarding", final_url)
        result["careers_url"] = None
        return result

    # Layer 1: Final URL domain after redirects
    platform, ats_url = _detect_ats_in_url(final_url)
    if platform:
        result["ats_platform"] = platform
        result["ats_url"] = ats_url
        return result

    # Layer 2: hrefs on the careers page
    page_data = await _extract_page_data(page)
    platform, ats_url = _detect_ats_in_hrefs(page_data["hrefs"])
    if platform:
        result["ats_platform"] = platform
        result["ats_url"] = ats_url
        return result

    # Layer 3: Page content patterns ("Powered by ...")
    text = page_data["text"]
    for platform_name, pattern in _ATS_CONTENT_PATTERNS:
        if pattern.search(text):
            result["ats_platform"] = platform_name
            return result

    # Layer 4: iframe src attributes (including dynamically injected)
    try:
        iframe_srcs = await page.eval_on_selector_all(
            "iframe[src]", "els => els.map(e => e.src || e.getAttribute('src'))"
        )
        for src in (iframe_srcs or []):
            platform, ats_url = _detect_ats_in_url(src)
            if platform:
                result["ats_platform"] = platform
                result["ats_url"] = ats_url
                return result
    except PlaywrightError:
        pass

    # Layer 5: script src attributes (Greenhouse embed, Lever widget, Phenom SDK, etc.)
    try:
        script_srcs = await page.eval_on_selector_all(
            "script[src]", "els => els.map(e => e.src || e.getAttribute('src'))"
        )
        for src in (script_srcs or []):
            platform, ats_url = _detect_ats_in_url(src)
            if platform:
                result["ats_platform"] = platform
                result["ats_url"] = ats_url
                return result
    except PlaywrightError:
        pass

    # Layer 6: full page HTML (catches data attributes, inline config, hidden markers)
    try:
        html = await page.content()
        html_snippet = html[:50_000]
        for platform_name, pattern in _ATS_CONTENT_PATTERNS:
            if pattern.search(html_snippet):
                result["ats_platform"] = platform_name
                return result
    except PlaywrightError:
        pass

    return result


# ── Facebook fallback ────────────────────────────────────────────

async def _facebook_extract_contact(
    page: Page,
    company_name: str,
    city: str | None,
    state: str | None,
) -> dict:
    """For parked domains: search DDG for Facebook page, navigate to /about, extract contact."""
    from verifier.checks.search import search_facebook

    contact = {"contact_email": None, "contact_phone": None, "contact_page_url": None}

    try:
        fb_result = await search_facebook(company_name, city, state)
    except Exception:
        log.debug("Facebook search failed for %s", company_name, exc_info=True)
        return contact

    fb_url = fb_result.get("facebook_url")
    if not fb_url:
        return contact

    about_url = fb_url.rstrip("/") + "/about"
    try:
        resp = await page.goto(
            about_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT
        )
        if not resp or resp.status >= 400:
            return contact
    except PlaywrightError:
        log.debug("Failed to navigate to Facebook About %s", about_url)
        return contact

    # Check for login wall — if we see "log in" prompt, bail
    try:
        body = await page.inner_text("body", timeout=3000)
    except PlaywrightError:
        return contact

    if "log in" in body.lower()[:500] and len(body) < 2000:
        log.debug("Facebook login wall detected for %s", about_url)
        return contact

    # Extract from the about page
    page_data = await _extract_page_data(page)

    for raw in page_data["mailto"]:
        e = _clean_email(raw)
        if e:
            contact["contact_email"] = e
            contact["contact_page_url"] = about_url
            break

    for raw in page_data["tel"]:
        p = _clean_phone(raw)
        if p:
            contact["contact_phone"] = p
            if not contact["contact_page_url"]:
                contact["contact_page_url"] = about_url
            break

    if not contact["contact_email"]:
        email, phone = _extract_contact_from_text(page_data["text"])
        if email:
            contact["contact_email"] = email
            contact["contact_page_url"] = about_url
        if phone and not contact["contact_phone"]:
            contact["contact_phone"] = phone
            if not contact["contact_page_url"]:
                contact["contact_page_url"] = about_url

    return contact


# ── Main discovery flow ──────────────────────────────────────────

async def _discover_one(
    page: Page,
    url: str,
    *,
    is_parked: bool = False,
    company_name: str | None = None,
    city: str | None = None,
    state: str | None = None,
    ollama_base_url: str | None = None,
    ollama_model: str = "llama3",
    ollama_timeout: float = 10.0,
    ollama_vision_model: str | None = None,
    ollama_vision_timeout: float = 15.0,
) -> dict:
    """Discover careers + contact info for one company URL."""
    careers: dict = {"careers_url": None, "ats_platform": None, "ats_url": None}
    contact: dict = {"contact_email": None, "contact_phone": None, "contact_page_url": None}

    if not url and not is_parked:
        return {"careers": careers, "contact": contact}

    # ── Parked domain: Facebook fallback only ─────────────────
    if is_parked:
        if company_name:
            fb_contact = await _facebook_extract_contact(
                page, company_name, city, state,
            )
            contact.update(fb_contact)
        return {"careers": careers, "contact": contact}

    # ── Step 1: Navigate to homepage ─────────────────────────
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
        if not resp or resp.status >= 400:
            return {"careers": careers, "contact": contact}
    except PlaywrightError as exc:
        log.debug("Navigation failed for %s: %s", url, exc)
        return {"careers": careers, "contact": contact}

    base_url = page.url

    # ── Step 1b: Extract all data from homepage ──────────────
    elements = await _extract_navigable_elements(page)
    data = await _extract_page_data(page)

    # ── Step 2: Score elements for careers + contact ─────────
    base_domain = _root_domain(base_url)
    best_careers_el = _best_element(
        elements, lambda el: _score_for_careers(el, base_domain=base_domain)
    )
    best_contact_el = _best_element(elements, _score_for_contact)

    # ── Step 2b: LLM fallback when scorer found nothing ──────
    if not best_careers_el and ollama_base_url and elements:
        llm_el = await _llm_pick_element(
            elements, "careers",
            ollama_base_url=ollama_base_url,
            model=ollama_model,
            timeout=ollama_timeout,
        )
        if llm_el:
            if _validate_llm_pick(llm_el, "careers"):
                best_careers_el = llm_el
                log.info("LLM picked careers element: text=%r href=%r",
                         llm_el.get("text", ""), llm_el.get("href", ""))
            else:
                log.debug("LLM pick rejected (no careers signal): text=%r href=%r",
                          llm_el.get("text", ""), llm_el.get("href", ""))

    if not best_contact_el and ollama_base_url and elements:
        llm_el = await _llm_pick_element(
            elements, "contact",
            ollama_base_url=ollama_base_url,
            model=ollama_model,
            timeout=ollama_timeout,
        )
        if llm_el:
            best_contact_el = llm_el
            log.info("LLM picked contact element: text=%r href=%r",
                     llm_el.get("text", ""), llm_el.get("href", ""))

    # ── Step 2c: Vision LLM fallback ─────────────────────────
    if not best_careers_el and ollama_base_url and ollama_vision_model and elements:
        vision_el = await _vision_pick_element(
            page, elements, "careers",
            ollama_base_url=ollama_base_url,
            model=ollama_vision_model,
            timeout=ollama_vision_timeout,
        )
        if vision_el:
            if _validate_llm_pick(vision_el, "careers"):
                best_careers_el = vision_el
                log.info("Vision LLM picked careers element: text=%r href=%r",
                         vision_el.get("text", ""), vision_el.get("href", ""))
            else:
                log.debug("Vision LLM pick rejected (no careers signal): text=%r href=%r",
                          vision_el.get("text", ""), vision_el.get("href", ""))

    if not best_contact_el and ollama_base_url and ollama_vision_model and elements:
        vision_el = await _vision_pick_element(
            page, elements, "contact",
            ollama_base_url=ollama_base_url,
            model=ollama_vision_model,
            timeout=ollama_vision_timeout,
        )
        if vision_el:
            best_contact_el = vision_el
            log.info("Vision LLM picked contact element: text=%r href=%r",
                     vision_el.get("text", ""), vision_el.get("href", ""))

    # Also check homepage URL itself for ATS (e.g. site redirected to ATS)
    platform, ats_url = _detect_ats_in_url(base_url)
    if platform:
        careers["ats_platform"] = platform
        careers["ats_url"] = ats_url

    # Check homepage hrefs for ATS links
    if not careers["ats_platform"]:
        platform, ats_url = _detect_ats_in_hrefs(data["hrefs"])
        if platform:
            careers["ats_platform"] = platform
            careers["ats_url"] = ats_url

    # ── Step 3: Extract contact from homepage ────────────────
    for raw in data["mailto"]:
        e = _clean_email(raw)
        if e:
            contact["contact_email"] = e
            break

    for raw in data["tel"]:
        p = _clean_phone(raw)
        if p:
            contact["contact_phone"] = p
            break

    if not contact["contact_email"] or not contact["contact_phone"]:
        jld_email, jld_phone = _extract_jsonld_contact(data["jsonld"])
        if jld_email and not contact["contact_email"]:
            contact["contact_email"] = jld_email
        if jld_phone and not contact["contact_phone"]:
            contact["contact_phone"] = jld_phone

    if not contact["contact_email"] or not contact["contact_phone"]:
        text_email, text_phone = _extract_contact_from_text(data["text"])
        if text_email and not contact["contact_email"]:
            contact["contact_email"] = text_email
        if text_phone and not contact["contact_phone"]:
            contact["contact_phone"] = text_phone

    # ── Step 4: Navigate to careers page ─────────────────────
    careers_href = None
    if best_careers_el:
        careers_href = _resolve_href(best_careers_el.get("href", ""), base_url)

    if careers_href:
        ats_result = await _navigate_and_detect_ats(
            page, careers_href, base_domain=base_domain
        )
        careers["careers_url"] = ats_result["careers_url"]
        if ats_result["ats_platform"]:
            careers["ats_platform"] = ats_result["ats_platform"]
            careers["ats_url"] = ats_result["ats_url"]
    elif not careers["ats_platform"]:
        # Fallback: probe path and subdomain patterns
        # 1) Path probes on same domain
        probe_urls = [urljoin(base_url, p) for p in ("/careers", "/jobs")]

        # 2) Subdomain probes: careers.{domain}, jobs.{domain}
        if base_domain:
            for sub in ("careers", "jobs"):
                probe_urls.append(f"https://{sub}.{base_domain}/")

        for probe_url in probe_urls:
            try:
                probe_resp = await page.goto(
                    probe_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT
                )
                if not probe_resp or probe_resp.status >= 400:
                    continue

                final_probe_url = page.url

                # Validate: reject if redirected off-domain (not ATS)
                if base_domain:
                    probe_domain = _root_domain(final_probe_url)
                    if probe_domain and probe_domain != base_domain:
                        if not any(ats in probe_domain for ats in _ATS_DOMAINS):
                            log.debug("Probe %s redirected off-domain → %s", probe_url, probe_domain)
                            continue

                # Validate: check page content for careers signals
                try:
                    probe_title = await page.title()
                    probe_snippet = await page.inner_text("body", timeout=3000)
                    probe_snippet = probe_snippet[:5000]
                except PlaywrightError:
                    probe_title = ""
                    probe_snippet = ""

                probe_text = f"{probe_title} {probe_snippet}"

                # Reject login pages without careers signals
                if _LOGIN_SIGNAL_RE.search(probe_text) and not _CAREERS_PAGE_RE.search(probe_text):
                    log.debug("Probe %s landed on login page — skipping", probe_url)
                    continue

                # Reject if no careers signal at all in title+body
                if not _CAREERS_PAGE_RE.search(probe_text):
                    if _CAREERS_NEGATIVE_RE.search(probe_text):
                        log.debug("Probe %s matched negative pattern — skipping", probe_url)
                        continue

                ats_result = {"careers_url": final_probe_url, "ats_platform": None, "ats_url": None}
                p, a = _detect_ats_in_url(final_probe_url)
                if p:
                    ats_result["ats_platform"] = p
                    ats_result["ats_url"] = a
                else:
                    # Check page content/hrefs for ATS on the probed page
                    ats_result.update(await _navigate_and_detect_ats(
                        page, final_probe_url, base_domain=base_domain
                    ))
                careers["careers_url"] = ats_result["careers_url"] or final_probe_url
                if ats_result["ats_platform"]:
                    careers["ats_platform"] = ats_result["ats_platform"]
                    careers["ats_url"] = ats_result["ats_url"]
                break
            except PlaywrightError:
                continue

    # ── Step 5: Navigate to contact/about page if no email ───
    if not contact["contact_email"]:
        contact_href = None
        if best_contact_el:
            contact_href = _resolve_href(best_contact_el.get("href", ""), base_url)

        probe_urls: list[str] = []
        if contact_href:
            probe_urls.append(contact_href)
        probe_urls.extend([
            urljoin(base_url, "/contact"),
            urljoin(base_url, "/contact-us"),
        ])

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_probes: list[str] = []
        for u in probe_urls:
            if u not in seen:
                seen.add(u)
                unique_probes.append(u)

        for probe_url in unique_probes:
            try:
                probe_resp = await page.goto(
                    probe_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT
                )
                if not probe_resp or probe_resp.status >= 400:
                    continue

                cdata = await _extract_page_data(page)

                for raw in cdata["mailto"]:
                    e = _clean_email(raw)
                    if e:
                        contact["contact_email"] = e
                        contact["contact_page_url"] = page.url
                        break

                for raw in cdata["tel"]:
                    p = _clean_phone(raw)
                    if p:
                        if not contact["contact_phone"]:
                            contact["contact_phone"] = p
                        if not contact["contact_page_url"]:
                            contact["contact_page_url"] = page.url
                        break

                if not contact["contact_email"]:
                    ce, cp = _extract_contact_from_text(cdata["text"])
                    if ce:
                        contact["contact_email"] = ce
                        contact["contact_page_url"] = page.url
                    if cp and not contact["contact_phone"]:
                        contact["contact_phone"] = cp
                        if not contact["contact_page_url"]:
                            contact["contact_page_url"] = page.url

                if contact["contact_email"]:
                    break
            except PlaywrightError:
                continue

    return {"careers": careers, "contact": contact}


_stealth = Stealth()


async def discover_one_url(url: str) -> dict:
    """Convenience: discover careers+contact for a single URL (launches its own browser)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        await _stealth.apply_stealth_async(context)
        page = await context.new_page()
        try:
            return await _discover_one(page, url)
        finally:
            await page.close()
            await context.close()
            await browser.close()


async def discover_batch(
    companies: list[dict],
    *,
    concurrency: int = 5,
    website_results: dict | None = None,
    ollama_base_url: str | None = None,
    ollama_model: str = "llama3",
    ollama_timeout: float = 10.0,
    ollama_vision_model: str | None = None,
    ollama_vision_timeout: float = 15.0,
    on_result=None,
) -> dict:
    """Discover careers + contact for a batch of companies using Playwright.

    Routes each company based on website_results:
    - website_reachable=True → normal semantic discovery flow
    - website_is_parked=True → Facebook fallback
    - Neither (or no website_results) → normal flow if URL exists

    Args:
        companies: list of dicts with 'id', 'website', 'name', 'city', 'state'.
        concurrency: max concurrent browser tabs.
        website_results: dict mapping company_id -> website check results.

    Returns dict mapping company_id -> {"careers": {...}, "contact": {...}}.
    """
    if not companies:
        return {}

    sem = asyncio.Semaphore(concurrency)
    results: dict = {}
    wr = website_results or {}

    # Count eligible companies for progress tracking
    eligible = []
    for c in companies:
        cid = c["id"]
        ws = wr.get(cid, {})
        is_reachable = ws.get("website_reachable", False)
        is_parked = ws.get("website_is_parked", False)
        if wr and not is_reachable and not is_parked:
            continue
        if not c.get("website") and not is_parked:
            continue
        eligible.append(c)
    skipped = len(companies) - len(eligible)
    if skipped:
        log.info("Discovery: %d eligible, %d skipped (unreachable/no URL)", len(eligible), skipped)

    done_count = 0
    total = len(eligible)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        await _stealth.apply_stealth_async(context)

        async def _run(company: dict):
            nonlocal done_count
            cid = company["id"]
            url = company.get("website")
            name = company.get("name")
            city = company.get("city")
            state = company.get("state")

            ws = wr.get(cid, {})
            is_parked = ws.get("website_is_parked", False)

            async with sem:
                page = await context.new_page()
                t_start = asyncio.get_event_loop().time()
                try:
                    result = await asyncio.wait_for(
                        _discover_one(
                            page,
                            url or "",
                            is_parked=is_parked,
                            company_name=name,
                            city=city,
                            state=state,
                            ollama_base_url=ollama_base_url,
                            ollama_model=ollama_model,
                            ollama_timeout=ollama_timeout,
                            ollama_vision_model=ollama_vision_model,
                            ollama_vision_timeout=ollama_vision_timeout,
                        ),
                        timeout=_COMPANY_TIMEOUT,
                    )
                    results[cid] = result
                    if on_result:
                        on_result(cid, result)

                    # Per-company result summary with timing
                    elapsed = asyncio.get_event_loop().time() - t_start
                    c = result.get("careers", {})
                    ct = result.get("contact", {})
                    parts = []
                    if c.get("careers_url"):
                        parts.append("careers")
                    if c.get("ats_platform"):
                        parts.append(f"ats={c['ats_platform']}")
                    if ct.get("contact_email"):
                        parts.append("email")
                    if ct.get("contact_phone"):
                        parts.append("phone")
                    found = ", ".join(parts) if parts else "none"
                    log.info("[%d/%d] %s — %s (%.1fs)", done_count + 1, total, name, found, elapsed)

                except asyncio.TimeoutError:
                    log.warning(
                        "[%d/%d] %s — TIMEOUT after %ds (%s)",
                        done_count + 1, total, name, _COMPANY_TIMEOUT, url,
                    )
                except Exception:
                    log.warning(
                        "[%d/%d] %s — ERROR (%s)",
                        done_count + 1, total, name, url,
                        exc_info=True,
                    )
                finally:
                    done_count += 1
                    await page.close()

        tasks = [asyncio.create_task(_run(c)) for c in eligible]
        await asyncio.gather(*tasks, return_exceptions=True)

        await context.close()
        await browser.close()

    found_careers = sum(1 for r in results.values() if r["careers"].get("careers_url"))
    found_ats = sum(1 for r in results.values() if r["careers"].get("ats_platform"))
    found_email = sum(1 for r in results.values() if r["contact"].get("contact_email"))
    found_phone = sum(1 for r in results.values() if r["contact"].get("contact_phone"))

    log.info(
        "Discovery batch: %d checked — %d careers, %d ATS, %d email, %d phone",
        len(results), found_careers, found_ats, found_email, found_phone,
    )
    return results
