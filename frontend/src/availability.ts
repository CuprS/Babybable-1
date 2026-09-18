// Shared time slot helpers used by the tutor availability calendar,
// the parent booking screen, and the tutor lesson-invitation composer.

export const WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type WeekdayKey = typeof WEEKDAY_KEYS[number];

export const WEEKDAY_LABELS: Record<WeekdayKey, string> = {
  mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
};

// Hourly slots families actually book at — 8 AM through 8 PM.
export const HOUR_SLOTS: string[] = Array.from({ length: 13 }, (_, i) => {
  const h = 8 + i;
  return `${String(h).padStart(2, "0")}:00`;
});

export function weekdayFromDate(dateStr: string): WeekdayKey | null {
  const [y, m, d] = dateStr.split("-").map((n) => parseInt(n, 10));
  if (!y || !m || !d) return null;
  const dt = new Date(y, m - 1, d);
  // JS: Sunday=0..Saturday=6 — remap to Mon-first.
  const jsIdx = dt.getDay();
  const idx = jsIdx === 0 ? 6 : jsIdx - 1;
  return WEEKDAY_KEYS[idx];
}

export function normalizeSlot(t: string): string {
  const [h, m] = (t || "").split(":");
  if (h == null || m == null) return "";
  const hi = parseInt(h, 10);
  const mi = parseInt(m, 10);
  if (Number.isNaN(hi) || Number.isNaN(mi)) return "";
  return `${String(hi).padStart(2, "0")}:${String(mi).padStart(2, "0")}`;
}

export interface WeeklyAvailability {
  [day: string]: string[]; // day key -> sorted slots
}

/** Given a tutor's weekly availability and (optionally) their booked slots, decide if a slot
 * is bookable. Returns null when allowed, else a reason string. */
export function slotStatus(
  weekly: WeeklyAvailability | null | undefined,
  bookedSlots: { date: string; time: string }[] | null | undefined,
  date: string,
  time: string,
): "ok" | "unavailable" | "booked" {
  const key = weekdayFromDate(date);
  const norm = normalizeSlot(time);
  if (bookedSlots?.some((b) => b.date === date && normalizeSlot(b.time) === norm)) return "booked";
  const wa = weekly || {};
  const hasCalendar = Object.values(wa).some((slots) => Array.isArray(slots) && slots.length > 0);
  if (!hasCalendar) return "ok"; // legacy tutors who haven't set a calendar → treat as open
  if (!key) return "ok";
  const daySlots = new Set((wa[key] || []).map(normalizeSlot));
  return daySlots.has(norm) ? "ok" : "unavailable";
}
