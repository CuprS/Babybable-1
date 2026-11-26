# Babybabel

Care in every language: a marketplace connecting parents with tutors who provide childcare while
teaching a new language. Product scope and feature history: `memory/PRD.md`.

| Part | Stack | Folder |
| --- | --- | --- |
| API | FastAPI + MongoDB (Motor) | `backend/` |
| App (iOS / Android / web) | Expo + expo-router | `frontend/` |

## Backend layout

| File | What's in it |
| --- | --- |
| `server.py` | Builds the app: CORS, routers, startup/shutdown |
| `core.py` | Config, database, auth helpers, time zones, slot/overlap checks, notifications + push |
| `models.py` | Request/response shapes |
| `storage.py` | Uploaded files: a local folder or any S3-compatible bucket |
| `email_service.py` | Outgoing email through Resend or SMTP, with a content safety check |
| `booking_service.py` | Payment intents, cancellation and refund policy |
| `workers.py` | Background jobs that run every minute (see below) |
| `seed.py` | Indexes, sample data, migrations |
| `routes/*.py` | One file per area: `auth`, `tutors`, `bookings`, `messages`, `reviews`, `parents`, `notifications`, `uploads`, `admin`, `seo`, `blog`, `w9`, `blocks` |

## How bookings work

1. A parent picks a slot. Overlapping sessions are refused, and a unique database key on
   tutor + date + start time stops two people grabbing the same slot at the same moment.
2. They pay. An unpaid booking frees the slot after 30 minutes.
3. The tutor accepts or declines within 24 hours. A decline, or no answer, refunds the parent in full.
   Bookings made from a tutor's own invitation count as already accepted.
4. Either side can **reschedule** up to 24 hours before the start, or **cancel**. A parent who
   cancels at least 24 hours ahead, or any booking the tutor cancels, is refunded in full. Later
   parent cancellations aren't refunded. You can change all of these times in `.env`.
5. All times are the **tutor's local time** (their `timezone`). The app labels them when the
   viewer is in another zone, and reminders go out at the right moment.

**Background jobs** (`workers.py`, every minute): release unpaid slots, expire unanswered
requests, send morning-of / starting-soon / review reminders (including as push notifications),
and purge W-9s past their retention date.

## Accounts and safety

- **Email verification:** new accounts get a 6-digit code. Set `REQUIRE_EMAIL_VERIFICATION=true`
  to make it mandatory before booking, messaging or posting.
- **Password reset:** "Forgot password?" on the login screen emails a 6-digit code. Codes expire
  after 15 minutes and lock after 5 wrong tries. Resetting signs out every other session.
- **Tutor verification (required):** tutors upload a photo ID and a background-check certificate,
  and an admin approves them on the Admin page. Until then they don't appear in search, on the
  map or in share links, can't be booked, and can't send lesson offers. Verified tutors show a ✔ Verified badge.
  ID documents are visible only to the tutor and admins. This is a manual review: plugging in an
  automated provider (Checkr, Certn, a DBS umbrella body…) means replacing the upload step in
  `routes/tutors.py` with that provider's API and webhook.
- **Sign-in on the website** is kept in a secure cookie that page scripts can't read (not in
  browser storage), and changes need a security header, so other sites can't act as the user. The
  phone apps keep their sign-in in the device's secure storage. **Sign out on all devices** (Profile)
  ends every session at once, e.g. after a lost phone.
- **Content-Security-Policy:** the website only runs scripts it serves itself (`deploy/Caddyfile`),
  so injected scripts are blocked. The map uses a copy of Leaflet hosted on the site
  (`public/map.html`, copied in by `yarn install`). Adding a third-party script (e.g. Stripe's
  payment form) means adding its domains to that policy.
- **Deleting an account** removes the person, their messages, photos and push tokens, and cancels
  upcoming sessions. Past bookings and reviews stay, without the name, for the other side's
  history and for accounting. W-9s are kept (still encrypted) for `W9_RETENTION_DAYS` (4 years),
  then purged.

## File storage

Profile photos, accreditation documents and ID checks are stored by `storage.py`:

- `STORAGE_BACKEND=local` (default): files go in `backend/data/uploads` (or `STORAGE_DIR`).
  This is simplest, but the server needs a persistent disk, and you have to back that folder up yourself.
- `STORAGE_BACKEND=s3`: any S3-compatible bucket. Set `S3_BUCKET`, plus `S3_ENDPOINT_URL` for
  non-AWS providers (Cloudflare R2, Backblaze B2, MinIO, DigitalOcean Spaces), and the
  `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` for that bucket. Keep the bucket private: files
  are always served through the API, which checks who may see them.

## Email

Safety alerts and verification / reset codes go out through `email_service.py`:

- `EMAIL_PROVIDER=resend` with `RESEND_API_KEY`, or
- `EMAIL_PROVIDER=smtp` with `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`
  (Amazon SES, Postmark, Mailgun, Google Workspace…).

Either way, set `EMAIL_FROM` to a sender your provider has verified, e.g. `Babybabel <hello@yourdomain.com>`.
With no provider set, nothing is sent and the server logs a warning. For local development,
`DEV_LOG_EMAIL_CODES=true` prints the 6-digit codes to the log instead.

## Keeping data minimal

The app stores only what it needs, in one MongoDB database, and deletes the rest automatically
(hourly, in `workers.py`):

| What | Kept for | Setting |
| --- | --- | --- |
| Usage stats (anonymous: no user id, name or other ids) | 90 days | `EVENT_RETENTION_DAYS` |
| Notifications | 90 days | `NOTIFICATION_RETENTION_DAYS` |
| Push tokens not refreshed | 180 days | `PUSH_TOKEN_RETENTION_DAYS` |
| Uploaded files nothing uses (replaced photos, abandoned uploads) | 24 hours | `ORPHAN_UPLOAD_HOURS` |
| Verification / reset codes | until they expire (15 min) | |
| Emails that could never be delivered | after 30 attempts | |
| W-9s of deleted tutors | 4 years (legal requirement) | `W9_RETENTION_DAYS` |

## Push notifications

The app registers each phone with Expo's push service after sign-in. The server sends a push
with every in-app notification, and tapping one opens the right booking or chat. You need:

1. An EAS project: `cd frontend && npx eas init`, which adds `extra.eas.projectId` to `app.json`.
2. A development or production build (`npx eas build`). Expo Go and simulators can't receive pushes.
3. For Android, FCM credentials uploaded with `npx eas credentials`; for iOS, EAS sets up APNs.

On web, the in-app feed still updates every 30 seconds.

## Search engines and link previews

The web app renders in the browser, so crawlers see little. The API serves real HTML for public
pages (title, description, preview image, readable text), and redirects people on to the app:

- `/api/share/tutor/{id}`, `/api/share/blog/{id}`: share these links on social media / chat
- `/api/seo/sitemap.xml`: submit it in Google Search Console and Bing Webmaster Tools

Set `PUBLIC_WEB_URL` so the links in them are absolute.

## Run locally

You need Python 3.12 and Node 22. Nothing else: no MongoDB, Docker or cloud accounts.

**Backend** (http://127.0.0.1:8001)

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python run_dev.py
```

`run_dev.py` starts the API with development defaults:

- **Database:** a local stand-in saved to `backend/data/dev-db.json`, so data survives restarts.
  Delete that file to start fresh.
- **Uploads:** stored in `backend/data/uploads`.
- **Email:** nothing is sent; verification and reset codes are printed in the terminal.
- **Logins:** admin `admin@example.com` (password `admin-pass-123`). The database starts empty.
  To try booking quickly, set `SEED_SAMPLE_TUTORS=true` for two verified sample tutors
  (`sofia@babybabel.dev` / `marie@babybabel.dev`, password `password123`); remove it to delete them again.

Anything in `backend/.env` overrides these defaults. For a real database, set `MONGO_URL`
to a MongoDB connection string (local MongoDB, or a free MongoDB Atlas cluster).

**Frontend** (http://localhost:8081)

```bash
cd frontend
yarn install
npx expo start          # then press w for web, or scan the QR code with Expo Go
```

`frontend/.env.development` already points the app at the local API (`EXPO_PUBLIC_BACKEND_URL`)
and sets `EXPO_PUBLIC_WEB_URL`, the web-app address used by "Open the web app" in the phone apps.

## Deploying

**Step-by-step for a Hetzner server (Docker Compose, automatic HTTPS, nightly backups): see
[`deploy/README.md`](deploy/README.md).** The notes below apply to any host.

The API is a standard FastAPI app, `uvicorn server:app --host 0.0.0.0 --port 8001`, and runs on
any host that runs Python: a VPS, Render, Railway, Fly.io, AWS and so on. In production set at least:

- `MONGO_URL`: a real MongoDB, e.g. MongoDB Atlas. The `memory://` dev database isn't for production.
- `JWT_SECRET`, `ADMIN_EMAIL` / `ADMIN_INITIAL_PASSWORD`, `PUBLIC_WEB_URL` / `CORS_ORIGINS`.
- Storage and email, as described above.

Build the web app with `npx expo export --platform web` (static files in `frontend/dist`, served
by any static host) and the phone apps with `npx eas build`. Set `EXPO_PUBLIC_BACKEND_URL` to
your API's public address for both.

## Tests

| Suite | Needs | Run |
| --- | --- | --- |
| `backend/tests_inprocess/` | nothing: in-memory database | `cd backend && pytest tests_inprocess` |
| `backend/tests/` | a running server + its MongoDB | start the API with `SEED_TUTOR_PASSWORD=password123`, then `EXPO_PUBLIC_BACKEND_URL=http://localhost:8001 pytest tests` |
| frontend | Node 20 | `cd frontend && yarn typecheck && yarn lint` |

A few integration tests restart the API (to reload `.env` or clear rate limits). Set
`BACKEND_RESTART_CMD` to whatever restarts your server (e.g. `docker compose restart api` or
`systemctl restart babybabel`). Without it, those tests are skipped.

The integration suites create and delete real accounts, so they refuse to run against anything
but localhost unless you set `ALLOW_REMOTE_TESTS=1`.

**CI** (`.github/workflows/ci.yml`) runs the in-process tests, a lint and the frontend
type-check/lint on every push and pull request. The integration suites run on demand ("Run
workflow" → tick *integration*).

## Before going live

- Payments use Stripe and are **mocked for now** (`ENABLE_MOCK_CONFIRM=true`, Stripe keys empty):
  no card is charged and anyone can mark their own booking paid, so treat it as a pilot. When
  real payments are built, set `STRIPE_API_KEY` + `STRIPE_WEBHOOK_SECRET` and `ENABLE_MOCK_CONFIRM=false`.
- Leave `SEED_TUTOR_PASSWORD` empty. On a database created before this change, reset the
  passwords of `sofia@babybabel.dev` / `marie@babybabel.dev` (they used `password123`), or delete them.
- Set `W9_ENCRYPTION_KEYS`; without it W-9 TINs are encrypted with a key that is lost on restart.
- Set `ADMIN_EMAIL`, `PUBLIC_WEB_URL` (also allowed through CORS), and an email provider
  (verification and reset codes are sent by email).
- Choose file storage: `STORAGE_BACKEND=s3` with a private bucket, or `local` on a server whose
  disk survives restarts and is backed up.
- The app ids are `com.babybabel.app` (iOS and Android) and the link scheme is `babybabel://`.
  Change them in `frontend/app.json` before your first store release if you want different ones.
- The rate limiter is in memory per process: if you run several API workers, move it to Redis.
