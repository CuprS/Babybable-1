import { storage } from "@/src/utils/storage";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL as string;
export const TOKEN_KEY = "babybabel_token";

async function authHeaders(): Promise<Record<string, string>> {
  const t = await storage.secureGet<string>(TOKEN_KEY, "");
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function apiFetch<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeaders()),
    ...((init.headers as Record<string, string>) || {}),
  };
  const res = await fetch(`${BASE}/api${path}`, { ...init, headers });
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) {
    const msg = (data && typeof data === "object" && "detail" in data) ? (data as any).detail : `Request failed (${res.status})`;
    throw new Error(typeof msg === "string" ? msg : "Request failed");
  }
  return data as T;
}

export async function apiUpload(uri: string, name = "photo.jpg", type = "image/jpeg"): Promise<{ path: string; url: string }> {
  const form = new FormData();
  // Web: uri is a blob: URL — fetch it and append a real File so FormData actually streams bytes.
  // Native (iOS/Android): pass the descriptor as { uri, name, type }.
  const isWeb = typeof document !== "undefined";
  if (isWeb) {
    const blob = await fetch(uri).then((r) => r.blob());
    form.append("file", new File([blob], name, { type: blob.type || type }));
  } else {
    form.append("file", { uri, name, type } as any);
  }
  const t = await storage.secureGet<string>(TOKEN_KEY, "");
  const res = await fetch(`${BASE}/api/uploads`, {
    method: "POST",
    body: form,
    headers: t ? { Authorization: `Bearer ${t}` } : {},
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

export function fileUrl(pathOrUrl?: string | null): string | undefined {
  if (!pathOrUrl) return undefined;
  if (pathOrUrl.startsWith("http")) return pathOrUrl;
  if (pathOrUrl.startsWith("/api/")) return `${BASE}${pathOrUrl}`;
  return `${BASE}/api/files/${pathOrUrl}`;
}

// ---- Types ----
export type Role = "parent" | "tutor" | "admin";

export interface UserPublic {
  id: string;
  email: string;
  name: string;
  role: Role;
  avatar_url?: string | null;
  is_admin?: boolean;
}

export interface Tutor {
  id: string;
  user_id: string;
  name: string;
  avatar_url?: string | null;
  bio: string;
  languages: string[];
  hourly_rate_cents: number;
  currency: string;
  location: string;
  experience_years: number;
  rating: number;
  reviews_count: number;
  accreditation_urls: string[];
  hero_image_url?: string | null;
  is_new?: boolean;
}

export interface Booking {
  id: string;
  parent_id: string;
  parent_name: string;
  tutor_id: string;
  tutor_name: string;
  date: string;
  time: string;
  duration_minutes: number;
  language: string;
  amount_cents: number;
  currency: string;
  payment_status: string;
  notes?: string;
  created_at: string;
}

export interface Review {
  id: string;
  tutor_id: string;
  parent_id: string;
  parent_name: string;
  rating: number;
  comment: string;
  created_at: string;
}
