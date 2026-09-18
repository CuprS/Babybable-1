import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Platform, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as Print from "expo-print";
import { apiFetch } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { Button } from "@/src/ui";

interface Stats {
  users: number; parents: number; tutors: number;
  bookings: number; paid_bookings: number;
  messages: number; reviews: number; favorites: number; events: number;
  platform_earnings_cents?: number; platform_earnings_count?: number;
}
interface EventRow { user_id: string; user_name?: string; role: string; name: string; props: any; at: string }
interface EventBucket { name: string; count: number }
interface Earning { id: string; booking_id: string; parent_id?: string; tutor_id?: string; amount_cents: number; at: string }
interface W9Row {
  id: string; tutor_user_id: string; tutor_name: string; tutor_email: string;
  legal_name: string; tax_classification: string; llc_tax_class: string; other_classification: string;
  city: string; state: string; zip_code: string;
  tin_type: string; tin_masked: string;
  signature_name: string; signed_at: string; updated_at: string;
  business_name: string; address: string; country: string; is_us_person: boolean; exempt_from_backup: boolean;
}

export default function Admin() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [counts, setCounts] = useState<EventBucket[]>([]);
  const [earnings, setEarnings] = useState<Earning[]>([]);
  const [w9s, setW9s] = useState<W9Row[]>([]);
  const [filter, setFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [printingId, setPrintingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, e, earn, w9list] = await Promise.all([
        apiFetch<Stats>("/admin/stats"),
        apiFetch<{ events: EventRow[]; counts: EventBucket[] }>(`/admin/events${filter ? `?name=${encodeURIComponent(filter)}` : ""}`),
        apiFetch<{ total_cents: number; count: number; entries: Earning[] }>("/admin/earnings?limit=20").catch(() => ({ total_cents: 0, count: 0, entries: [] as Earning[] })),
        apiFetch<W9Row[]>("/admin/w9?limit=100").catch(() => [] as W9Row[]),
      ]);
      setStats(s); setEvents(e.events); setCounts(e.counts); setEarnings(earn.entries || []); setW9s(w9list || []);
    } catch (err) {
      console.log("admin load err", err);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  if (!user?.is_admin) {
    return (
      <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
        <Text style={{ color: theme.color.onSurface, padding: theme.space.xl }}>Admins only.</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.sm }}>
          <Feather name="shield" size={20} color={theme.color.brand} />
          <Text style={styles.title}>Admin</Text>
        </View>
        <Pressable onPress={signOut} testID="admin-signout" hitSlop={12}>
          <Feather name="log-out" size={20} color={theme.color.onSurface} />
        </Pressable>
      </View>

      {loading && !stats ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.space.xl }} />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: theme.space.xl, paddingBottom: theme.space["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
        >
          <Text style={styles.hello}>Welcome, {user.name}</Text>
          <Text style={styles.sub}>Live snapshot of Babybabel activity.</Text>

          <View style={styles.earnHero} testID="admin-platform-earnings">
            <View style={{ flex: 1 }}>
              <Text style={styles.earnLabel}>Platform earnings (1% fee)</Text>
              <Text style={styles.earnAmount}>${((stats?.platform_earnings_cents ?? 0) / 100).toFixed(2)}</Text>
              <Text style={styles.earnSub}>Across {stats?.platform_earnings_count ?? 0} paid booking{(stats?.platform_earnings_count ?? 0) === 1 ? "" : "s"}</Text>
            </View>
            <Feather name="trending-up" size={38} color={theme.color.brand} />
          </View>

          <Text style={styles.section}>Platform stats</Text>
          <View style={styles.statGrid}>
            <StatCard icon="users" label="Users" value={stats?.users ?? 0} />
            <StatCard icon="heart" label="Parents" value={stats?.parents ?? 0} />
            <StatCard icon="book-open" label="Tutors" value={stats?.tutors ?? 0} />
            <StatCard icon="calendar" label="Bookings" value={stats?.bookings ?? 0} />
            <StatCard icon="dollar-sign" label="Paid" value={stats?.paid_bookings ?? 0} />
            <StatCard icon="message-circle" label="Messages" value={stats?.messages ?? 0} />
            <StatCard icon="star" label="Reviews" value={stats?.reviews ?? 0} />
            <StatCard icon="bookmark" label="Favourites" value={stats?.favorites ?? 0} />
            <StatCard icon="activity" label="Events" value={stats?.events ?? 0} />
          </View>

          <Text style={styles.section}>Recent platform fees</Text>
          {earnings.length === 0 ? (
            <Text style={styles.muted}>No fees collected yet. They&apos;ll appear here once a booking is paid.</Text>
          ) : (
            earnings.slice(0, 8).map((r) => (
              <View key={r.id} style={styles.eventRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.eventName}>+ ${(r.amount_cents / 100).toFixed(2)}</Text>
                  <Text style={styles.eventMeta}>Booking {r.booking_id.slice(0, 8)} · {new Date(r.at).toLocaleString()}</Text>
                </View>
              </View>
            ))
          )}

          <Text style={styles.section}>Tax forms (W-9)</Text>
          {w9s.length === 0 ? (
            <Text style={styles.muted}>No W-9 forms submitted yet.</Text>
          ) : (
            w9s.map((w) => (
              <View key={w.id} style={styles.w9Row} testID={`admin-w9-${w.tutor_user_id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.eventName}>{w.legal_name}</Text>
                  <Text style={styles.eventMeta}>
                    {w.tutor_email} · {w.tin_type.toUpperCase()} {w.tin_masked} · {new Date(w.signed_at).toLocaleDateString()}
                  </Text>
                  <Text style={styles.eventMeta}>
                    {classificationLabel(w.tax_classification, w.llc_tax_class, w.other_classification)} · {w.city}, {w.state}
                  </Text>
                </View>
                <Pressable
                  onPress={async () => {
                    setPrintingId(w.id);
                    try { await printW9(w); } finally { setPrintingId(null); }
                  }}
                  disabled={printingId === w.id}
                  style={styles.w9Btn}
                  testID={`admin-w9-print-${w.tutor_user_id}`}
                >
                  <Feather name="printer" size={14} color="#fff" />
                  <Text style={styles.w9BtnText}>{printingId === w.id ? "…" : "Print"}</Text>
                </Pressable>
              </View>
            ))
          )}

          <Text style={styles.section}>Top events</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: theme.space.sm, paddingRight: theme.space.xl }}>
            <Pressable
              testID="admin-filter-all"
              onPress={() => setFilter(null)}
              style={[styles.eventChip, !filter && styles.eventChipActive]}
            >
              <Text style={[styles.eventChipText, !filter && styles.eventChipTextActive]}>All</Text>
            </Pressable>
            {counts.map((b) => (
              <Pressable
                key={b.name}
                testID={`admin-filter-${b.name}`}
                onPress={() => setFilter(b.name)}
                style={[styles.eventChip, filter === b.name && styles.eventChipActive]}
              >
                <Text style={[styles.eventChipText, filter === b.name && styles.eventChipTextActive]}>
                  {b.name} · {b.count}
                </Text>
              </Pressable>
            ))}
          </ScrollView>

          <Text style={styles.section}>Recent events {filter ? `· ${filter}` : ""}</Text>
          {events.length === 0 ? (
            <Text style={styles.muted}>No events tracked yet — as parents browse and book, they'll show up here in real time.</Text>
          ) : (
            events.map((e, i) => (
              <View key={i} style={styles.eventRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.eventName}>{e.name}</Text>
                  <Text style={styles.eventMeta}>
                    {(e.user_name || "?")}  ·  {e.role}  ·  {new Date(e.at).toLocaleString()}
                  </Text>
                  {e.props && Object.keys(e.props).length > 0 && (
                    <Text style={styles.eventProps} numberOfLines={2}>{JSON.stringify(e.props)}</Text>
                  )}
                </View>
              </View>
            ))
          )}

          <View style={{ marginTop: theme.space["2xl"] }}>
            <Button title="Refresh" onPress={load} variant="secondary" testID="admin-refresh" />
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function StatCard({ icon, label, value }: { icon: any; label: string; value: number }) {
  return (
    <View style={styles.stat} testID={`stat-${label.toLowerCase()}`}>
      <Feather name={icon} size={16} color={theme.color.brand} />
      <Text style={styles.statNum}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  hello: { fontSize: 28, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5 },
  sub: { color: theme.color.onSurfaceSecondary, marginTop: 4 },
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm },
  stat: { width: "31.5%", padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, gap: 4 },
  statNum: { fontSize: 22, fontWeight: "700", color: theme.color.onSurface },
  statLabel: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  eventChip: { paddingHorizontal: theme.space.md, paddingVertical: 8, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.borderStrong },
  eventChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  eventChipText: { color: theme.color.onSurface, fontWeight: "500" },
  eventChipTextActive: { color: theme.color.onBrand },
  eventRow: { padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, marginBottom: theme.space.sm },
  eventName: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.brand },
  eventMeta: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: 4 },
  eventProps: { color: theme.color.muted, fontSize: 11, marginTop: 4, fontFamily: "monospace" },
  muted: { color: theme.color.onSurfaceSecondary },
  earnHero: {
    marginTop: theme.space.xl,
    flexDirection: "row", alignItems: "center", gap: theme.space.md,
    padding: theme.space.lg,
    backgroundColor: theme.color.brandSoft,
    borderRadius: theme.radius.lg,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  earnLabel: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.sm, letterSpacing: 0.4, textTransform: "uppercase" },
  earnAmount: { color: theme.color.brandDark, fontWeight: "700", fontSize: 34, letterSpacing: -0.5, marginTop: 2 },
  earnSub: { color: theme.color.brandDark, opacity: 0.85, fontSize: theme.font.sm, marginTop: 2 },
  w9Row: {
    flexDirection: "row", alignItems: "center", gap: theme.space.md,
    paddingVertical: theme.space.md, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  w9Btn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: theme.space.md, paddingVertical: 8,
    borderRadius: theme.radius.pill, backgroundColor: theme.color.brand,
  },
  w9BtnText: { color: "#fff", fontWeight: "700", fontSize: theme.font.sm },
});

function classificationLabel(k: string, llc?: string, other?: string) {
  const map: Record<string, string> = {
    individual: "Individual / Sole proprietor",
    c_corp: "C Corporation",
    s_corp: "S Corporation",
    partnership: "Partnership",
    trust_estate: "Trust / Estate",
    llc: `LLC (${llc || "?"})`,
    other: `Other (${other || ""})`,
    sole_proprietor: "Sole proprietor",
  };
  return map[k] || k;
}

async function printW9(w: W9Row) {
  const html = buildW9Html(w);
  try {
    if (Platform.OS === "web") {
      const win = window.open("", "_blank");
      if (win) { win.document.write(html); win.document.close(); setTimeout(() => win.print(), 300); }
    } else {
      await Print.printAsync({ html });
    }
  } catch (e: any) {
    Alert.alert("Print failed", e?.message || "Try again in a moment.");
  }
}

function buildW9Html(w: W9Row): string {
  const esc = (v: string) => String(v || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c));
  const cls = esc(classificationLabel(w.tax_classification, w.llc_tax_class, w.other_classification));
  const date = new Date(w.signed_at).toLocaleDateString();
  return `<!doctype html>
<html><head><meta charset="utf-8" />
<title>Form W-9 — ${esc(w.legal_name)}</title>
<style>
  @page { margin: 24mm 18mm; }
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; color: #1f1a17; font-size: 12px; }
  h1 { font-size: 20px; letter-spacing: -0.3px; margin: 0 0 4px; }
  h2 { font-size: 13px; margin: 24px 0 6px; text-transform: uppercase; letter-spacing: 0.6px; color: #E4572E; }
  .sub { color: #6b6260; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  td { border: 1px solid #d8d1cd; padding: 8px 10px; vertical-align: top; }
  td.label { background: #f8f3ee; width: 34%; font-weight: 700; color: #5a3a2a; }
  .sig { margin-top: 26px; border-top: 1px solid #d8d1cd; padding-top: 10px; }
  .brand { color: #E4572E; font-weight: 700; }
  .footer { margin-top: 30px; font-size: 10px; color: #8a807c; }
</style>
</head><body>
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <h1>Form W-9 <span style="font-size:12px;color:#6b6260;">(Rev. Babybabel)</span></h1>
      <div class="sub">Request for Taxpayer Identification Number and Certification</div>
    </div>
    <div style="text-align:right">
      <div class="brand">Babybabel</div>
      <div style="color:#6b6260">Language childcare marketplace</div>
    </div>
  </div>
  <h2>Identifying information</h2>
  <table>
    <tr><td class="label">1. Name (as shown on your tax return)</td><td>${esc(w.legal_name)}</td></tr>
    <tr><td class="label">2. Business name / DBA</td><td>${esc(w.business_name) || "—"}</td></tr>
    <tr><td class="label">3. Federal tax classification</td><td>${cls}</td></tr>
    <tr><td class="label">4. Exempt from backup withholding?</td><td>${w.exempt_from_backup ? "Yes" : "No"}</td></tr>
    <tr><td class="label">5. Address</td><td>${esc(w.address)}</td></tr>
    <tr><td class="label">6. City, State, ZIP</td><td>${esc(w.city)}, ${esc(w.state)} ${esc(w.zip_code)}</td></tr>
    <tr><td class="label">7. Country</td><td>${esc(w.country || "US")}</td></tr>
  </table>
  <h2>Part I — Taxpayer Identification Number</h2>
  <table>
    <tr><td class="label">Type</td><td>${w.tin_type.toUpperCase()}</td></tr>
    <tr><td class="label">TIN</td><td>${esc(w.tin_masked)}</td></tr>
  </table>
  <h2>Part II — Certification</h2>
  <p>Under penalties of perjury, I certify that:</p>
  <ol>
    <li>The number shown on this form is my correct taxpayer identification number.</li>
    <li>I am not subject to backup withholding${w.exempt_from_backup ? "" : " unless notified otherwise by the IRS"}.</li>
    <li>${w.is_us_person ? "I am a U.S. citizen or other U.S. person." : "I am NOT a U.S. person (see instructions)."}</li>
  </ol>
  <div class="sig">
    <div>Signature: <strong>${esc(w.signature_name)}</strong></div>
    <div>Signed on ${esc(date)} · Submitted by ${esc(w.tutor_name)} (${esc(w.tutor_email)})</div>
  </div>
  <div class="footer">
    Generated by Babybabel · Not a substitute for IRS Form W-9. Consult a tax professional if in doubt.
  </div>
</body></html>`;
}
