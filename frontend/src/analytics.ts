import { apiFetch } from "./api";

export function track(name: string, props: Record<string, any> = {}) {
  // Fire-and-forget; never blocks UX. Silently drops when unauthenticated.
  apiFetch("/events", { method: "POST", body: JSON.stringify({ name, props }) }).catch(() => {});
}
