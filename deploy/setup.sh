#!/usr/bin/env bash
# One-time setup of a fresh Hetzner Cloud server (Ubuntu 24.04), run as root:
#
#   curl -fsSL https://raw.githubusercontent.com/CuprS/Babybable-1/main/deploy/setup.sh -o setup.sh
#   less setup.sh                                  # read it first
#   bash setup.sh babybabel.com you@example.com
#
# It hardens the server (firewall, automatic security updates, fail2ban, swap), installs Docker,
# clones the app to /opt/babybabel, generates all secrets into deploy/.env, starts everything and
# schedules nightly backups. Safe to run again: it never overwrites an existing deploy/.env.
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
REPO_URL="${REPO_URL:-https://github.com/CuprS/Babybable-1.git}"
APP_DIR="${APP_DIR:-/opt/babybabel}"

if [[ $EUID -ne 0 ]]; then echo "Run as root (sudo bash setup.sh ...)"; exit 1; fi
if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
  echo "Usage: bash setup.sh <domain> <your-email>"; exit 1
fi

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

say "Updating the system"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl git ufw fail2ban unattended-upgrades openssl dnsutils

say "Turning on automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades

say "Firewall: allow SSH, HTTP and HTTPS only"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
systemctl enable --now fail2ban

if ! swapon --show | grep -q .; then
  say "Adding 2 GB swap (helps the website build on small servers)"
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if ! command -v docker >/dev/null; then
  say "Installing Docker from Docker's official repository"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

say "Getting the app"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR/deploy"

if [[ ! -f .env ]]; then
  say "Creating deploy/.env with fresh secrets"
  rand_hex() { openssl rand -hex "$1"; }
  fernet_key() { openssl rand -base64 32 | tr '+/' '-_'; }
  cp .env.example .env
  chmod 600 .env
  set_var() { sed -i "s#^$1=.*#$1=$2#" .env; }
  set_var DOMAIN "$DOMAIN"
  set_var ACME_EMAIL "$EMAIL"
  set_var ADMIN_EMAIL "$EMAIL"
  set_var MONGO_ROOT_PASSWORD "$(rand_hex 24)"
  set_var MONGO_APP_PASSWORD "$(rand_hex 24)"
  set_var JWT_SECRET "$(rand_hex 32)"
  set_var W9_ENCRYPTION_KEYS "$(fernet_key)"
  BACKUP_PASS="$(rand_hex 32)"
  set_var BACKUP_ENCRYPTION_PASSPHRASE "$BACKUP_PASS"
  ADMIN_PW="$(rand_hex 12)"
  set_var ADMIN_INITIAL_PASSWORD "$ADMIN_PW"
  set_var EMAIL_FROM "Babybabel <hello@${DOMAIN}>"
  set_var SAFETY_ALERT_EMAIL "$EMAIL"
  NEW_ENV=1
else
  say "Keeping the existing deploy/.env"
  NEW_ENV=0
fi

say "Checking DNS for $DOMAIN"
SERVER_IP="$(curl -fsS4 https://api.ipify.org || true)"
DNS_IP="$(dig +short A "$DOMAIN" | tail -n1 || true)"
if [[ -n "$SERVER_IP" && "$DNS_IP" != "$SERVER_IP" ]]; then
  echo "  Warning: $DOMAIN points to '${DNS_IP:-nothing}', but this server is $SERVER_IP."
  echo "  HTTPS certificates will fail until the DNS A record points here. Continuing anyway."
fi

say "Building and starting Babybabel (the first build takes several minutes)"
docker compose up -d --build

say "Scheduling nightly backups (03:30)"
cat > /etc/cron.d/babybabel-backup <<CRON
SHELL=/bin/bash
30 3 * * * root $APP_DIR/deploy/backup.sh >> /var/log/babybabel-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/babybabel-backup
chmod +x "$APP_DIR/deploy/"*.sh

say "Done"
echo "  Site:   https://$DOMAIN  (allow a minute for the HTTPS certificate)"
echo "  Status: cd $APP_DIR/deploy && docker compose ps"
if [[ "$NEW_ENV" == 1 ]]; then
  echo
  echo "  Admin login: $EMAIL"
  echo "  Admin password: $ADMIN_PW"
  echo "  Save it in a password manager. To change it later, use Forgot password once email is set up."
  echo
  echo "  Backup encryption passphrase: $BACKUP_PASS"
  echo "  Save it too — backups can't be restored without it. (Also in deploy/.env.)"
  echo
  echo "  Next: add your email provider (RESEND_API_KEY) and, if you want, Hetzner Object Storage"
  echo "  keys to $APP_DIR/deploy/.env, then run: $APP_DIR/deploy/update.sh"
fi
