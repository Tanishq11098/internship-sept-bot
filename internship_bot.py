#!/usr/bin/env python3
"""
internship_bot.py - daily job/internship bot.

PHASE 1 (foundation): constants, IST time, parse_date, URL normalization,
fingerprinting, noise filter, domain matching, credential rule, experience
rule, role-type classification, deadline extraction, Tier-1 matching, scoring.

Scrapers, Google Sheets, Excel and email arrive in later phases.
"""

import hashlib
import logging
import math
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# =============================================================================
# CONSTANTS (every threshold and list lives here)
# =============================================================================

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def _env_flag(name, default):
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "n")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


# --- behaviour flags ---------------------------------------------------------
STRICT_LOCATION = _env_flag("STRICT_LOCATION", True)  # only Delhi NCR or remote

# --- limits / thresholds (several are used in later phases) ------------------
EXCEL_WINDOW_DAYS = 50
EMAIL_MAX_PER_SECTION = 25
MAX_DETAIL_FETCH = 40            # scraped listings that get a detail-page fetch
MAX_API_LISTINGS = 150           # API/Apify listings processed per run
TRACKER_MIN_SCORE = 60
TRACKER_MAX_PER_RUN = 10
API_QUERIES_PER_RUN = _env_int("API_QUERIES_PER_RUN", 4)
APIFY_MAX_ITEMS = _env_int("APIFY_MAX_ITEMS", 100)
REQUEST_TIMEOUT = 20
RETRY_PAUSE_SECONDS = 3

INTERN_MAX_YEARS_REJECT = 3      # internship requiring >= 3 years is rejected
OTHER_MAX_YEARS_REJECT = 2       # non-internship requiring >= 2 years is rejected
FULLTIME_FRESHER_MAX_YEARS = 1   # full-time passes only if fresher or <= 1 year
DEADLINE_SOON_DAYS = 14
DEADLINE_ROLLOVER_DAYS = 180     # year-less dates that already passed may roll to next year
DOMAIN_TEXT_CHARS = 800          # description chars used when title has no domain
ROLE_TEXT_HEAD_CHARS = 400       # description head used to spot "internship"

# --- scoring (0-100) ---------------------------------------------------------
SCORE_TIER1 = 30
ROLE_POINTS = {
    "PPO Internship": 20,
    "Graduate Program": 18,
    "Full-time": 14,
    "Internship": 12,
}
SCORE_LOC_NCR = 10
SCORE_LOC_REMOTE = 8
SCORE_ENTRY_SIGNAL = 6
SCORE_DEADLINE_SOON = 4
SCORE_CAP = 100

INTERNSHIP_TYPES = ("Internship", "PPO Internship")

# Seed constants for secret masking in logs
SECRET_ENV_NAMES = (
    "PASSWORD", "GOOGLE_SERVICE_ACCOUNT_JSON", "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
    "RAPIDAPI_KEY", "JOOBLE_KEY", "SERPAPI_KEY", "APIFY_TOKEN",
)

# Hosts whose links carry per-session query strings: strip ALL query params
STRIP_ALL_QUERY_HOSTS = ("adzuna.", "jooble.org")
TRACKING_PARAMS = {
    "ref", "ref_src", "ref_url", "src", "fbclid", "gclid", "msclkid", "dclid",
    "yclid", "igshid", "mc_cid", "mc_eid", "trk", "_ga", "gclsrc", "li_fat_id",
}
TRACKING_PREFIXES = ("utm_",)

# --- search phrases (rotated by date in Phase 2) -----------------------------
SEARCH_TOPICS = [
    "finance", "investment banking", "equity research", "venture capital",
    "private equity", "strategy", "consulting", "founders office",
    "chief of staff", "business analyst",
]
SEARCH_PHRASES = (
    [f"{t} {s}" for t in SEARCH_TOPICS for s in ("intern", "fresher")]
    + [
        "financial analyst fresher", "investment analyst fresher",
        "management trainee", "management trainee fresher",
        "graduate trainee", "graduate trainee fresher",
        "graduate program", "graduate program fresher",
    ]
)

# --- noise filter (title) ----------------------------------------------------
NOISE_TERMS = [
    r"software", r"developers?", r"devops", r"data\s+scientists?", r"sales",
    r"marketing", r"social\s+media", r"influencers?", r"seo", r"copywrit\w*",
    r"brand(?:s|ing)?", r"recruiters?", r"hr", r"tele[\s-]?callers?", r"bpo",
    r"customer", r"graphic", r"content", r"business\s+development",
    r"bde", r"bd", r"bdm", r"logistics", r"senior", r"sr\.?", r"managers?",
    r"vp", r"vice\s+president", r"director", r"head\s+of", r"lead", r"principal",
    r"avp",
]
# "chief" is noise EXCEPT "chief of staff"
NOISE_RE = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(NOISE_TERMS) + r"|chief(?!\s+of\s+staff))(?![a-z0-9])",
    re.I,
)


def _w(pattern):
    """Wrap a pattern in alnum lookarounds (works for names ending in symbols)."""
    return r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])"


# --- domains (ordered, first match wins) --------------------------------------
_APOS = r"[’'`]"
DOMAIN_RULES = [
    ("VC/PE", 30,
     r"venture\s+capital|venture\s+(?:analyst|associate|investing)|vc|private\s+equity|"
     r"growth\s+equity|pe\s+(?:fund|analyst|associate)|angel\s+invest\w*"),
    ("Investment Banking", 30,
     r"investment\s+bank\w*|ibd|m\s*&\s*a|mergers?\s*(?:&|and)\s*acquisitions?|"
     r"capital\s+markets|ecm|dcm"),
    ("Equity Research", 27,
     r"equity\s+research|equity\s+analyst|sell[\s-]side|buy[\s-]side|"
     r"securities\s+research|stock\s+research|equity\s+markets?"),
    ("Portfolio/Asset Mgmt", 25,
     r"portfolio\s+(?:management|analyst|manager|strategy)|asset\s+management|"
     r"wealth\s+management|fund\s+management|investment\s+management|mutual\s+funds?|amc"),
    ("Founder's Office/CoS", 27,
     rf"founders?(?:{_APOS}s?)?\s*office|ceo(?:{_APOS}?s)?\s*office|"
     r"office\s+of\s+(?:the\s+)?(?:ceo|founders?)|chief\s+of\s+staff|special\s+projects?"),
    ("Strategy & Operations", 22,
     r"strateg(?:y|ic)\s*(?:&|and|/)\s*op(?:s|erations?)|strategy\s+operations|"
     r"business\s+operations|bizops|program(?:me)?\s+management"),
    ("Consulting/Strategy", 25,
     r"consult(?:ing|ant|ants|ancy)|management\s+consult\w*|strategy|"
     r"strategic\s+(?:analyst|associate|planning|initiatives?|projects?)|advisory"),
    ("Corp Dev/IR", 22,
     r"corporate\s+development|corp\.?\s*dev(?:elopment)?|"
     r"investor\s+(?:relations|communications)"),
    ("Research & Policy", 18,
     r"research\s+(?:analyst|associate|intern|assistant|fellow)|public\s+policy|policy|"
     r"economic\w*\s+research|economics?|macro\w*|think[\s-]tank|market\s+research"),
    ("Finance (General)", 15,
     r"financ(?:e|es|ial)|banking|investments?|treasury|wealth|credit\s+analyst"),
]
DOMAIN_RULES = [(n, p, re.compile(_w(rx), re.I)) for n, p, rx in DOMAIN_RULES]

# --- credential rule -----------------------------------------------------------
_PG = r"(?:mba|pgdm|pgp)"
CREDENTIAL_REJECT_RES = [
    re.compile(rf"(?<![a-z0-9]){_PG}(?:\s*[/&,]\s*{_PG})*\s*(?:\([^)]{{0,30}}\)\s*)?"
               r"(?:students?\s+|candidates?\s+|graduates?\s+)?only(?![a-z0-9])", re.I),
    re.compile(rf"only\s+(?:for\s+)?{_PG}(?![a-z0-9])", re.I),
    re.compile(rf"pursuing\s+(?:an?\s+|their\s+)?(?:mba|pgdm|pgp|cfa)(?![a-z0-9])", re.I),
    re.compile(rf"currently\s+(?:in|doing)\s+(?:an?\s+)?{_PG}(?![a-z0-9])", re.I),
    re.compile(r"(?<![a-z0-9])ca\s*[-/]?\s*(?:inter(?:mediate)?|final)s?(?![a-z0-9])", re.I),
    re.compile(r"(?<![a-z0-9])cfa\s*(?:level|l)\s*[-:]?\s*(?:[1-3]|i{1,3})?(?![a-z0-9])", re.I),
    re.compile(r"(?<![a-z0-9])level\s*(?:[1-3]|i{1,3})\s*cfa(?![a-z0-9])", re.I),
]
# BBA / B.Com / bachelor / undergraduate / graduate (NOT post-graduate)
CREDENTIAL_ALLOW_RE = re.compile(
    r"(?<![a-z0-9])bba(?![a-z0-9])|"
    r"(?<![a-z0-9])b\.?\s?com(?![a-z0-9])|"
    r"(?<![a-z0-9])bachelor|"
    r"undergraduate|"
    r"(?<![a-z0-9])(?<!post[\s-])graduates?(?![a-z0-9])",
    re.I,
)

# --- experience / entry-level --------------------------------------------------
_N = r"(\d{1,2}(?:\.\d)?)"
_YR = r"(?:years?|yrs?)(?![a-z])"
EXP_RANGE_RE = re.compile(rf"(?<![\d.]){_N}\s*(?:-|–|—|to)\s*\d{{1,2}}(?:\.\d)?\s*\+?\s*{_YR}", re.I)
EXP_SINGLE_RE = re.compile(
    rf"(?<![\d.\-]){_N}\s*\+?\s*{_YR}\s*(?:of\s+)?"
    r"(?:(?:relevant|work|professional|prior|total|industry|hands[\s-]on|related)\s+)*"
    r"(?:experience|exp)(?![a-z])", re.I)
EXP_MIN_RE = re.compile(
    rf"(?:minimum|min\.?|at\s*least|more\s+than|over)\s*(?:of\s+)?{_N}\s*\+?\s*{_YR}", re.I)
EXP_OF_RE = re.compile(
    rf"experience\s*(?:of|:|-)?\s*(?:minimum\s*|at\s*least\s*)?{_N}\s*\+?\s*{_YR}", re.I)
EXP_PLUS_RE = re.compile(rf"(?<![\d.\-]){_N}\s*\+\s*{_YR}", re.I)

ENTRY_RE = re.compile(
    _w(r"freshers?|final[\s-]year|entry[\s-]level|2027|"
       r"0\s*(?:-|–|to)\s*1\s*(?:years?|yrs?)|0\s*(?:years?|yrs?)|"
       r"no\s+(?:prior\s+)?experience(?:\s+required)?|recent\s+graduates?"),
    re.I,
)

# --- role types ----------------------------------------------------------------
INTERN_RE = re.compile(_w(r"interns?|internships?"), re.I)
PPO_RE = re.compile(
    _w(r"ppo|pre[\s-]?placement\s+(?:offer|interview)|"
       r"(?:convert|conversion|converted)\s+(?:in)?to\s+(?:a\s+)?(?:full[\s-]?time|permanent)|"
       r"full[\s-]?time\s+(?:offer|conversion)|"
       r"lead(?:s)?\s+to\s+(?:a\s+)?(?:full[\s-]?time|permanent)|"
       r"(?:job|employment)\s+offer\s+(?:post|after|upon|on\s+successful)"),
    re.I,
)
GRAD_PROGRAM_RE = re.compile(
    _w(r"graduate\s+(?:trainee|program(?:me)?|scheme)|management\s+trainee|"
       r"campus\s+(?:hiring|hire|recruit\w*|placements?|program(?:me)?|drive)|"
       r"2027\s+batch|batch\s+of\s+2027|class\s+of\s+2027"),
    re.I,
)

# --- location -------------------------------------------------------------------
NCR_RE = re.compile(
    _w(r"delhi|new\s+delhi|ncr|gurgaon|gurugram|noida|greater\s+noida|ghaziabad|"
       r"faridabad|sahibabad|dwarka"), re.I)
REMOTE_LOC_RE = re.compile(_w(r"remote|work[\s-]from[\s-]home|wfh"), re.I)
REMOTE_TEXT_RE = re.compile(
    _w(r"work[\s-]from[\s-]home|fully\s+remote|100%\s+remote|"
       r"remote\s+(?:work|internship|position|role|opportunity)"), re.I)

# --- Tier-1 (priority signal only, never a filter) --------------------------------
TIER1_NAMES = [
    # global & Indian banks
    "Goldman Sachs", "Morgan Stanley", "J.P. Morgan", "JP Morgan", "JPMorgan",
    "Citi", "Citibank", "Citigroup", "Bank of America", "BofA", "Barclays",
    "Deutsche Bank", "UBS", "HSBC", "Standard Chartered", "BNP Paribas", "Nomura",
    "Macquarie", "Societe Generale", "DBS", "Mizuho", "HDFC Bank", "ICICI Bank",
    "ICICI Securities", "Axis Bank", "Axis Capital", "Kotak Mahindra",
    "Kotak Investment Banking", "SBI Capital Markets", "SBI Caps", "IDFC First",
    "Yes Bank", "IndusInd Bank", "Motilal Oswal", "JM Financial", "Edelweiss",
    # boutique / mid-market IBs
    "Avendus", "Ambit", "Equirus", "DAM Capital", "O3 Capital", "Nuvama", "IIFL",
    "Rothschild", "Lazard", "Evercore", "Houlihan Lokey", "Jefferies",
    # VC / PE
    "Peak XV", "Sequoia", "Accel", "Blume Ventures", "Elevation Capital", "3one4",
    "Kedaara", "Lightspeed", "Matrix Partners", "Nexus Venture Partners",
    "Info Edge", "Stellaris", "Chiratae", "Antler", "Speciale Invest",
    "Kae Capital", "Inventus", "KKR", "Carlyle", "Bain Capital", "Warburg Pincus",
    "TPG",
    # consulting
    "McKinsey", "BCG", "Boston Consulting Group", "Bain & Company", "Bain and Company",
    "Bain & Co", "Oliver Wyman", "Kearney", "Strategy&", "Roland Berger",
    "Arthur D. Little", "Arthur D Little", "L.E.K.", "LEK Consulting",
    "Alvarez & Marsal", "Alvarez and Marsal", "Deloitte", "EY-Parthenon",
    "EY Parthenon", "Redseer", "Zinnov",
    # AMCs
    "ICICI Prudential", "SBI Funds", "SBI Mutual Fund", "Nippon India",
    "HDFC AMC", "HDFC Asset Management", "Kotak AMC", "Kotak Mahindra Asset",
    "Axis Mutual Fund", "Axis AMC", "Axis MF", "Mirae Asset", "DSP Mutual Fund",
    "DSP Asset Managers", "DSP Investment Managers", "UTI AMC", "UTI Mutual Fund",
    "UTI Asset Management", "Aditya Birla Sun Life", "Franklin Templeton",
    "Quant Mutual Fund", "Quant Money Managers", "Parag Parikh", "PPFAS",
    "WhiteOak", "360 ONE", "Marcellus",
]


def _compile_tier1(names):
    parts = [re.escape(n).replace(r"\ ", r"\s+")
             for n in sorted(set(names), key=len, reverse=True)]
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(parts) + r")(?![A-Za-z0-9])", re.I)


TIER1_RE = _compile_tier1(TIER1_NAMES)

# =============================================================================
# LOGGING (never log keys or URLs with query strings)
# =============================================================================

def mask_secrets(text):
    """Replace any configured secret value found in text with ***."""
    if not text:
        return text
    out = str(text)
    for name in SECRET_ENV_NAMES:
        val = os.environ.get(name, "")
        if val and len(val) >= 4:
            out = out.replace(val, "***")
    return out


def safe_url(url):
    """host + path only (no scheme, no query, no fragment)."""
    try:
        parts = urlsplit(str(url))
        return f"{parts.netloc}{parts.path}"
    except Exception:
        return "<unparseable-url>"


class _SecretMaskFilter(logging.Filter):
    def filter(self, record):
        try:
            record.msg = mask_secrets(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


def setup_logging(level=logging.INFO):
    root = logging.getLogger()
    if not any(isinstance(f, _SecretMaskFilter) for f in root.filters):
        root.addFilter(_SecretMaskFilter())
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        h.addFilter(_SecretMaskFilter())
        root.addHandler(h)
    root.setLevel(level)
    return logging.getLogger("internship_bot")


log = logging.getLogger("internship_bot")

# =============================================================================
# TIME (runner is UTC; everything user-facing is IST)
# =============================================================================

def now_ist():
    return datetime.now(IST)


def today_ist():
    return now_ist().date()


# =============================================================================
# parse_date: strings, datetimes, Google Sheets serial numbers
# =============================================================================

SHEETS_EPOCH = date(1899, 12, 30)
SERIAL_MIN, SERIAL_MAX = 25569, 73415       # 1970-01-01 .. 2100-12-31 as serials
_NULL_STRINGS = {"", "na", "n/a", "-", "--", "none", "nan", "nat", "null", "nil"}
_DATE_FORMATS = [
    "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
    "%d %b %y", "%d %B %y", "%b %d %y", "%B %d %y",
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d",
    "%d/%m/%y", "%d-%m-%y", "%d.%m.%y", "%Y%m%d",
]


def _date_from_number(v):
    try:
        if 19000101 <= v <= 21001231 and float(v).is_integer():
            return datetime.strptime(str(int(v)), "%Y%m%d").date()
        if SERIAL_MIN <= v <= SERIAL_MAX:
            return SHEETS_EPOCH + timedelta(days=int(v))
        if 1e9 <= v < 1e11:                        # unix seconds
            return datetime.fromtimestamp(v, IST).date()
        if 1e12 <= v < 1e14:                       # unix milliseconds
            return datetime.fromtimestamp(v / 1000.0, IST).date()
    except (ValueError, OverflowError, OSError):
        return None
    return None


def parse_date(value, default_year=None):
    """
    Return a datetime.date (or None). Accepts datetime/date, Google Sheets serials
    (int/float/numeric string), unix timestamps, ISO strings, and common Indian
    formats (day-first for ambiguous d/m/y). default_year is used for strings
    that carry a month name but no year ("15 Oct").
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        try:
            if value != value:                      # NaT
                return None
            if value.tzinfo is not None:
                value = value.astimezone(IST)
            return value.date()
        except Exception:
            return None
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return _date_from_number(value)

    s = str(value).strip()
    if s.lower() in _NULL_STRINGS:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return _date_from_number(float(s))

    # ISO 8601 (with optional time / timezone)
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(IST)
            return dt.date()
        except ValueError:
            pass

    s = re.sub(r"^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+", "", s, flags=re.I)
    s = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", s, flags=re.I)
    s = re.sub(r"\bsept\b", "sep", s, flags=re.I)
    s = re.sub(r"[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*(?:am|pm)?\s*(?:ist|utc|gmt|z)?$",
               "", s, flags=re.I).strip()
    has_letters = bool(re.search(r"[A-Za-z]", s))
    if has_letters:
        s = re.sub(r"[-/.,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if default_year and has_letters and not re.search(r"\b\d{4}\b", s):
        s = f"{s} {default_year}"
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# =============================================================================
# URL normalization & fingerprints
# =============================================================================

def normalize_url(url):
    """Canonical link for dedup: https, no www, no tracking params, no fragment,
    no trailing slash; aggregator links lose their whole query string."""
    if not url:
        return ""
    u = str(url).strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        u = "https://" + u.lstrip("/")
    try:
        parts = urlsplit(u)
    except ValueError:
        return u
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")
    if any(h in host for h in STRIP_ALL_QUERY_HOSTS):
        query = ""
    else:
        kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k.lower() not in TRACKING_PARAMS
                and not k.lower().startswith(TRACKING_PREFIXES)]
        query = urlencode(sorted(kept))
    return urlunsplit(("https", host, path, query, ""))


_COMPANY_STOP = {"pvt", "private", "ltd", "limited", "llp", "inc", "incorporated",
                 "corp", "corporation", "co", "llc", "plc", "india"}
_TITLE_STOP = {"hiring", "urgent", "urgently", "opening", "openings", "immediate",
               "apply", "now", "job", "jobs", "wanted"}
_TITLE_MAP = {"interns": "intern", "internship": "intern", "internships": "intern",
              "trainees": "trainee", "analysts": "analyst", "associates": "associate"}


def _ascii_lower(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    return s.encode("ascii", "ignore").decode("ascii").lower()


def normalize_company(company):
    s = _ascii_lower(company).replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    toks = [t for t in s.split() if t not in _COMPANY_STOP]
    return " ".join(toks) if toks else s


def normalize_title(title):
    s = _ascii_lower(title)
    s = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    toks = [_TITLE_MAP.get(t, t) for t in s.split() if t not in _TITLE_STOP]
    return " ".join(toks)


def make_fingerprint(company, title):
    c = normalize_company(company) or "unknown"
    t = normalize_title(title)
    if not t:
        return ""
    return "fp:" + hashlib.sha1(f"{c}|{t}".encode("utf-8")).hexdigest()[:20]


def link_key(url):
    n = normalize_url(url)
    return f"url:{n}" if n else ""


def listing_keys(item):
    """(link_key, fingerprint_key) used for in-run and cross-run dedup."""
    return (link_key(item.get("link") or item.get("url")),
            make_fingerprint(item.get("company"), item.get("title")))


# =============================================================================
# FILTERS
# =============================================================================

def is_noise_title(title):
    m = NOISE_RE.search(title or "")
    return m.group(0) if m else None


def classify_domain(title, text=""):
    """First-match-wins domain. Title first; falls back to the description head.
    Returns (name, points) or None."""
    for src in (title or "", (text or "")[:DOMAIN_TEXT_CHARS]):
        if not src:
            continue
        for name, pts, rx in DOMAIN_RULES:
            if rx.search(src):
                return name, pts
    return None


def title_gate(title, snippet=""):
    """Cheap pre-detail gate: not noisy AND a domain match in title (or card snippet)."""
    if not (title or "").strip():
        return False, "no title"
    n = is_noise_title(title)
    if n:
        return False, f"noise title ({n.strip().lower()})"
    if not classify_domain(title, snippet):
        return False, "no domain match"
    return True, ""


def credential_ok(text):
    """Reject MBA/PGDM-only, pursuing MBA/PGDM/CFA, CA inter/final, CFA level
    UNLESS BBA / B.Com / bachelor / undergraduate / graduate is also mentioned."""
    t = text or ""
    for rx in CREDENTIAL_REJECT_RES:
        m = rx.search(t)
        if m:
            if CREDENTIAL_ALLOW_RE.search(t):
                return True, ""
            return False, f"credential requirement ({m.group(0).strip().lower()})"
    return True, ""


def required_years(text):
    """Minimum years of experience mentioned (smallest across matches), or None."""
    vals = []
    t = text or ""
    for rx in (EXP_RANGE_RE, EXP_SINGLE_RE, EXP_MIN_RE, EXP_OF_RE, EXP_PLUS_RE):
        for m in rx.finditer(t):
            try:
                vals.append(float(m.group(1)))
            except (ValueError, IndexError):
                pass
    return min(vals) if vals else None


def has_entry_signal(text):
    return bool(ENTRY_RE.search(text or ""))


def experience_ok(role_type, text):
    yrs = required_years(text)
    if role_type in INTERNSHIP_TYPES:
        if yrs is not None and yrs >= INTERN_MAX_YEARS_REJECT:
            return False, f"internship needs {yrs:g}+ yrs"
        return True, ""
    if yrs is not None and yrs >= OTHER_MAX_YEARS_REJECT:
        return False, f"needs {yrs:g}+ yrs"
    if role_type == "Full-time":
        if (yrs is not None and yrs <= FULLTIME_FRESHER_MAX_YEARS) or has_entry_signal(text):
            return True, ""
        return False, "full-time without fresher / 0-1 yr signal"
    return True, ""


def classify_role_type(title, text="", hint=None):
    """hint: optional source-provided type (e.g. 'Internship' for Internshala)."""
    t, body = title or "", text or ""
    both = f"{t} {body}"
    if INTERN_RE.search(t):
        return "PPO Internship" if PPO_RE.search(both) else "Internship"
    if GRAD_PROGRAM_RE.search(t):
        return "Graduate Program"
    if hint in INTERNSHIP_TYPES:
        return "PPO Internship" if PPO_RE.search(both) else "Internship"
    if GRAD_PROGRAM_RE.search(body):
        return "Graduate Program"
    if INTERN_RE.search(body[:ROLE_TEXT_HEAD_CHARS]):
        return "PPO Internship" if PPO_RE.search(both) else "Internship"
    return "Full-time"


def location_kind(location, title="", text=""):
    """'ncr' | 'remote' | 'other' | 'unknown'."""
    loc = (location or "").strip()
    if NCR_RE.search(loc):
        return "ncr"
    if REMOTE_LOC_RE.search(loc) or REMOTE_LOC_RE.search(title or "") or REMOTE_TEXT_RE.search(text or ""):
        return "remote"
    return "other" if loc else "unknown"


def location_ok(kind, strict=None):
    strict = STRICT_LOCATION if strict is None else strict
    if not strict:
        return True, ""
    if kind in ("ncr", "remote", "unknown"):   # unknown = no location given, can't judge
        return True, ""
    return False, "outside Delhi NCR / remote"


# =============================================================================
# Deadline extraction
# =============================================================================

_MON = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
        r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_DATE_FRAG = (
    rf"\d{{1,2}}(?:st|nd|rd|th)?[\s\-/.]*{_MON}\b\.?(?:[\s,\-/.]*\d{{4}})?"
    rf"|{_MON}\b\.?\s*\d{{1,2}}(?:st|nd|rd|th)?(?:\s*,?\s*\d{{4}})?"
    r"|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
)
DEADLINE_RE = re.compile(
    r"(?:last\s+date(?:\s+(?:to|for)\s+(?:apply(?:ing)?|application|submission))?|"
    r"apply\s+(?:by|before|till|until)|application\s+deadline|deadline|closing\s+date|"
    r"applications?\s+(?:close|closes|closing)(?:\s+on)?|due\s+(?:by|on)|valid\s+(?:till|until))"
    r"[\s:\-–]*(?:(?:is|on|by)[\s:\-–]*)*"
    rf"({_DATE_FRAG})",
    re.I,
)


def extract_deadline(text, today=None):
    """Earliest upcoming deadline found in free text (past dates ignored), or None."""
    today = today or today_ist()
    best = None
    for m in DEADLINE_RE.finditer(text or ""):
        frag = m.group(1)
        d = parse_date(frag, default_year=today.year)
        if d is None:
            continue
        has_year = bool(re.search(r"\d{4}|\d[/\-.]\d{1,2}[/\-.]\d{2}\b", frag))
        if d < today and not has_year:
            try:
                nxt = d.replace(year=d.year + 1)
            except ValueError:
                nxt = None
            if nxt and (nxt - today).days <= DEADLINE_ROLLOVER_DAYS:
                d = nxt
        if d >= today and (best is None or d < best):
            best = d
    return best


# =============================================================================
# Tier-1 & scoring
# =============================================================================

def tier1_match(company, title=""):
    """Company name only (case-insensitive); title only if company is missing."""
    src = company if (company or "").strip() else title
    m = TIER1_RE.search(src or "")
    return m.group(0).strip() if m else None


def score_listing(role_type, domain_pts, tier1, loc_kind, entry_signal, deadline, today=None):
    today = today or today_ist()
    b = {
        "company": SCORE_TIER1 if tier1 else 0,
        "domain": int(domain_pts or 0),
        "role": ROLE_POINTS.get(role_type, 0),
        "location": SCORE_LOC_NCR if loc_kind == "ncr" else (SCORE_LOC_REMOTE if loc_kind == "remote" else 0),
        "entry": SCORE_ENTRY_SIGNAL if entry_signal else 0,
        "deadline": 0,
    }
    if deadline is not None and 0 <= (deadline - today).days <= DEADLINE_SOON_DAYS:
        b["deadline"] = SCORE_DEADLINE_SOON
    return min(sum(b.values()), SCORE_CAP), b


def evaluate_listing(item, today=None, strict_location=None, role_hint=None):
    """
    Run the full Phase 1 rule chain on one listing dict
    (title, company, location, description, link, deadline[optional]).
    Returns a result dict; result['keep'] False means rejected (see 'reason').
    Quality gate / detail-fetch policy come in Phase 3.
    """
    today = today or today_ist()
    title = (item.get("title") or "").strip()
    company = (item.get("company") or "").strip()
    location = item.get("location") or ""
    desc = item.get("description") or ""
    text = f"{title}\n{desc}"
    res = {"keep": False, "reason": "", "score": 0}

    def reject(reason):
        res["reason"] = reason
        return res

    if not title:
        return reject("no title")
    noise = is_noise_title(title)
    if noise:
        return reject(f"noise title ({noise.strip().lower()})")
    dom = classify_domain(title, desc)
    if not dom:
        return reject("no domain match")
    ok, why = credential_ok(text)
    if not ok:
        return reject(why)
    role = classify_role_type(title, desc, hint=role_hint)
    ok, why = experience_ok(role, text)
    if not ok:
        return reject(why)
    kind = location_kind(location, title, desc)
    ok, why = location_ok(kind, strict_location)
    if not ok:
        return reject(why)

    deadline = extract_deadline(text, today) or None
    if deadline is None:
        d = parse_date(item.get("deadline"))
        deadline = d if (d and d >= today) else None
    t1 = tier1_match(company, title)
    entry = has_entry_signal(text)
    score, breakdown = score_listing(role, dom[1], t1, kind, entry, deadline, today)
    lk, fp = listing_keys(item)
    res.update({
        "keep": True, "score": score, "breakdown": breakdown, "role_type": role,
        "domain": dom[0], "domain_pts": dom[1], "tier1": t1, "location_kind": kind,
        "entry_signal": entry, "deadline": deadline, "link_key": lk, "fp_key": fp,
        "ppo": role == "PPO Internship",
    })
    return res


# =============================================================================
# main (Phase 1: foundation only)
# =============================================================================

def main():
    setup_logging()
    log.info("internship_bot Phase 1 foundation loaded (today IST: %s). "
             "Scrapers/Sheets/Excel/email are not implemented yet.", today_ist().isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
