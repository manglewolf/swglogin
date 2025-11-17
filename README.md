Flask conversion of `swglogin`

Quick start (PowerShell):

1. Create a virtual environment and activate it:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Set up environment variables (optional but recommended):

```powershell
# Copy the example env file
Copy-Item .env.example .env
# Edit .env with your values
notepad .env
```

4. Run the app:

```powershell
python app.py
```

The swglogin will be available at http://127.0.0.1:5000/

Notes:
- This is a minimal translation of the HTML form to a Flask route. The server-side code currently performs only basic validation and does not create database records or hash passwords. Replace `app.secret_key` with a secure secret and implement proper DB logic before using in production.

Environment variables
- It's recommended to put secrets and DB credentials in environment variables instead of source.
- **Option 1: Use a `.env` file** (recommended for local development):
  - Copy `.env.example` to `.env` and fill in your values
  - The app automatically loads `.env` if `python-dotenv` is installed
  - Never commit `.env` to version control (already in `.gitignore`)
- **Option 2: Set variables in your shell session** (see PowerShell example below)
- The app reads the following env vars (falling back to sensible defaults for development):
	- `FLASK_SECRET_KEY` - secret used by Flask sessions
	- `DB_HOST` - database host (default: 127.0.0.1)
	- `DB_NAME` - database name (default: swgusers)
	- `DB_USER` - database username (default: root)
	- `DB_PASS` - database password (default: swg)
	- `LOG_MAX_MB` - max log file size in MB before rotation (default: 10)
	- `LOG_BACKUP_COUNT` - number of rotated log files to keep (default: 10)
	- `LOG_LEVEL` - logging level for the app (default: ERROR). Accepted values: DEBUG, INFO, WARNING, ERROR, CRITICAL

PowerShell example (set variables for current session):

```powershell
$env:FLASK_SECRET_KEY = 'replace-with-a-strong-secret'
$env:DB_HOST = '127.0.0.1'
$env:DB_NAME = 'swgusers'
$env:DB_USER = 'swg'
$env:DB_PASS = 'Enterprise1701!'
$env:LOG_MAX_MB = '20'  # 20 MB
$env:LOG_BACKUP_COUNT = '30'
$env:LOG_LEVEL = 'WARNING'
python app.py
```

For production, prefer setting these in your host/service config or a secrets manager.
