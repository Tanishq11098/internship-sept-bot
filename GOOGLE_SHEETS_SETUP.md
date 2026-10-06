# Google Sheets Setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project.
3. Enable the **Google Sheets API** and **Google Drive API**.
4. Go to Credentials, create a **Service Account**.
5. Create a new JSON key for the Service Account and download it.
6. Open your Google Sheet, and share it (Editor access) with the Service Account email address.
7. Copy the JSON key contents into the GitHub Secret `GOOGLE_SERVICE_ACCOUNT_JSON`.
8. Copy the ID of your Google Sheet from the URL into the GitHub Secret `GSHEET_ID`.

The bot will automatically manage `seen_listings`, `all_listings`, and `tracker` tabs.
