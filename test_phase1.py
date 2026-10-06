"""Offline tests for Phase 1. Run: python test_phase1.py  (or pytest)."""
import sys
from datetime import date, datetime, timedelta, timezone

import internship_bot as b

TODAY = date(2026, 10, 6)
FAILS = []


def check(name, cond, extra=""):
    if not cond:
        FAILS.append(f"{name} {extra}".strip())


def test_noise():
    for t in ["Software Developer Intern", "Senior Analyst", "Sr. Analyst", "Marketing Intern",
              "HR Intern", "BDE Intern", "Business Development Intern", "Chief Executive Officer",
              "Manager - Strategy", "Vice President Finance", "Head of Strategy", "Team Lead Finance",
              "SEO Intern", "Customer Success Intern", "Content Writer Finance", "AVP Research",
              "Brand Strategy Intern", "Principal Consultant", "Director Finance", "Sales Intern",
              "Telecaller Finance", "Data Scientist Intern", "DevOps Intern", "Social Media Intern"]:
        check("noise-reject " + t, b.is_noise_title(t) is not None)
    for t in ["Chief of Staff Intern", "Management Trainee", "Finance Intern", "Equity Research Analyst",
              "Strategy Associate Intern", "Chief of Staff to the CEO", "Leadership Development Intern"]:
        check("noise-pass " + t, b.is_noise_title(t) is None, str(b.is_noise_title(t)))


def test_domains():
    cases = {
        "Venture Capital Intern": "VC/PE", "Private Equity Analyst": "VC/PE",
        "Investment Banking Summer Intern": "Investment Banking", "M&A Analyst Intern": "Investment Banking",
        "Equity Research Intern": "Equity Research",
        "Portfolio Management Intern": "Portfolio/Asset Mgmt", "Asset Management Intern": "Portfolio/Asset Mgmt",
        "Founder's Office Intern": "Founder's Office/CoS", "Founder\u2019s Office Intern": "Founder's Office/CoS",
        "Founders Office Intern": "Founder's Office/CoS", "CEO's Office Intern": "Founder's Office/CoS",
        "Special Projects Intern": "Founder's Office/CoS", "Chief of Staff Intern": "Founder's Office/CoS",
        "Strategy & Operations Intern": "Strategy & Operations", "Business Operations Intern": "Strategy & Operations",
        "Program Management Intern": "Strategy & Operations",
        "Consulting Intern": "Consulting/Strategy", "Strategy Intern": "Consulting/Strategy",
        "Corporate Development Intern": "Corp Dev/IR", "Investor Relations Intern": "Corp Dev/IR",
        "Policy Research Intern": "Research & Policy", "Finance Intern": "Finance (General)",
        "Financial Analyst Fresher": "Finance (General)",
    }
    for t, exp in cases.items():
        d = b.classify_domain(t)
        check("domain " + t, d is not None and d[0] == exp, f"got {d}")
    check("domain none", b.classify_domain("Graphic Design Intern") is None)
    check("domain points", b.classify_domain("Venture Capital Intern")[1] == 30
          and b.classify_domain("Equity Research Intern")[1] == 27
          and b.classify_domain("Finance Intern")[1] == 15)
    check("gate ok", b.title_gate("Finance Intern")[0])
    check("gate noise", not b.title_gate("Sales Finance Intern")[0])
    check("gate nodomain", not b.title_gate("Management Trainee")[0])
    check("gate snippet", b.title_gate("Management Trainee", "banking and finance")[0])


def test_credentials():
    bad = ["Open to MBA/PGDM only", "Candidates pursuing MBA from top B-school", "pursuing PGDM",
           "CA Inter / Final students", "CA Final qualified", "CFA Level 1 cleared", "CFA level II candidate",
           "MBA only", "pursuing CFA", "Only MBA students", "MBA (Finance) only",
           "Postgraduate students, MBA/PGDM only", "post-graduate pursuing MBA", "post graduate MBA only"]
    good = ["Pursuing MBA or BBA", "MBA/PGDM only; BBA students can also apply", "B.Com or MBA only",
            "Bachelor's degree, pursuing MBA", "Graduate or pursuing MBA", "undergraduate pursuing MBA",
            "Final year BBA student", "Finance interest, MBA preferred", "no credential text"]
    for t in bad:
        check("cred-reject " + t, not b.credential_ok(t)[0])
    for t in good:
        check("cred-pass " + t, b.credential_ok(t)[0], b.credential_ok(t)[1])


def test_experience():
    r = b.required_years
    check("yrs 2-5 yrs", r("Experience: 2-5 yrs") == 2)
    check("yrs 0-1", r("0-1 Yrs") == 0)
    check("yrs 3+", r("3+ years experience in finance") == 3)
    check("yrs minimum", r("minimum 2 years") == 2)
    check("yrs none", r("no mention here") is None)
    check("yrs 2 to 4", r("2 to 4 years of experience") == 2)
    check("yrs experience of", r("experience of 5 years") == 5)
    E = b.experience_ok
    check("intern 3y rej", not E("Internship", "requires 3+ years experience")[0])
    check("intern 2y ok", E("Internship", "2 years experience")[0])
    check("intern none ok", E("Internship", "")[0])
    check("ppo 3y rej", not E("PPO Internship", "3 years experience")[0])
    check("ft 2y rej", not E("Full-time", "Experience: 2-5 yrs")[0])
    check("ft 0-1 ok", E("Full-time", "0-1 yrs")[0])
    check("ft fresher ok", E("Full-time", "Freshers can apply")[0])
    check("ft none rej", not E("Full-time", "great role")[0])
    check("gp 2y rej", not E("Graduate Program", "2 years experience")[0])
    check("gp none ok", E("Graduate Program", "")[0])
    check("ft 1y ok", E("Full-time", "1 year experience")[0])


def test_roles():
    C = b.classify_role_type
    check("role intern", C("Finance Intern") == "Internship")
    check("role ppo", C("Finance Intern", "Pre-placement offer (PPO) for top performers") == "PPO Internship")
    check("role ppo2", C("Strategy Internship", "may convert to full-time") == "PPO Internship")
    check("role gp", C("Graduate Trainee - Finance") == "Graduate Program")
    check("role mt", C("Management Trainee") == "Graduate Program")
    check("role campus", C("Finance Analyst", "campus hiring 2027 batch") == "Graduate Program")
    check("role ft", C("Financial Analyst", "Freshers welcome") == "Full-time")
    check("role hint", C("Research Analyst", "", hint="Internship") == "Internship")
    check("role body intern", C("Finance Analyst", "Internship duration 3 months") == "Internship")
    check("role ft not intern late", C("Finance Analyst", "x" * 500 + " internship experience") == "Full-time")


def test_location():
    K = b.location_kind
    check("loc ncr", K("Gurugram, Haryana") == "ncr" and K("New Delhi") == "ncr" and K("Delhi/NCR") == "ncr"
          and K("Noida") == "ncr")
    check("loc multi", K("Mumbai, Delhi") == "ncr")
    check("loc remote", K("Work From Home") == "remote" and K("Remote") == "remote")
    check("loc remote text", K("Pune", "", "this is a fully remote role") == "remote")
    check("loc other", K("Mumbai") == "other" and K("Bengaluru") == "other")
    check("loc unknown", K("") == "unknown")
    check("loc strict other", not b.location_ok("other", True)[0])
    check("loc strict ncr", b.location_ok("ncr", True)[0])
    check("loc nonstrict", b.location_ok("other", False)[0])


def test_dates():
    P = b.parse_date
    check("serial", P(46300) == date(1899, 12, 30) + timedelta(days=46300))
    check("serial 45000", P(45000) == date(2023, 3, 15))
    check("serial float", P(45000.0) == date(2023, 3, 15))
    check("serial str", P("45000") == date(2023, 3, 15) and P("45000.0") == date(2023, 3, 15))
    check("iso", P("2026-10-05") == date(2026, 10, 5))
    check("iso time z", P("2026-10-05T20:00:00Z") == date(2026, 10, 6))   # 01:30 IST next day
    check("dmy slash", P("10/05/2026") == date(2026, 5, 10))
    check("dmy dash", P("15-10-2026") == date(2026, 10, 15))
    check("dmy dot", P("15.10.2026") == date(2026, 10, 15))
    check("d mon y", P("15 Oct 2026") == date(2026, 10, 15))
    check("ordinal", P("15th October 2026") == date(2026, 10, 15))
    check("mon d, y", P("Oct 15, 2026") == date(2026, 10, 15))
    check("sept", P("5 Sept 2026") == date(2026, 9, 5))
    check("weekday", P("Mon, 5 Oct 2026") == date(2026, 10, 5))
    check("with time", P("5 Oct 2026 10:30 AM") == date(2026, 10, 5))
    check("2digit", P("15/10/26") == date(2026, 10, 15))
    check("compact", P("20261005") == date(2026, 10, 5) and P(20261005) == date(2026, 10, 5))
    check("datetime", P(datetime(2026, 10, 5, 10)) == date(2026, 10, 5))
    check("tz aware", P(datetime(2026, 10, 5, 20, tzinfo=timezone.utc)) == date(2026, 10, 6))
    check("unix", P(1790000000) is not None)
    check("default year", P("15 Oct", default_year=2026) == date(2026, 10, 15))
    for bad in [None, "", "N/A", "garbage", float("nan"), True, "2026", "-"]:
        check(f"bad {bad!r}", P(bad) is None)


def test_deadline():
    X = lambda t: b.extract_deadline(t, TODAY)
    check("dl last date", X("Last date to apply: 15 Oct 2026") == date(2026, 10, 15))
    check("dl apply by", X("Apply by 20th October 2026.") == date(2026, 10, 20))
    check("dl no year", X("Deadline: 15 November") == date(2026, 11, 15))
    check("dl numeric", X("Application deadline - 12/10/2026") == date(2026, 10, 12))
    check("dl iso", X("deadline is 2026-10-30") == date(2026, 10, 30))
    check("dl past ignored", X("Last date to apply: 1 Sep 2026") is None)
    check("dl past noyear far", X("apply by 1 June") is None)
    check("dl rollover", X("apply by 5 January") == date(2027, 1, 5))
    check("dl today ok", X("Last date: 6 Oct 2026") == TODAY)
    check("dl none", X("No deadline info 15 Oct 2026") is None)
    check("dl earliest", X("apply by 30 Oct 2026. Last date 15 Oct 2026") == date(2026, 10, 15))
    check("dl mon first", X("Closing date: October 25, 2026") == date(2026, 10, 25))


def test_urls_and_fingerprints():
    N = b.normalize_url
    check("url utm", N("https://www.Example.com/jobs/1/?utm_source=x&utm_medium=y&id=5#frag")
          == "https://example.com/jobs/1?id=5")
    check("url ref/src", N("http://example.com/j/?ref=abc&src=li") == "https://example.com/j")
    check("url slash", N("https://example.com/a/b///") == "https://example.com/a/b")
    check("url adzuna", N("https://www.adzuna.in/land/ad/123?se=abc&v=zzz") == "https://adzuna.in/land/ad/123")
    check("url sorted", N("https://e.com/x?b=2&a=1") == "https://e.com/x?a=1&b=2")
    check("url noscheme", N("e.com/x/") == "https://e.com/x")
    check("url empty", N("") == "" and N(None) == "")
    check("safe_url", b.safe_url("https://api.x.com/v1/search?key=SECRET&q=a") == "api.x.com/v1/search")
    a = b.make_fingerprint("Avendus Capital Pvt. Ltd.", "Finance Intern (Gurgaon)")
    c = b.make_fingerprint("avendus capital private limited", "Finance Internship")
    check("fp equal", a == c and a.startswith("fp:"))
    check("fp differ", a != b.make_fingerprint("Avendus Capital", "Strategy Intern"))
    check("fp &", b.make_fingerprint("Alvarez & Marsal", "Finance Intern")
          == b.make_fingerprint("Alvarez and Marsal", "Finance Intern"))
    check("fp empty title", b.make_fingerprint("X", "") == "")
    lk, fp = b.listing_keys({"link": "https://e.com/x?utm_a=1", "company": "X", "title": "Y"})
    check("keys", lk == "url:https://e.com/x" and fp.startswith("fp:"))
    import os
    os.environ["APIFY_TOKEN"] = "tok_supersecret123"
    check("mask", "tok_supersecret123" not in b.mask_secrets("token=tok_supersecret123"))
    del os.environ["APIFY_TOKEN"]


def test_tier1():
    T = b.tier1_match
    for c in ["Strategy&", "Strategy& India", "Peak XV Partners", "McKinsey & Company", "Goldman Sachs",
              "Bain & Company", "Alvarez and Marsal", "360 ONE Asset", "3one4 Capital", "EY-Parthenon",
              "HOULIHAN LOKEY", "Nippon India Mutual Fund", "KKR India", "Kotak Mahindra Bank", "Info Edge (India)"]:
        check("tier1 " + c, T(c) is not None)
    for c in ["Citywide Finance", "Acme Capital", "Matrixx Labs", "Accelerated Learning", "Ambitious Co", "BCGX"]:
        check("tier1-no " + c, T(c) is None, str(T(c)))
    check("tier1 title fallback", T("", "Intern at Sequoia Capital") is not None)
    check("tier1 company wins", T("Acme", "Intern at Sequoia") is None)


def test_scoring():
    s, br = b.score_listing("PPO Internship", 30, "Sequoia", "ncr", True, TODAY + timedelta(days=5), TODAY)
    check("score max 100", s == 100, str(br))
    s, _ = b.score_listing("Internship", 15, None, "other", False, None, TODAY)
    check("score min", s == 27, str(s))
    s, br = b.score_listing("Graduate Program", 25, None, "remote", True, TODAY + timedelta(days=20), TODAY)
    check("score remote/no deadline", s == 25 + 18 + 8 + 6 and br["deadline"] == 0, str(br))
    s, br = b.score_listing("Full-time", 22, "KKR", "ncr", False, TODAY + timedelta(days=14), TODAY)
    check("score deadline 14", br["deadline"] == 4 and s == 30 + 22 + 14 + 10 + 4, str(br))
    s, br = b.score_listing("Full-time", 22, None, "ncr", False, TODAY - timedelta(days=1), TODAY)
    check("score past deadline", br["deadline"] == 0)


def test_evaluate():
    E = lambda **k: b.evaluate_listing(k, today=TODAY, strict_location=True)
    r = E(title="Venture Capital Intern", company="Peak XV Partners", location="Gurugram",
          description="Freshers and final year BBA students. PPO possible. Last date to apply: 12 Oct 2026",
          link="https://x.com/j/1?utm_source=a")
    check("eval keep", r["keep"], r["reason"])
    check("eval fields", r.get("role_type") == "PPO Internship" and r.get("domain") == "VC/PE"
          and r.get("tier1") and r.get("deadline") == date(2026, 10, 12))
    check("eval score", r.get("score") == 100, str(r.get("breakdown")))
    r = E(title="Finance Intern", company="Acme", location="Mumbai", description="")
    check("eval loc reject", not r["keep"] and "NCR" in r["reason"], r["reason"])
    r = E(title="Finance Intern", company="Acme", location="Mumbai", description="")
    r2 = b.evaluate_listing({"title": "Finance Intern", "company": "Acme", "location": "Mumbai"},
                            today=TODAY, strict_location=False)
    check("eval nonstrict keep", r2["keep"])
    r = E(title="Equity Research Intern", company="X", location="Delhi", description="MBA/PGDM only")
    check("eval cred reject", not r["keep"] and "credential" in r["reason"], r["reason"])
    r = E(title="Financial Analyst", company="X", location="Noida", description="Experience: 2-5 yrs")
    check("eval exp reject", not r["keep"] and "yrs" in r["reason"], r["reason"])
    r = E(title="Financial Analyst", company="X", location="Noida", description="Fresher / 0-1 years")
    check("eval ft ok", r["keep"] and r["role_type"] == "Full-time", r["reason"])
    r = E(title="Marketing Intern", company="X", location="Delhi")
    check("eval noise", not r["keep"] and "noise" in r["reason"])
    r = E(title="Operations Intern", company="X", location="Delhi")
    check("eval nodomain", not r["keep"] and "domain" in r["reason"])
    r = E(title="Chief of Staff Intern", company="Startup", location="Remote",
          description="Direct work with CEO. Apply by 20 Oct 2026", deadline="2026-12-01")
    check("eval cos", r["keep"] and r["domain"] == "Founder's Office/CoS" and r["location_kind"] == "remote",
          r["reason"])
    r = E(title="Finance Intern", company="X", location="Delhi", description="", deadline=46300)
    check("eval serial deadline", r["keep"] and r["deadline"] == date(1899, 12, 30) + timedelta(days=46300)
          if date(1899, 12, 30) + timedelta(days=46300) >= TODAY else r["keep"])


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        n = len(FAILS)
        try:
            t()
        except Exception as e:  # noqa
            FAILS.append(f"{t.__name__} crashed: {e!r}")
        print(f"{'PASS' if len(FAILS) == n else 'FAIL'}  {t.__name__}")
    print(f"\n{len(tests) - len({f.split()[0] for f in FAILS})} groups ok, {len(FAILS)} failed checks")
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
