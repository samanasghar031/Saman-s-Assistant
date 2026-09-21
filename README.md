# Research Application Assistant

A Windows-oriented Python desktop application for evidence-based PhD opportunity checking, professor verification, tailored-CV preparation, and human-reviewed Gmail draft creation.

The application does not send email automatically. It creates an unsent Gmail draft only after the user reviews the content and confirms the verified institutional address.

## Privacy and security

This repository intentionally excludes API keys, OAuth credentials, OAuth tokens, CVs, contact details, research documents, candidate records, generated drafts, and verification archives. Never commit those files. The included `.gitignore` protects the expected local filenames, but always inspect staged changes before pushing.

If a key or token is ever committed, remove it from the repository history and revoke or rotate it immediately.

## Requirements

- Python 3.11 or newer
- Tkinter (normally included with Windows Python)
- A Google AI API key for workflows that use Gemini
- A Google OAuth desktop client with the Gmail Compose scope for Gmail draft creation

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Add your own API key to `.env`. For Gmail draft creation, download your own Google OAuth desktop-client configuration and save it locally as `credentials.json`. Do not share that file.

## Run

```powershell
python desktop_app.py
```

Follow the stages in order:

1. Import and approve applicant research evidence.
2. Check an official opportunity using official institutional sources.
3. Verify the professor, research fit, institutional email, and authored publications.
4. Create and review a separate tailored CV.
5. Create and review an unsent Gmail draft.

## Important limitations

- Web pages and admissions information can change; review every generated report.
- Publication, recruitment, deadline, and contact claims must be checked before use.
- Generated CVs and emails require human review.
- Each user must supply their own documents, API key, and OAuth configuration.

