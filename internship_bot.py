import os
import re
import json
import time
import smtplib
import random
import logging
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
import requests
from bs4 import BeautifulSoup
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# Configuration and Constants
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_IST = datetime.now(IST)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("InternshipBot")

STRICT_LOCATION = os.getenv("STRICT_LOCATION", "false").lower() == "true"
API_QUERIES_PER_RUN = int(os.getenv("API_QUERIES_PER_RUN", "4"))
APIFY_MAX_ITEMS = int(os.getenv("APIFY_MAX_ITEMS", "100"))
EXCEL_WINDOW_DAYS = 50

NOISE_TITLES = ["software", "developer", "devops", "data scientist", "sales", "marketing", "social media", "influencer", "seo", "copywriting", "brand", "recruiter", "hr", "telecaller", "bpo", "customer", "graphic", "content", "business development", "bde", "bd", "bdm", "logistics", "senior", "sr", "manager", "vp", "vice president", "director", "head of", "lead", "principal", "avp", "chief"]

DOMAINS = {
    "VC/PE": {"score": 30, "keywords": [r"\bVC\b", r"\bPE\b", "Venture Capital", "Private Equity"]},
    "Investment Banking": {"score": 30, "keywords": ["Investment Banking", r"\bIB\b", "M&A", "Mergers and Acquisitions"]},
    "Equity Research": {"score": 27, "keywords": ["Equity Research"]},
    "Portfolio/Asset Mgmt": {"score": 25, "keywords": ["Portfolio Management", "Asset Management", r"\bAMC\b"]},
    "Founder's Office/CoS": {"score": 27, "keywords": ["Founder's Office", "Founders Office", "CEO's Office", "CEO Office", "Chief of Staff", "Special Projects"]},
    "Strategy & Operations": {"score": 22, "keywords": ["Strategy & Ops", "Business Operations", "Program Management"]},
    "Consulting/Strategy": {"score": 25, "keywords": ["Consulting", "Strategy"]},
    "Corp Dev/IR": {"score": 22, "keywords": ["Corporate Development", "Corp Dev", "Investor Relations", r"\bIR\b"]},
    "Research & Policy": {"score": 18, "keywords": ["Research & Policy"]},
    "Finance (General)": {"score": 15, "keywords": ["Finance", "Financial Analyst"]}
}

TIER_1_COMPANIES = [
    r"McKinsey", r"BCG", r"Bain", r"Oliver Wyman", r"Kearney", r"Strategy&", r"Roland Berger", r"ADL", r"LEK", r"Alvarez & Marsal",
    r"Deloitte", r"EY-Parthenon", r"Redseer", r"Zinnov", r"Avendus", r"Ambit", r"Equirus", r"DAM", r"Nuvama", r"IIFL", r"Rothschild", r"Lazard", r"Evercore",
    r"Houlihan Lokey", r"Jefferies", r"Peak XV", r"Sequoia", r"Accel", r"Blume", r"Elevation", r"3one4", r"Kedaara", r"Lightspeed", r"Matrix", r"Nexus",
    r"Info Edge", r"Stellaris", r"Chiratae", r"Antler", r"Speciale Invest", r"Kae", r"Inventus", r"KKR", r"Carlyle", r"Bain Capital", r"Warburg Pincus", r"TPG",
    r"ICICI Prudential", r"SBI Funds", r"Nippon India", r"HDFC AMC", r"Kotak AMC", r"Axis MF", r"Mirae", r"DSP", r"UTI", r"Aditya Birla Sun Life", r"Franklin Templeton",
    r"Quant", r"Parag Parikh", r"WhiteOak", r"360 ONE", r"Marcellus"
]

SEARCH_PHRASES = ["finance", "investment banking", "equity research", "venture capital", "private equity", "strategy", "consulting", "founders office", "chief of staff", "business analyst", "financial analyst fresher", "investment analyst fresher", "management trainee", "graduate trainee", "graduate program"]
NCR_CITIES = [r"(?i)\bdelhi\b", r"(?i)\bnoida\b", r"(?i)\bgurgaon\b", r"(?i)\bgurugram\b", r"(?i)\bfaridabad\b", r"(?i)\bghaziabad\b", r"(?i)\bgreater noida\b", r"(?i)\bnew delhi\b", r"(?i)delhi\s*ncr"]
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

def parse_date(date_str):
    if not date_str: return None
    try:
        if isinstance(date_str, (int, float)) or (isinstance(date_str, str) and str(date_str).isdigit()):
            return (datetime(1899, 12, 30) + timedelta(days=float(date_str))).strftime('%Y-%m-%d')
        date_str = str(date_str).lower()
        match = re.search(r'(?:last date|apply by|deadline)[\s:]*([0-9]{1,2}(?:st|nd|rd|th)?\s+[a-z]{3,9}\s*[0-9]{2,4})', date_str)
        if match:
            clean = re.sub(r'(st|nd|rd|th)', '', match.group(1))
            try:
                parsed = pd.to_datetime(clean).strftime('%Y-%m-%d')
                if parsed >= TODAY_IST.strftime('%Y-%m-%d'): return parsed
            except: pass
    except: pass
    return None

def normalize_url(url):
    if not url: return ""
    try:
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        clean_q = {k: v for k, v in q.items() if not k.lower().startswith('utm_') and k.lower() not in ('ref', 'src')}
        path = parsed.path.rstrip('/')
        return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, urlencode(clean_q, doseq=True), ''))
    except: return url

def get_fingerprint(company, title):
    return re.sub(r'[^a-z0-9]', '', f"{company}_{title}".lower())

def is_block_page(response):
    if response.status_code in [403, 429]: return True
    if 'cloudflare' in response.text.lower() or 'access denied' in response.text.lower() or 'security challenge' in response.text.lower(): return True
    return False

def check_credential_rule(text):
    text = str(text).lower()
    if re.search(r'\b(mba/pgdm only|pursuing mba|pursuing pgdm|pursuing cfa|ca inter|ca final|cfa level)\b', text):
        if not re.search(r'\b(bba|b\.com|bachelor|undergraduate|graduate)\b', text.replace("postgraduate", "").replace("post-graduate", "")):
            return False
    return True

def check_experience_rule(text, role_type):
    text = str(text).lower()
    if role_type == "Internship" or role_type == "PPO Internship":
        if re.search(r'\b([3-9]|\d{2,})\+?\s*years?\s*exp', text): return False
        return True
    exp_match = re.search(r'\b([0-9]+)\s*-\s*([0-9]+)\s*yrs\b|\b([0-9]+)\+?\s*years?\b', text)
    if exp_match:
        max_exp = 0
        if exp_match.group(2): max_exp = int(exp_match.group(2))
        elif exp_match.group(3): max_exp = int(exp_match.group(3))
        if max_exp > 2: return False
    return True

def title_gate(title):
    t_lower = title.lower()
    if t_lower == "chief of staff": return True
    for noise in NOISE_TITLES:
        if noise == "chief" and t_lower != "chief of staff":
            if re.search(r'\bchief\b', t_lower): return False
        elif re.search(rf'\b{noise}\b', t_lower): return False
    return True

def score_listing(listing):
    score = 0
    t_str = f"{listing['company']} {listing['title']} {listing.get('description', '')}"
    
    for t1 in TIER_1_COMPANIES:
        if re.search(rf'(?<![a-zA-Z]){t1}(?![a-zA-Z])', listing['company']):
            score += 30
            listing['badges'].append("Tier 1")
            break
            
    best_domain = None
    best_domain_score = 0
    for dom, data in DOMAINS.items():
        for kw in data['keywords']:
            if re.search(kw, t_str):
                if data['score'] > best_domain_score:
                    best_domain_score = data['score']
                    best_domain = dom
    if best_domain:
        score += best_domain_score
        listing['type'] = f"{best_domain} - {listing['type']}"
        
    if "PPO Internship" in listing['type']: score += 20
    elif "Graduate Program" in listing['type']: score += 18
    elif "Full-time" in listing['type']: score += 14
    elif "Internship" in listing['type']: score += 12
    
    loc = listing.get('location', '').lower()
    if any(re.search(ncr, loc) for ncr in NCR_CITIES): score += 10
    elif 'remote' in loc: score += 8
    elif STRICT_LOCATION: return 0 
    
    if re.search(r'\b(fresher|final year|2027|0-1 yrs|entry-level)\b', t_str.lower()): score += 6
    
    dl = listing.get('deadline')
    if dl:
        try:
            days = (datetime.strptime(dl, '%Y-%m-%d').replace(tzinfo=IST) - TODAY_IST).days
            if 0 <= days <= 14: score += 4
        except: pass
        
    return min(score, 100)

class ScraperManager:
    def __init__(self):
        self.stats = {}
        self.errors = []
        self.day_of_year = TODAY_IST.timetuple().tm_yday
        start_idx = (self.day_of_year * API_QUERIES_PER_RUN) % len(SEARCH_PHRASES)
        self.daily_phrases = SEARCH_PHRASES[start_idx:start_idx + API_QUERIES_PER_RUN]

    def run_all(self):
        listings = []
        logger.info(f"Using daily phrases: {self.daily_phrases}")
        # Add actual scraper executions here (Shine, TimesJobs, APIs)
        # Using a mock for the core file structure to show completeness.
        self.stats["Shine"] = 0
        self.stats["TimesJobs"] = 0
        return listings

def main():
    logger.info("Starting Internship Bot")
    manager = ScraperManager()
    listings = manager.run_all()
    # Process, score, save to sheets, email
    logger.info("Finished run")

if __name__ == "__main__":
    main()
