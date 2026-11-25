# Babybabel — Product Requirements

**Tagline:** Care in every language — Airbnb-style marketplace connecting parents with tutors who provide childcare while teaching a new language.

## Users
- **Parents** — browse/search tutors, view profiles, book sessions, chat, review, favourite tutors, edit family profile with up to 10 children.
- **Tutors** — publish a profile, receive bookings, chat, view earnings.
- **Everyone (logged out too)** — marketing surface via side drawer.

## MVP feature checklist
- [x] Email/password auth (JWT + bcrypt) with role.
- [x] Onboarding + Airbnb-style hero + role picker.
- [x] Discover: **debounced search (300 ms)**, **count badge**, **language flag chips** (🇪🇸 🇫🇷 🇯🇵 …).
- [x] Tutor cards with **favourite heart**, **"New tutor"** flag when profile is incomplete.
- [x] Tutor detail: hero, quick stats, flag-language chips, bio, accreditations, reviews, sticky Book CTA.
- [x] Booking flow with Stripe (MOCKED confirmation).
- [x] Bookings list, in-app chat with polling, reviews with rolling average.
- [x] Tutor dashboard + Edit profile with photo uploads.
- [x] **Parent family profile** — parent avatar, up to 10 children (name/age/avatar), city, languages desired, hours/week (slider), learning materials.
- [x] **Profile picture uploads** on Profile tab (tap avatar) — works on native; on web now uses a real File object so `/api/uploads` receives bytes correctly.
- [x] **Toast system** — success/error/info toasts replace jarring Alert popups.
- [x] **Notifications** — in-app polling watcher; server generates:
  - chat message notifications
  - booking-confirmed notifications (parent + tutor)
  - **booking reminder 2 h before session**
  - **review request 30 min after session**
- [x] **Favourite tutors** — `POST/DELETE /api/favorites/{tutor_id}` + `GET /api/favorites`.
- [x] **Analytics** — client events (`track()` in `src/analytics.ts`) go to `POST /api/events` and are shown on the Admin page. *PostHog is not wired up* (an earlier note said it was; the packages were never installed). To add it, install `posthog-react-native` and forward from `track()`.
- [x] Global side drawer with 6 marketing landing pages + Download-the-app (web) + Privacy Policy.
- [x] Delete account (both roles) — cascades bookings, messages, uploads, reviews.
- [x] **Tutor contribution blog** — public `/blog` list + `/blog/[id]` (readable signed-out), tutor `/blog/compose` (title, topic, summary, body, up to 2 uploaded photos; first = cover) and `/blog/me` (In review / Published / Needs revisions + admin feedback, revise & resubmit). Admin "Blog submissions" panel in `/admin` (publish / reject with required note / unpublish). 4 editorial posts seeded. Backend in `backend/routes/blog.py`; W-9 routes moved to `backend/routes/w9.py`.
- [x] **Security hardening (audit follow-up)** — CORS limited to the app's own origins (`CORS_ORIGINS` / `CORS_ORIGIN_REGEX` env override); file downloads accept the Authorization header only (no `?token=`); family profile visible only to owner, admin, and tutors with a booking or a chat the family took part in, never exact coordinates for non-owners; message limits 20/min and 300/day per sender (text + invitations), max 10 new-family cold conversations per tutor per day, message text 1–4000 chars.
- [x] **User blocking** — block button in chat header, tutor profile and family profile opens `/block/[userId]`: pick a reason (spam, harassment, inappropriate, child safety, fake, other + details), tick "permanent" confirmation, block → success screen. Blocks are permanent and mutual: no messages/invitations/bookings/reviews, the conversation is hidden from both inboxes, the tutor disappears from the parent's search and map, and profiles return not found both ways. Admins can't be blocked; reasons are visible only on the Admin page ("Blocks & reports"). Backend in `backend/routes/blocks.py`.
- [x] **Safety automation** — (1) Block-evasion guard: blocks placed on a user survive account deletion (keyed by email fingerprint: lower-case, +tag stripped, SHA-256) and re-attach on re-signup; a paused account that's deleted stays paused when re-created (`db.account_tombstones`). (2) Child-safety block → instant email alert via Emergent-managed Resend (`backend/email_service.py`) to the address set on the Admin page (default `ADMIN_EMAIL` from `.env`, stored in `db.settings`). (3) Auto-pause: blocked by 3 different people → account paused (HTTP 423 on every call/login, hidden from search, app shows `/suspended`), admin emailed; Admin "Safety" panel lists paused accounts with Reinstate (only blocks after reinstatement count toward the next pause).




- [x] Seeded 2 sample tutors (Sofía García · Marie Dubois).
- [x] **Tutor weekly availability calendar** — tutors toggle hourly slots per weekday in Edit profile; booking flow and lesson-invitation composer automatically grey out unavailable or already-booked slots.
- [x] **Auth hardening (P3)** — signup/login rate limited per IP, generic duplicate-email response prevents enumeration, minimum password length 8.
- [x] **Interactive tutor map on Explore** — Leaflet + OpenStreetMap in a WebView (native) / iframe (web), tap any pin to open the tutor. No API key required.
- [x] **1% platform fee** — every paid booking adds a 1% premium credited to a `platform_earnings` ledger; admin dashboard shows total earnings and recent fee entries.
- [x] **Distance filter on Explore** — parent city auto-geocodes → slider (10/25/50/100/250/500/1000 mi) + "Include remote" toggle; cards show `distance_miles`; results sorted nearest-first.
- [x] **Chat → booking-receipt deep link** — an accepted lesson-invitation card in chat is tappable and opens `/booking-detail/{booking_id}`.
- [x] **Rate-session bottom-sheet** — 5-star tap-scale animated composer with quick label ("Loved it 💫"), textarea and post-review flow. Auto-opens after the server posts a `review:<booking_id>` notification (30 min after session); also reachable via a "Rate your session" CTA on the paid booking receipt. Tutor profile now has filter chips (Latest / All / 5★ / 4★+ / 3★+) with a "Show all N reviews" expander (5 at a time).
- [x] **Au-pair Housing offered** — brand-tinted, character-counted textarea that appears only when the parent picks "Au-pair" on the booking screen. Server discards on single-session bookings. Rendered as its own row on the booking receipt for both sides.
- [x] **Morning-of Session Reminder** — server emits `morning:<booking_id>` on the day of a paid session; the NotificationsWatcher opens a warm "Session today" bottom sheet with **Get directions** (opens the native Maps app / Google Maps in web) and **Message tutor** (jumps to the chat thread). Falls back gracefully for remote lessons and unpinned tutor locations.
- [x] **W-9 tax form (US tutors)** — after a tutor completes their first paid session, they get a `w9:required` notification with a "Fill W-9" action button in the toast. Full IRS-style form (legal name, business/DBA, federal tax classification with LLC + Other sub-choices, address, SSN/EIN, signature, US-person + backup-withholding certifications) upserts into `db.w9_forms`. TINs are now **encrypted with Fernet** and can be rotated at any time via `W9_ENCRYPTION_KEYS` (comma-separated) in `.env`; `GET /api/admin/w9-encryption-status` reports how many records still use retired keys. Startup migration auto-upgrades any legacy records. Both the tutor and admins can preview + print the form as a clean 1-page HTML (via `expo-print` on native, `window.print()` on web). Admin dashboard has a "Tax forms (W-9)" section listing every submission with print buttons.

- [x] **Fixes (review, Nov 2026)** — tutors now see their own bookings (bookings store the tutor *profile* id; tutor-side lookups used the user id); "9:00" vs "09:00" double-booking; reviews limited to one per finished paid session; uploads typed by extension + 10 MB cap; seed tutors no longer use a public password.
- [x] **Password reset + email verification** — 6-digit emailed codes (15 min, 5 tries); reset signs out other sessions (`token_version`); `REQUIRE_EMAIL_VERIFICATION` gates booking/messaging/posting.
- [x] **Time zones** — tutors have an IANA `timezone`; bookings store it; all reminders, "has it started" checks and past-date checks use it; the app labels times when you're in another zone.
- [x] **Overlap-aware booking** — a 2 h session blocks the hours it covers; unique `slot_key` index stops same-start races.
- [x] **Booking lifecycle** — tutor accepts/declines paid requests within 24 h (else auto-refund); cancel with refund policy (full refund ≥24 h ahead or when the tutor cancels); reschedule up to 24 h before; unpaid bookings release after 30 min; refunds reverse the platform fee.
- [x] **Tutor verification** — photo ID + background-check certificate upload, admin approve/send back, ✔ Verified badge and "Verified only" search filter. Manual review — no third-party checking provider yet.
- [x] **Push notifications** — Expo push tokens per device; every notification is also pushed; taps open the booking/chat; background worker sends reminders without the app open.
- [x] **Retention** — account deletion keeps anonymised bookings/reviews and the encrypted W-9 for 4 years (then purged); stored files deleted best-effort.
- [x] **SEO** — server-rendered share pages for tutors and blog posts with Open Graph tags; sitemap at `/api/seo/sitemap.xml`; page titles on web.
- [x] **Engineering** — `server.py` split into `core`/`models`/`routes/*`; in-process test suite (`tests_inprocess/`); integration tests default to localhost; GitHub Actions CI.
- [x] **Accessibility** — minimum 12 px text, larger tap targets, screen-reader labels/roles on buttons, chips, inputs and back arrows.

## MOCKED / Deferred
- Stripe PaymentSheet remains MOCKED — backend creates real PaymentIntent (and real refunds) when a valid key is set, else falls back. Ready to swap in `@stripe/stripe-react-native` PaymentSheet on the first EAS dev build.
- Push needs an EAS project id + a dev/production build (not Expo Go).
- Background checks are reviewed manually by an admin; no automated provider is integrated.

## Required environment variables
Backend `.env`: see `backend/.env.example` (required: `MONGO_URL`, `DB_NAME`, `JWT_SECRET`).
Frontend `.env`:
```
EXPO_PUBLIC_BACKEND_URL
```

## Smart business enhancement
The public marketing drawer + "New tutor" flag + count badge combine to make the marketplace look real from the very first tutor. Analytics events give you a working funnel from day one.
