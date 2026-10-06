# Internship Bot

An automated job-hunting bot that scrapes various job boards, ATS platforms, and APIs to find high-quality internships and entry-level finance/strategy roles, scores them, and delivers a daily summary via email and Google Sheets.

## Setup
1. Clone the repository
2. Set up GitHub Secrets and Variables (see below)
3. The bot runs automatically every day at 8:00 AM IST.

## GitHub Secrets and Variables
Secrets:
- `EMAIL`: Your Gmail address
- `PASSWORD`: Your Gmail App Password
- `EMAIL_TO`: Where to send the daily report
- `GSHEET_ID`: The ID of your Google Sheet
- `GOOGLE_SERVICE_ACCOUNT_JSON`: The full JSON of your Google Service Account
- (Optional APIs): `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `RAPIDAPI_KEY`, `JOOBLE_KEY`, `SERPAPI_KEY`, `APIFY_TOKEN`

Variables:
- `ATS_GREENHOUSE`, `ATS_LEVER`: Comma separated lists of board tokens
- `APIFY_ACTORS`: Comma separated Apify actor IDs
- `APIFY_INPUT_JSON`: JSON input string for Apify, supports {query} and {location}

All Rights Reserved.
