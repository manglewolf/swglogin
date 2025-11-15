#!/usr/bin/env bash
# Sample commands to create a service user, directories, and set permissions
# Run these on the server (example for Debian/Ubuntu). Adjust paths and names to suit your environment.

set -euo pipefail

SERVICE_USER=swglogin
SERVICE_GROUP=swglogin
APP_DIR=/srv/swglogin
ENV_FILE=/etc/default/swglogin
UNIT_DIR=/etc/systemd/system

echo "Creating service user and group: $SERVICE_USER"
sudo groupadd --force "$SERVICE_GROUP"
# Create a system user with no login shell and home at the app dir
sudo useradd --system --group "$SERVICE_GROUP" --no-create-home --shell /usr/sbin/nologin --comment "SWG Login service" "$SERVICE_USER" || true

echo "Creating application directory: $APP_DIR"
sudo mkdir -p "$APP_DIR"
# If your app source will be deployed under $APP_DIR, copy or git-clone it as a privileged step
# chown the directory to the service user so the service (and deploy scripts) can access it
sudo chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$APP_DIR"
sudo chmod -R 750 "$APP_DIR"

# Example location for environment file used by systemd unit
echo "Creating environment file placeholder: $ENV_FILE"
sudo tee "$ENV_FILE" > /dev/null <<'EOF'
# /etc/default/swglogin
# Example environment file consumed by the systemd unit (EnvironmentFile=/etc/default/swglogin)
# Do NOT make this file world-readable if it contains secrets.
# VENV_PATH=/srv/swglogin/venv
# FLASK_SECRET_KEY=replace-with-a-strong-random-value
# DB_HOST=127.0.0.1
# DB_USER=swglogin
# DB_PASS=your_db_password_here
EOF

sudo chown root:"$SERVICE_GROUP" "$ENV_FILE"
sudo chmod 640 "$ENV_FILE"

# If creating a virtualenv, ensure its files are readable/executable by the service user
echo "If you create a virtualenv at /srv/swglogin/venv, ensure the service user owns it or has access. Example:"
echo "  sudo chown -R $SERVICE_USER:$SERVICE_GROUP /srv/swglogin/venv"

# Reload systemd daemon and enable service (adjust service unit name if different)
echo "Reloading systemd and enabling service (does not start it yet):"
sudo systemctl daemon-reload
sudo systemctl enable swglogin.service

echo "Done. You can now start the service with: sudo systemctl start swglogin.service"

# Note: This script is an example. Review each command before running in production.
