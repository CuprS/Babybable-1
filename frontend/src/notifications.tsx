import { useEffect, useRef } from "react";
import { apiFetch } from "./api";
import { useAuth } from "./auth";
import { useToast } from "./toast";
import { storage } from "./utils/storage";

interface Notif { id: string; kind: string; title: string; body: string; at: string; read: boolean }

const SEEN_KEY = "bb_last_notif_seen";

export function NotificationsWatcher() {
  const { user } = useAuth();
  const { show } = useToast();
  const timer = useRef<any>(null);

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
        if (list[0]) await storage.set(SEEN_KEY, list[0].at);
      } catch {}
      if (!cancelled) timer.current = setTimeout(tick, 6000);
    };
    tick();
    return () => { cancelled = true; if (timer.current) clearTimeout(timer.current); };
  }, [user, show]);

  return null;
}
