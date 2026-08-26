import { useEffect, useMemo, useState, useCallback } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, ScrollView, ActivityIndicator, RefreshControl, TextInput } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { apiFetch, fileUrl, Tutor } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { Chip } from "@/src/ui";
import { MenuButton } from "@/src/drawer";
import { flagFor } from "@/src/flags";
import { track } from "@/src/analytics";

const LANGUAGES = ["All", "Spanish", "French", "Japanese", "Mandarin", "German", "Arabic", "English", "Italian"];

export default function Explore() {
  const { user } = useAuth();
  const router = useRouter();
  const [tutors, setTutors] = useState<Tutor[]>([]);
  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lang, setLang] = useState<string>("All");
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (lang !== "All") params.set("language", lang);
      if (debouncedQ.trim()) params.set("q", debouncedQ.trim());
      const qs = params.toString();
      const data = await apiFetch<Tutor[]>(`/tutors${qs ? `?${qs}` : ""}`);
      setTutors(data);
      if (debouncedQ.trim() || lang !== "All") {
        track("search", { query_length: debouncedQ.trim().length, result_count: data.length, language: lang, source: "explore" });
      }
    } catch (e) {
      console.log("load tutors error", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [lang, debouncedQ]);

  const loadFavs = useCallback(async () => {
    if (user?.role !== "parent") return;
    try { const ids = await apiFetch<string[]>("/favorites"); setFavs(new Set(ids)); } catch {}
  }, [user]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadFavs(); }, [loadFavs]);

  const toggleFav = async (id: string) => {
    const isFav = favs.has(id);
    const next = new Set(favs);
    if (isFav) { next.delete(id); await apiFetch(`/favorites/${id}`, { method: "DELETE" }); }
    else { next.add(id); await apiFetch(`/favorites/${id}`, { method: "POST" }); track("favorite_added", { tutor_id: id }); }
    setFavs(next);
  };

  // Tutors see their dashboard on this tab
  if (user?.role === "tutor") {
    return <TutorHome />;
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={styles.headerWrap}>
        <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: theme.space.md, paddingTop: theme.space.xs }}>
          <MenuButton tint={theme.color.onSurface} />
          <Text style={{ flex: 1, textAlign: "center", fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginRight: 40 }}>Explore</Text>
        </View>
        <View style={styles.searchBar} testID="explore-search-bar">
          <Feather name="search" size={20} color={theme.color.muted} />
          <TextInput
            testID="explore-search-input"
            placeholder="Search tutors, languages, cities"
            placeholderTextColor={theme.color.muted}
            style={styles.searchInput}
            value={q}
            onChangeText={setQ}
            returnKeyType="search"
          />
        </View>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: theme.space.sm, paddingHorizontal: theme.space.xl }}
          style={styles.chipsRow}
        >
          {LANGUAGES.map((l) => (
            <Chip key={l} label={l === "All" ? "All" : `${flagFor(l)} ${l}`} selected={lang === l} onPress={() => setLang(l)} testID={`chip-${l.toLowerCase()}`} />
          ))}
        </ScrollView>
      </SafeAreaView>

      {loading ? (
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator color={theme.color.brand} />
        </View>
      ) : (
        <FlatList
          testID="tutor-list"
          data={tutors}
          keyExtractor={(t) => t.id}
          contentContainerStyle={{ paddingTop: theme.space.md, paddingBottom: theme.space["3xl"], paddingHorizontal: theme.space.xl, gap: theme.space.xl }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
          ListHeaderComponent={
            <Text style={{ color: theme.color.onSurfaceSecondary, fontWeight: "600", marginBottom: theme.space.sm }} testID="tutor-count">
              {tutors.length} tutor{tutors.length === 1 ? "" : "s"}{lang !== "All" ? ` · ${flagFor(lang)} ${lang}` : ""}
            </Text>
          }
          ListEmptyComponent={
            <View style={{ padding: theme.space["2xl"], alignItems: "center" }}>
              <Feather name="search" size={48} color={theme.color.borderStrong} />
              <Text style={{ marginTop: theme.space.md, color: theme.color.onSurfaceSecondary }}>No tutors found. Try another language.</Text>
            </View>
          }
          renderItem={({ item }) => (
            <TutorCard
              tutor={item}
              isFav={favs.has(item.id)}
              canFav={user?.role === "parent"}
              onFav={() => toggleFav(item.id)}
              onPress={() => { track("tutor_view", { tutor_id: item.id, source: "explore" }); router.push(`/tutor/${item.id}`); }}
            />
          )}
        />
      )}
    </View>
  );
}

function TutorCard({ tutor, onPress, isFav, canFav, onFav }: { tutor: Tutor; onPress: () => void; isFav?: boolean; canFav?: boolean; onFav?: () => void }) {
  return (
    <Pressable onPress={onPress} testID={`tutor-card-${tutor.id}`} style={cardStyles.card}>
      <View style={cardStyles.imageWrap}>
        <Image
          source={{ uri: fileUrl(tutor.hero_image_url || tutor.avatar_url) }}
          style={cardStyles.image}
          contentFit="cover"
          transition={200}
        />
        <LinearGradient
          colors={["rgba(0,0,0,0)", "rgba(0,0,0,0.15)"]}
          style={StyleSheet.absoluteFill}
        />
        {tutor.is_new && (
          <View style={cardStyles.newBadge} testID={`tutor-new-${tutor.id}`}>
            <Text style={cardStyles.newBadgeText}>New tutor</Text>
          </View>
        )}
        <View style={cardStyles.priceBadge}>
          <Text style={cardStyles.priceText}>${(tutor.hourly_rate_cents / 100).toFixed(0)}/hr</Text>
        </View>
        {canFav && (
          <Pressable
            onPress={(e) => { e.stopPropagation?.(); onFav?.(); }}
            style={cardStyles.favBtn}
            testID={`tutor-fav-${tutor.id}`}
            hitSlop={10}
          >
            <Feather name="heart" size={20} color={isFav ? theme.color.brand : "#fff"} />
          </Pressable>
        )}
      </View>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginTop: theme.space.md }}>
        <View style={{ flex: 1 }}>
          <Text style={cardStyles.name} numberOfLines={1}>{tutor.name}</Text>
          <Text style={cardStyles.meta} numberOfLines={1}>{tutor.location || "Location coming soon"}</Text>
          <Text style={cardStyles.langs} numberOfLines={1}>
            {tutor.languages.length ? tutor.languages.map((l) => `${flagFor(l)} ${l}`).join("  ·  ") : "Setting up profile"}
          </Text>
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginLeft: theme.space.md }}>
          <Feather name="star" size={14} color={theme.color.onSurface} />
          <Text style={{ color: theme.color.onSurface, fontWeight: "600", fontSize: theme.font.base }}>
            {tutor.rating > 0 ? tutor.rating.toFixed(1) : "—"}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}

function TutorHome() {
  const router = useRouter();
  const [bookings, setBookings] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    apiFetch<any[]>("/bookings/me").then(setBookings).catch(() => {}).finally(() => setLoading(false));
  }, []);
  const paid = bookings.filter((b) => b.payment_status === "paid");
  const earnings = paid.reduce((a, b) => a + b.amount_cents, 0);
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.color.surface }} edges={["top"]}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: theme.space.md, paddingTop: theme.space.xs }}>
        <MenuButton tint={theme.color.onSurface} />
        <Text style={{ flex: 1, textAlign: "center", fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginRight: 40 }}>Dashboard</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: theme["3xl"] }}>
        <Text style={{ fontSize: 28, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5 }}>Welcome, tutor</Text>
        <Text style={{ color: theme.color.onSurfaceSecondary, marginTop: theme.space.xs }}>Here's your day at a glance.</Text>

        <View style={dashStyles.grid}>
          <View style={dashStyles.metric} testID="tutor-earnings-card">
            <Feather name="dollar-sign" size={18} color={theme.color.brand} />
            <Text style={dashStyles.metricNum}>${(earnings / 100).toFixed(0)}</Text>
            <Text style={dashStyles.metricLabel}>Earnings</Text>
          </View>
          <View style={dashStyles.metric} testID="tutor-sessions-card">
            <Feather name="calendar" size={18} color={theme.color.brand} />
            <Text style={dashStyles.metricNum}>{bookings.length}</Text>
            <Text style={dashStyles.metricLabel}>Sessions</Text>
          </View>
        </View>

        <Text style={dashStyles.section}>Upcoming</Text>
        {loading ? (
          <ActivityIndicator color={theme.color.brand} />
        ) : bookings.length === 0 ? (
          <View style={dashStyles.empty}>
            <Text style={{ color: theme.color.onSurfaceSecondary }}>No bookings yet. Update your profile to attract parents.</Text>
          </View>
        ) : (
          bookings.slice(0, 5).map((b) => (
            <View key={b.id} style={dashStyles.bookRow}>
              <View>
                <Text style={{ fontWeight: "700", color: theme.color.onSurface }}>{b.parent_name} · {b.language}</Text>
                <Text style={{ color: theme.color.onSurfaceSecondary, marginTop: 2 }}>{b.date} at {b.time} · {b.duration_minutes} min</Text>
              </View>
              <Text style={{ color: theme.color.brand, fontWeight: "700" }}>${(b.amount_cents / 100).toFixed(0)}</Text>
            </View>
          ))
        )}

        <Pressable
          testID="tutor-edit-profile-btn"
          onPress={() => router.push("/edit-tutor")}
          style={{ marginTop: theme.space.xl, backgroundColor: theme.color.brand, height: 52, borderRadius: theme.radius.pill, alignItems: "center", justifyContent: "center" }}
        >
          <Text style={{ color: "#fff", fontWeight: "700", fontSize: theme.font.lg }}>Edit my public profile</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  headerWrap: { backgroundColor: theme.color.surface, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  searchBar: {
    marginHorizontal: theme.space.xl, marginTop: theme.space.sm,
    backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.pill,
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    flexDirection: "row", alignItems: "center", gap: theme.space.sm,
  },
  searchInput: { flex: 1, fontSize: theme.font.base, color: theme.color.onSurface, padding: 0 },
  chipsRow: { paddingVertical: theme.space.md, height: 56, flexGrow: 0 },
});

const cardStyles = StyleSheet.create({
  card: {},
  imageWrap: { width: "100%", aspectRatio: 1, borderRadius: theme.radius.lg, overflow: "hidden", backgroundColor: theme.color.surfaceSecondary },
  image: { width: "100%", height: "100%" },
  priceBadge: {
    position: "absolute", top: theme.space.md, right: theme.space.md,
    backgroundColor: "rgba(255,255,255,0.92)", paddingHorizontal: theme.space.md, paddingVertical: 6,
    borderRadius: theme.radius.pill,
  },
  priceText: { fontWeight: "700", color: theme.color.onSurface, fontSize: theme.font.base },
  newBadge: {
    position: "absolute", top: theme.space.md, left: theme.space.md,
    backgroundColor: theme.color.brand, paddingHorizontal: theme.space.md, paddingVertical: 6,
    borderRadius: theme.radius.pill,
  },
  newBadgeText: { color: "#fff", fontWeight: "700", fontSize: 11, letterSpacing: 0.5, textTransform: "uppercase" },
  favBtn: {
    position: "absolute", bottom: theme.space.md, right: theme.space.md,
    width: 36, height: 36, borderRadius: 18, backgroundColor: "rgba(0,0,0,0.35)",
    alignItems: "center", justifyContent: "center",
  },
  name: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  meta: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, marginTop: 2 },
  langs: { color: theme.color.muted, fontSize: theme.font.sm, marginTop: 2 },
});

const dashStyles = StyleSheet.create({
  grid: { flexDirection: "row", gap: theme.space.md, marginTop: theme.space.xl },
  metric: { flex: 1, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, padding: theme.space.lg, gap: 6 },
  metricNum: { fontSize: 28, fontWeight: "700", color: theme.color.onSurface },
  metricLabel: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  empty: { backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, padding: theme.space.lg },
  bookRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: theme.space.lg, backgroundColor: theme.color.surfaceSecondary,
    borderRadius: theme.radius.lg, marginBottom: theme.space.sm,
  },
});
