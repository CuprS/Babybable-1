import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
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

export default function Admin() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [counts, setCounts] = useState<EventBucket[]>([]);
  const [earnings, setEarnings] = useState<Earning[]>([]);
  const [filter, setFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, e, earn] = await Promise.all([
        apiFetch<Stats>("/admin/stats"),
        apiFetch<{ events: EventRow[]; counts: EventBucket[] }>(`/admin/events${filter ? `?name=${encodeURIComponent(filter)}` : ""}`),
        apiFetch<{ total_cents: number; count: number; entries: Earning[] }>("/admin/earnings?limit=20").catch(() => ({ total_cents: 0, count: 0, entries: [] as Earning[] })),
      ]);
      setStats(s); setEvents(e.events); setCounts(e.counts); setEarnings(earn.entries || []);
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
});
