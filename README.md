Flask conversion of `addnewuser.php`

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

3. Run the app:

```powershell
python app.py
```

The add-new-user form will be available at http://127.0.0.1:5000/addnewuser

Notes:
- This is a minimal translation of the HTML form to a Flask route. The server-side code currently performs only basic validation and does not create database records or hash passwords. Replace `app.secret_key` with a secure secret and implement proper DB logic before using in production.

Environment variables
- It's recommended to put secrets and DB credentials in environment variables instead of source.
- The app reads the following env vars (falling back to sensible defaults for development):
	- `FLASK_SECRET_KEY` - secret used by Flask sessions
	- `DB_HOST` - database host (default: 127.0.0.1)
	- `DB_NAME` - database name (default: swgusers)
	- `DB_USER` - database username (default: root)
	- `DB_PASS` - database password (default: swg)

PowerShell example (set variables for current session):

```powershell
$env:FLASK_SECRET_KEY = 'replace-with-a-strong-secret'
$env:DB_HOST = '127.0.0.1'
$env:DB_NAME = 'swgusers'
$env:DB_USER = 'swg'
$env:DB_PASS = 'Enterprise1701!'
python app.py
```

For production, prefer setting these in your host/service config or a secrets manager.
