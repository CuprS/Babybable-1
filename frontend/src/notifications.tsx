import { useEffect, useRef } from "react";
import { apiFetch, Booking, Tutor } from "./api";
import { useAuth } from "./auth";
import { useToast } from "./toast";
import { useReviewPrompt } from "./reviewprompt";
import { useSessionReminder } from "./sessionreminder";
import { storage } from "./utils/storage";

interface Notif { id: string; kind: string; title: string; body: string; at: string; read: boolean }

const SEEN_KEY = "bb_last_notif_seen";
const REVIEWED_KEY = "bb_reviewed_bookings"; // JSON array of bookingIds we've asked/reviewed
const MORNING_KEY = "bb_morning_bookings"; // JSON array of bookingIds we've opened today

async function readJsonList(key: string): Promise<string[]> {
  const raw = (await storage.get<string>(key, "")) || "";
  try { return raw ? (JSON.parse(raw) as string[]) : []; } catch { return []; }
}

async function pushJsonList(key: string, value: string, cap = 100) {
  const arr = await readJsonList(key);
  if (!arr.includes(value)) arr.push(value);
  await storage.set(key, JSON.stringify(arr.slice(-cap)));
}

// Reset the morning-of dedupe list at UTC-midnight rollover so it re-fires next day.
async function pruneMorningIfNewDay() {
  const stamp = (await storage.get<string>(MORNING_KEY + "_day", "")) || "";
  const today = new Date().toISOString().slice(0, 10);
  if (stamp !== today) {
    await storage.set(MORNING_KEY, JSON.stringify([]));
    await storage.set(MORNING_KEY + "_day", today);
  }
}

export function NotificationsWatcher() {
  const { user } = useAuth();
  const { show } = useToast();
  const { openReview } = useReviewPrompt();
  const { openReminder } = useSessionReminder();
  const timer = useRef<any>(null);
  const promptedReview = useRef<Set<string>>(new Set());
  const promptedMorning = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const tick = async () => {
      try {
        await pruneMorningIfNewDay();
        const list = await apiFetch<Notif[]>("/notifications");
        const seen = (await storage.get<string>(SEEN_KEY, "")) || "";
        const fresh = list.filter((n) => n.at > seen);
        if (fresh.length && seen) {
          fresh.slice(-3).reverse().forEach((n) => {
            show({ kind: n.kind === "chat" ? "info" : "success", title: n.title, body: n.body });
          });
        }
        if (user.role === "parent") {
          // Morning-of reminder: open the sheet (once per booking per day).
          for (const n of list) {
            if (!n.kind.startsWith("morning:")) continue;
            const bookingId = n.kind.split(":")[1];
            if (!bookingId || promptedMorning.current.has(bookingId)) continue;
            const handled = await readJsonList(MORNING_KEY);
            if (handled.includes(bookingId)) continue;
            promptedMorning.current.add(bookingId);
            try {
              const b = await apiFetch<Booking>(`/bookings/${bookingId}`);
              let tutor: Tutor | null = null;
              try { tutor = await apiFetch<Tutor>(`/tutors/${b.tutor_id}`); } catch {}
              await pushJsonList(MORNING_KEY, bookingId);
              openReminder({ booking: b, tutor });
            } catch {
              await pushJsonList(MORNING_KEY, bookingId);
            }
            break; // one sheet at a time
          }
          // Review prompt after session.
          for (const n of list) {
            if (!n.kind.startsWith("review:")) continue;
            const bookingId = n.kind.split(":")[1];
            if (!bookingId || promptedReview.current.has(bookingId)) continue;
            const handled = await readJsonList(REVIEWED_KEY);
            if (handled.includes(bookingId)) continue;
            promptedReview.current.add(bookingId);
            try {
              const b = await apiFetch<Booking>(`/bookings/${bookingId}`);
              await pushJsonList(REVIEWED_KEY, bookingId);
              openReview({ bookingId, tutorId: b.tutor_id, tutorName: b.tutor_name });
            } catch {
              await pushJsonList(REVIEWED_KEY, bookingId);
            }
            break;
          }
        }
        if (list[0]) await storage.set(SEEN_KEY, list[0].at);
      } catch {}
      if (!cancelled) timer.current = setTimeout(tick, 6000);
    };
    tick();
    return () => { cancelled = true; if (timer.current) clearTimeout(timer.current); };
  }, [user, show, openReview, openReminder]);

  return null;
}
