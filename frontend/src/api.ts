import { storage } from "@/src/utils/storage";
import { uploadForm } from "@/src/utils/upload";

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
    if (res.status === 423) suspendedHandler?.(typeof msg === "string" ? msg : "");
    throw new Error(typeof msg === "string" ? msg : "Request failed");
  }
  return data as T;
}

/** Called when the server reports the signed-in account is paused (HTTP 423). */
let suspendedHandler: ((message: string) => void) | null = null;
export function onAccountSuspended(fn: ((message: string) => void) | null) {
  suspendedHandler = fn;
}

export async function apiUpload(uri: string, name = "photo.jpg", type = "image/jpeg"): Promise<{ path: string; url: string }> {
  const res = await uploadForm(`${BASE}/api/uploads`, uri, name, type, await authHeaders());
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

export interface TutorLocation { name: string; latitude?: number | null; longitude?: number | null }
export interface Tutor {
  id: string;
  user_id: string;
  name: string;
  avatar_url?: string | null;
  bio: string;
  languages: string[];
  hourly_rate_cents: number;
  currency: string;
  location: string;  // legacy primary
  latitude?: number | null;
  longitude?: number | null;
  locations?: TutorLocation[];
  allows_remote?: boolean;
  experience_years: number;
  rating: number;
  reviews_count: number;
  accreditation_urls: string[];  // legacy
  accreditation_photo_url?: string | null;
  accreditation_document_url?: string | null;
  hero_image_url?: string | null;
  is_new?: boolean;
  weekly_availability?: { [day: string]: string[] };
  distance_miles?: number | null;
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
  platform_fee_cents?: number;
  currency: string;
  payment_status: string;
  notes?: string;
  is_au_pair?: boolean;
  lessons_count?: number;
  distance_miles?: number | null;
  remote?: boolean;
  housing_offered?: string;
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

export type PostStatus = "pending" | "published" | "rejected";
export interface BlogPost {
  id: string;
  author_id: string;
  author_name: string;
  author_avatar_url?: string | null;
  title: string;
  excerpt: string;
  body: string;
  cover_image_url?: string;
  tag: string;
  image_urls: string[];
  status: PostStatus;
  reviewer_notes?: string;
  submitted_at: string;
  reviewed_at?: string | null;
  published_at?: string | null;
  updated_at: string;
}
export const BLOG_TAGS = ["Guides", "Activities", "Culture", "Tips", "Trends", "Tutor spotlight"] as const;
export const MAX_POST_IMAGES = 2;
export function readMinutes(text: string) {
  return Math.max(1, Math.round((text || "").split(/\s+/).length / 200));
}
