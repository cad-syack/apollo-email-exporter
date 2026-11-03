# Apollo Email Exporter

Python tool (CLI + Tkinter desktop GUI) that exports the emails of your saved contacts from [Apollo.io](https://apollo.io) using Apollo's **official API**. No web scraping.

## Features
- Pages through all saved contacts (100 per request) via the Apollo Contacts Search API.
- De-duplicates emails and writes them one per line to a text file.
- **Only new contacts** mode: appends to an existing file and skips emails already in it.
- Automatic exponential backoff on rate limits (HTTP 429).
- GUI with start/stop, live progress, masked API key field and optional "remember key" setting.
- Packaged as a standalone Windows `.exe` with PyInstaller.

## Usage
```bash
pip install -r requirements.txt
python apollo_gui.py
```
Or from the command line (PowerShell):
```powershell
$env:APOLLO_API_KEY = "your_key"
python apollo_emails.py
```

## Build the .exe
```bash
pip install pyinstaller
pyinstaller ApolloEmailExporter.spec
```

> Your API key is never stored in the repository. Keep it in an environment variable or the app's local settings.
