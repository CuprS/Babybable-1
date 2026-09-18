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
- [x] **Analytics** — dual sink: local `/api/events` + **PostHog** (`posthog-react-native` on client, `posthog` on backend). Server captures `signup`, `booking_created`, and forwards all client events. Provide `EXPO_PUBLIC_POSTHOG_KEY` + `POSTHOG_PROJECT_TOKEN` to enable.
- [x] Global side drawer with 6 marketing landing pages + Download-the-app (web) + Privacy Policy.
- [x] Delete account (both roles) — cascades bookings, messages, uploads, reviews.
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

## MOCKED / Deferred
- Stripe PaymentSheet remains MOCKED — backend creates real PaymentIntent when a valid key is set, else falls back. Ready to swap in `@stripe/stripe-react-native` PaymentSheet on the first EAS dev build.
- Push notifications currently surface as in-app toasts. When you generate an EAS dev build, we can drop in Emergent-managed push using the same notification records — the plumbing is already there.

## Required environment variables
Backend `.env`:
```
MONGO_URL, DB_NAME, JWT_SECRET, STRIPE_API_KEY, EMERGENT_LLM_KEY,
POSTHOG_PROJECT_TOKEN, POSTHOG_HOST
```
Frontend `.env`:
```
EXPO_PUBLIC_BACKEND_URL, EXPO_PUBLIC_POSTHOG_KEY, EXPO_PUBLIC_POSTHOG_HOST
```

## Smart business enhancement
The public marketing drawer + "New tutor" flag + count badge combine to make the marketplace look real from the very first tutor. Analytics events give you a working funnel from day one.
