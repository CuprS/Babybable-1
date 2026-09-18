import { useEffect, useRef } from "react";
import { apiFetch, Booking } from "./api";
import { useAuth } from "./auth";
import { useToast } from "./toast";
import { useReviewPrompt } from "./reviewprompt";
import { storage } from "./utils/storage";

interface Notif { id: string; kind: string; title: string; body: string; at: string; read: boolean }

const SEEN_KEY = "bb_last_notif_seen";
const REVIEWED_KEY = "bb_reviewed_bookings"; // JSON array of bookingIds we've asked/reviewed

async function hasHandled(bookingId: string): Promise<boolean> {
  const raw = (await storage.get<string>(REVIEWED_KEY, "")) || "";
  try {
    const arr = raw ? JSON.parse(raw) as string[] : [];
    return arr.includes(bookingId);
  } catch { return false; }
}

async function markHandled(bookingId: string) {
  const raw = (await storage.get<string>(REVIEWED_KEY, "")) || "";
  try {
    const arr = raw ? JSON.parse(raw) as string[] : [];
    if (!arr.includes(bookingId)) arr.push(bookingId);
    await storage.set(REVIEWED_KEY, JSON.stringify(arr.slice(-100)));
  } catch {}
}

export function NotificationsWatcher() {
  const { user } = useAuth();
  const { show } = useToast();
  const { openReview } = useReviewPrompt();
  const timer = useRef<any>(null);
  const promptedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const list = await apiFetch<Notif[]>("/notifications");
        const seen = (await storage.get<string>(SEEN_KEY, "")) || "";
        const fresh = list.filter((n) => n.at > seen);
        if (fresh.length && seen) {
          fresh.slice(-3).reverse().forEach((n) => {
            show({ kind: n.kind === "chat" ? "info" : "success", title: n.title, body: n.body });
          });
        }
        // Review request auto-prompt: look for kind starting with "review:"
        if (user.role === "parent") {
          for (const n of list) {
            if (!n.kind.startsWith("review:")) continue;
            const bookingId = n.kind.split(":")[1];
            if (!bookingId || promptedRef.current.has(bookingId)) continue;
            if (await hasHandled(bookingId)) continue;
            promptedRef.current.add(bookingId);
            try {
              const b = await apiFetch<Booking>(`/bookings/${bookingId}`);
              await markHandled(bookingId);
              openReview({ bookingId, tutorId: b.tutor_id, tutorName: b.tutor_name });
            } catch {
              // If we can't fetch, mark handled to avoid spamming.
              await markHandled(bookingId);
            }
            break; // one at a time
          }
        }
        if (list[0]) await storage.set(SEEN_KEY, list[0].at);
      } catch {}
      if (!cancelled) timer.current = setTimeout(tick, 6000);
    };
    tick();
    return () => { cancelled = true; if (timer.current) clearTimeout(timer.current); };
  }, [user, show, openReview]);

  return null;
}
