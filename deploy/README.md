# Hosting Babybabel on Hetzner

Everything runs on **one Hetzner Cloud server** with Docker Compose:

| Container | What it does | Reachable from the internet? |
| --- | --- | --- |
| `web` (Caddy) | Serves the website, gets free HTTPS certificates automatically, forwards `/api` to the API | Yes: ports 80 and 443 |
| `api` | The FastAPI backend | No, only through Caddy |
| `mongo` | MongoDB database | No |

The site and the API share one address: `https://yourdomain` and `https://yourdomain/api`.

**Rough monthly cost** (check Hetzner's current prices): a CX22 server is about €4–5, Hetzner's
own server backups add about 20%, and Object Storage, if you use it, is about €5 for the first TB.
Resend's free plan covers 3,000 emails a month.

---

## 1. Before you start

You need:

1. **A Hetzner account**: [console.hetzner.com](https://console.hetzner.com).
2. **A domain**, e.g. `babybabel.com`, from any registrar. You'll add one DNS record.
3. **An SSH key** on your computer. In PowerShell:

   ```powershell
   ssh-keygen -t ed25519 -C "babybabel-server"
   ```

   Press Enter to accept the defaults; choosing a passphrase is recommended. Your public key is
   then in `C:\Users\<you>\.ssh\id_ed25519.pub`.

## 2. Create the server

In the Hetzner Console:

1. **New project** → name it `Babybabel`.
2. **Security → SSH keys → Add SSH key**: paste the contents of `id_ed25519.pub`.
3. **Firewalls → Create firewall** named `babybabel-web` with these *inbound* rules:
   TCP 22 (SSH), TCP 80, TCP 443, UDP 443, and ICMP. This is a second layer on top of the
   firewall `setup.sh` turns on inside the server.
4. **Servers → Add server**:
   - **Location**: closest to your families (Falkenstein / Nuremberg / Helsinki for Europe,
     Ashburn / Hillsboro for the US).
   - **Image**: Ubuntu 24.04.
   - **Type**: shared vCPU, x86 → **CX22** (2 vCPU, 4 GB RAM). You can resize later.
   - **Networking**: public IPv4 and IPv6.
   - **SSH keys**: select yours. Password login is then disabled, which is what you want.
   - **Firewalls**: select `babybabel-web`.
   - **Backups**: turn on. Hetzner keeps 7 daily snapshots of the whole server.
   - **Name**: `babybabel-prod`.
5. Note the server's **IPv4 address**.

## 3. Point your domain at it

At your domain registrar's DNS settings, add an **A record**: name `@` (or a subdomain like
`app`), value = the server's IPv4 address. Optionally add an **AAAA record** with its IPv6 address.
DNS changes usually take a few minutes, but can take up to a few hours.

## 4. Install Babybabel

From PowerShell on your computer:

```powershell
ssh root@YOUR_SERVER_IP
```

Then, on the server:

```bash
curl -fsSL https://raw.githubusercontent.com/CuprS/Babybable-1/main/deploy/setup.sh -o setup.sh
less setup.sh            # read what it does (q to quit)
bash setup.sh babybabel.com you@example.com
```

Use your own domain and email. The script:

- updates Ubuntu, turns on automatic security updates, a firewall and fail2ban, and adds swap
- installs Docker from Docker's official repository
- clones the app to `/opt/babybabel`
- writes `deploy/.env` with freshly generated database passwords, app secret, W-9 encryption key
  and admin password
- builds and starts everything (the first build takes 5–10 minutes)
- schedules a nightly database backup.

At the end it prints your **admin password**: save it in a password manager. Then open
`https://yourdomain`. The HTTPS certificate is issued in the first minute after DNS points to the server.

## 5. Turn on email (needed for sign-up codes and password resets)

New accounts must confirm their email (`REQUIRE_EMAIL_VERIFICATION=true`), so set this up before
inviting anyone.

1. Create a free account at [resend.com](https://resend.com) → **Domains → Add domain** → add the
   DNS records it shows to your domain, and wait until it says *Verified*.
2. **API Keys → Create API key** with "Sending access".
3. On the server, edit the settings and apply them:

   ```bash
   nano /opt/babybabel/deploy/.env       # set RESEND_API_KEY=… and check EMAIL_FROM
   /opt/babybabel/deploy/update.sh
   ```

Any SMTP provider works instead (`EMAIL_PROVIDER=smtp`), but it must use port 587, because Hetzner
blocks outgoing ports 25 and 465 on new accounts.

To change the admin password, use **Forgot password** on the login screen once email works.

## 6. Optional: Hetzner Object Storage

Uploads start on the server's disk (`STORAGE_BACKEND=local`), and the nightly backup includes them.
To keep files off the server instead:

1. Hetzner Console → **Object Storage → Create bucket**: same location as the server, visibility **private**.
2. **Object Storage → S3 credentials → Generate**.
3. In `deploy/.env` set `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_ENDPOINT_URL`
   (e.g. `https://fsn1.your-objectstorage.com`), `S3_REGION`, `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY`, then run `update.sh`.

If people have already uploaded files, copy them to the bucket first:

```bash
export AWS_ACCESS_KEY_ID=your-key AWS_SECRET_ACCESS_KEY=your-secret
docker run --rm -v babybabel_uploads:/data:ro -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY amazon/aws-cli \
  --endpoint-url https://fsn1.your-objectstorage.com s3 sync /data/uploads s3://YOUR_BUCKET
```

**Off-site backups:** create a second private bucket and set `BACKUP_S3_BUCKET` to its name. Each
nightly backup is then copied there too, so a lost server doesn't mean lost data.

---

## Day to day

| Task | Command (on the server) |
| --- | --- |
| Deploy the latest code from GitHub | `/opt/babybabel/deploy/update.sh` (backs up first) |
| Apply changed settings in `deploy/.env` | `/opt/babybabel/deploy/update.sh` |
| See what's running | `cd /opt/babybabel/deploy && docker compose ps` |
| Follow the API's log | `cd /opt/babybabel/deploy && docker compose logs -f api` |
| Run a backup now | `/opt/babybabel/deploy/backup.sh` |
| See backups | `ls -lh /var/backups/babybabel` |

### Restoring a backup

Backups are encrypted. Decrypt the one you need first (the passphrase is
`BACKUP_ENCRYPTION_PASSPHRASE` in `deploy/.env`):

```bash
cd /var/backups/babybabel
export BACKUP_ENCRYPTION_PASSPHRASE='…'
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_ENCRYPTION_PASSPHRASE \n  -in db-YYYYMMDD-HHMMSS.archive.gz.enc -out db-YYYYMMDD-HHMMSS.archive.gz
```

Then restore it:

```bash
cd /opt/babybabel/deploy
# Database (replaces the current data):
docker compose exec -T mongo sh -c \
  'mongorestore --username root --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip --drop' \
  < /var/backups/babybabel/db-YYYYMMDD-HHMMSS.archive.gz
# Uploaded files (local storage only):
docker run --rm -v babybabel_uploads:/data -v /var/backups/babybabel:/in alpine \
  tar -xzf /in/uploads-YYYYMMDD-HHMMSS.tar.gz -C /data
```

## A staging server

Repeat these steps on a second CX22 (e.g. `staging.babybabel.com`) to try changes before they go
live. Payments are mocked on both servers until real Stripe payments are built.
To keep it private, add this inside the site block in `deploy/Caddyfile` on that server only,
using a hash from `docker compose exec web caddy hash-password`:

```
basic_auth {
	tester $2a$14$your-hash-here
}
```

## Security checklist

- [ ] SSH works with your key, and password login is off (the default when you choose an SSH key).
- [ ] Hetzner firewall attached; `ufw status` shows only 22, 80 and 443.
- [ ] Hetzner server backups on; `BACKUP_S3_BUCKET` set for off-site copies.
- [ ] `BACKUP_ENCRYPTION_PASSPHRASE` saved in your password manager (the nightly backups are
      encrypted with it; Hetzner's own server snapshots are not, so keep the Hetzner account
      protected with two-factor sign-in).
- [ ] Payments: while they're mocked (`ENABLE_MOCK_CONFIRM=true`, Stripe keys empty) no money
      moves, and anyone can mark their own booking paid. Tell testers it's a pilot. When real
      Stripe payments are built, add the keys and set `ENABLE_MOCK_CONFIRM=false`.
- [ ] `deploy/.env` stays on the server (it's git-ignored). Keep a copy of it in your password
      manager: without `W9_ENCRYPTION_KEYS`, stored tax IDs can't be decrypted.
- [ ] After deploying, open the site and check the browser console shows no
      "Content Security Policy" errors. When you add Stripe (or any outside script), add its
      domains to the policy in `deploy/Caddyfile` first.
- [ ] Terms and Privacy Policy reviewed by a lawyer before real families sign up.
