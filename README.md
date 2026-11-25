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
- **Tutor verification:** tutors upload a photo ID and a background-check certificate. An admin
  approves them on the Admin page, and families see a ✔ Verified badge and can filter by it.
  ID documents are visible only to the tutor and admins. This is a manual review: plugging in an
  automated provider (Checkr, Certn, a DBS umbrella body…) means replacing the upload step in
  `routes/tutors.py` with that provider's API and webhook.
- **Deleting an account** removes the person, their messages, photos and push tokens, and cancels
  upcoming sessions. Past bookings and reviews stay, without the name, for the other side's
  history and for accounting. W-9s are kept (still encrypted) for `W9_RETENTION_DAYS` (4 years),
  then purged.

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

**Backend**

```bash
cd backend
cp .env.example .env          # fill in MONGO_URL, DB_NAME, JWT_SECRET (32+ chars), ADMIN_* …
pip install -r requirements-dev.txt
uvicorn server:app --reload --port 8001
```

**Frontend**

```bash
cd frontend
yarn install
EXPO_PUBLIC_BACKEND_URL=http://localhost:8001 npx expo start
```

## Tests

| Suite | Needs | Run |
| --- | --- | --- |
| `backend/tests_inprocess/` | nothing: in-memory database | `cd backend && pytest tests_inprocess` |
| `backend/tests/` | a running server + its MongoDB | start the API with `SEED_TUTOR_PASSWORD=password123`, then `EXPO_PUBLIC_BACKEND_URL=http://localhost:8001 pytest tests` |
| frontend | Node 20 | `cd frontend && yarn typecheck && yarn lint` |

The integration suites create and delete real accounts, so they refuse to run against anything
but localhost unless you set `ALLOW_REMOTE_TESTS=1`.

**CI** (`.github/workflows/ci.yml`) runs the in-process tests, a lint and the frontend
type-check/lint on every push and pull request. The integration suites run on demand ("Run
workflow" → tick *integration*).

## Before going live

- `ENABLE_MOCK_CONFIRM=false` (otherwise anyone can mark a booking paid), and set
  `STRIPE_API_KEY` + `STRIPE_WEBHOOK_SECRET`.
- Leave `SEED_TUTOR_PASSWORD` empty. On a database created before this change, reset the
  passwords of `sofia@babybabel.dev` / `marie@babybabel.dev` (they used `password123`), or delete them.
- Set `W9_ENCRYPTION_KEYS`; without it W-9 TINs are encrypted with a key that is lost on restart.
- Set `ADMIN_EMAIL`, `PUBLIC_WEB_URL`, and the email keys (verification and reset codes are sent by email).
- The rate limiter is in memory per process: if you run several API workers, move it to Redis.
