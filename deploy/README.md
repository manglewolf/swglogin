SWGLogin deployment notes
=========================

This folder contains example deployment files and instructions.

Files
-----
- `swglogin.service` - systemd unit file to run the Flask app via gunicorn.
- `nginx_swglogin.conf` - example Nginx site config to reverse-proxy to gunicorn and serve static files.

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

2. Create the environment file `/etc/default/swglogin` with application secrets and optionally VENV_PATH:

```
# /etc/default/swglogin
FLASK_SECRET_KEY='replace-with-secure-random'
DB_HOST='127.0.0.1'
DB_NAME='swgusers'
DB_USER='swg'
DB_PASS='secret'
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
