SWGLogin deployment notes
=========================

This folder contains example deployment files and instructions.

Files
-----
- `swglogin.service` - systemd unit file to run the Flask app via gunicorn.
- `nginx_swglogin.conf` - example Nginx site config to reverse-proxy to gunicorn and serve static files.
- `run_gunicorn.sh` - deployment script wrapping gunicorn (virtualenv activation, logs, tunables).

Quick setup
-----------
1. Copy the repo to the host (example path `/srv/swglogin`) and create a virtualenv there:

```bash
cd /srv
git clone <your-repo-url> swglogin
cd swglogin
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

2. Create the environment file `/etc/default/swglogin` with application secrets and optionally VENV_PATH. You can also control application logging here via `LOG_LEVEL`:

```
# /etc/default/swglogin
FLASK_SECRET_KEY='replace-with-secure-random'
DB_HOST='127.0.0.1'
DB_NAME='swgusers'
DB_USER='swg'
DB_PASS='secret'
# Application logging (defaults if omitted: LOG_LEVEL=ERROR, LOG_MAX_MB=10, LOG_BACKUP_COUNT=10)
LOG_LEVEL='ERROR'            # DEBUG | INFO | WARNING | ERROR | CRITICAL
LOG_MAX_MB='10'              # per-file size before rotation
LOG_BACKUP_COUNT='10'        # number of rotated files to keep
# Optional: point to your virtualenv location (recommended)
VENV_PATH=/srv/swglogin/.venv
```

3. Install the systemd unit and start the service:

```bash
sudo cp deploy/swglogin.service /etc/systemd/system/swglogin.service
sudo systemctl daemon-reload
sudo systemctl enable --now swglogin.service
sudo journalctl -u swglogin -f
```

4. Configure Nginx (optional)

```bash
sudo cp deploy/nginx_swglogin.conf /etc/nginx/sites-available/swglogin
sudo ln -s /etc/nginx/sites-available/swglogin /etc/nginx/sites-enabled/swglogin
sudo nginx -t
sudo systemctl reload nginx
```

Notes
-----
- The systemd service uses `VENV_PATH` from `/etc/default/swglogin` if provided; otherwise it will use the system `gunicorn` found in PATH.
- For production, run the service under a dedicated, non-root user and secure the environment file (e.g. `chmod 640 /etc/default/swglogin`).
- Consider fronting the app with Nginx and enabling TLS (Let's Encrypt) for secure connections.
 - You can override run-time settings without editing the unit using `systemctl set-environment` or a drop-in.
 - The application log file is written to `logs/auth.log` (rotated). Control verbosity via `LOG_LEVEL` as above.
 
Local development (Windows PowerShell)
-------------------------------------
```powershell
cd swglogin
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FLASK_SECRET_KEY = "dev_local_secret_change_me"
python app.py  # Runs Flask dev server (debug=True currently)
```

Gunicorn script usage (Linux)
-----------------------------
The `deploy/run_gunicorn.sh` script centralizes production settings:
```bash
chmod +x deploy/run_gunicorn.sh
WORKERS=4 BIND_ADDRESS=127.0.0.1:8000 LOG_LEVEL=info ./deploy/run_gunicorn.sh
```
Environment variables (defaults shown):
```
APP_DIR=/srv/swglogin
VENV_PATH=/srv/swglogin/venv
BIND_ADDRESS=127.0.0.1:8000
WORKERS=4
WORKER_CLASS=sync
TIMEOUT=120
LOG_LEVEL=info
```

Logging levels: Gunicorn vs App
-------------------------------
- `LOG_LEVEL` in the Gunicorn script controls Gunicorn's own logs (workers, requests) written to `logs/gunicorn-*.log`.
- `LOG_LEVEL` in the application environment controls the Flask app logger (`swglogin`), written to `logs/auth.log` (rotated).

Examples:
```bash
# Set Gunicorn verbosity only
LOG_LEVEL=warning ./deploy/run_gunicorn.sh

# Set application verbosity via systemd environment
sudo systemctl set-environment LOG_LEVEL=ERROR   # app logger level
sudo systemctl restart swglogin.service

# Or persist in /etc/default/swglogin (managed by Ansible/template)
LOG_LEVEL='ERROR'            # app logger level
LOG_MAX_MB='10'
LOG_BACKUP_COUNT='10'
```

Systemd + overrides
-------------------
The unit now calls the script directly:
```
ExecStart=/srv/swglogin/deploy/run_gunicorn.sh
```
Set temporary overrides (persist until daemon reload or unset):
```bash
sudo systemctl set-environment WORKERS=6 LOG_LEVEL=warning BIND_ADDRESS=127.0.0.1:9000
# App logging level (controls Flask app logger)
sudo systemctl set-environment LOG_LEVEL=INFO
sudo systemctl restart swglogin.service
```
Show current environment overrides:
```bash
systemctl show swglogin.service | grep Environment=
```
Clear overrides:
```bash
sudo systemctl unset-environment WORKERS LOG_LEVEL BIND_ADDRESS
sudo systemctl restart swglogin.service
```
 
Drop-in overrides and service-user setup
---------------------------------------

Systemd drop-ins let you override environment variables and service options without editing the main unit file. Copy the example drop-in to `/etc/systemd/system/swglogin.service.d/override.conf` and edit it there:

```bash
sudo mkdir -p /etc/systemd/system/swglogin.service.d
sudo cp deploy/swglogin.service.d/override.conf /etc/systemd/system/swglogin.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart swglogin.service
```

Use the drop-in to set `VENV_PATH`, `FLASK_SECRET_KEY`, `DB_*` variables, or change `User`/`Group` without touching the upstream `swglogin.service` unit.

Service user and permissions (sample)
------------------------------------

A small helper script `deploy/create_service_user.sh` is included as an example to create a dedicated service user, create the application directory, and set secure permissions. It demonstrates commands such as:

```bash
sudo groupadd --force swglogin
sudo useradd --system --group swglogin --no-create-home --shell /usr/sbin/nologin --comment "SWG Login service" swglogin
sudo mkdir -p /srv/swglogin
sudo chown -R swglogin:swglogin /srv/swglogin
sudo chmod -R 750 /srv/swglogin
```

The script also creates a placeholder `/etc/default/swglogin` and sets `chmod 640` on it so only root and the service group can read it. Review the script before running in production and adjust paths, user/group names, and permission policy to match your site's security policies.

If you'd like, I can also add an Ansible playbook or a more complete system provisioning script that includes virtualenv creation, pip installs, and service start/monitoring.

Hardening / Next Steps
----------------------
- **CSRF Protection**: Integrate Flask-WTF or custom token for all modifying POST forms.
- **Password Hash Migration**: Transition from legacy SHA1+salt to bcrypt or Argon2 (store versioned hashes; rehash on login).
- **Session Security**: Set `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `PERMANENT_SESSION_LIFETIME`; consider server-side session storage (Redis).
- **Rate Limiter Backend**: Switch `storage_uri` to Redis (`redis://host:port/0`) for multi-process resilience.
- **Structured Logging**: Output JSON (e.g. via `python-json-logger`) and ship to a log aggregation service.
- **Monitoring**: Add health endpoint, Prometheus metrics, uptime checks.
- **Database Pooling**: Use connection pooling or a library wrapper to reduce connect overhead.
- **Content Security Policy (CSP)**: Add headers via Nginx or Flask to mitigate XSS.
- **Automated TLS**: Integrate Certbot + renewal timer for Nginx.

