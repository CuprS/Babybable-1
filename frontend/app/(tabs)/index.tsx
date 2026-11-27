import { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, ScrollView, ActivityIndicator, RefreshControl, TextInput, Switch } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useFocusEffect, useRouter } from "expo-router";
import Slider from "@react-native-community/slider";
import { apiFetch, Booking, fileUrl, MyVerification, Tutor } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { Chip, VerifiedBadge } from "@/src/ui";
import { MenuButton } from "@/src/drawer";
import { flagFor } from "@/src/flags";
import { track } from "@/src/analytics";
import { LiveMap, LiveMapMarker, MapRow, mapRowToPin } from "@/src/livemap";

const LANGUAGES = ["All", "Spanish", "French", "Japanese", "Mandarin", "German", "Arabic", "English", "Italian"];
const DISTANCE_STEPS = [10, 25, 50, 100, 250, 500, 1000];

export default function Explore() {
  const { user } = useAuth();
  const router = useRouter();
  const [tutors, setTutors] = useState<Tutor[]>([]);
  const [mapPins, setMapPins] = useState<LiveMapMarker[]>([]);
  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lang, setLang] = useState<string>("All");
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [maxMilesIdx, setMaxMilesIdx] = useState<number>(-1); // -1 means "Any distance"
  const [includeRemote, setIncludeRemote] = useState<boolean>(true);
  const [parentHasCoords, setParentHasCoords] = useState<boolean>(false);
  const [parentCity, setParentCity] = useState<string>("");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (lang !== "All") params.set("language", lang);
      if (debouncedQ.trim()) params.set("q", debouncedQ.trim());
      if (maxMilesIdx >= 0 && parentHasCoords) {
        params.set("max_miles", String(DISTANCE_STEPS[maxMilesIdx]));
        params.set("include_remote", String(includeRemote));
      }
      const qs = params.toString();
      const data = await apiFetch<Tutor[]>(`/tutors${qs ? `?${qs}` : ""}`);
      setTutors(data);
      if (debouncedQ.trim() || lang !== "All" || maxMilesIdx >= 0) {
        track("search", {
          query_length: debouncedQ.trim().length,
          result_count: data.length,
          language: lang,
          max_miles: maxMilesIdx >= 0 ? DISTANCE_STEPS[maxMilesIdx] : null,
          include_remote: includeRemote,
          source: "explore",
        });
      }
    } catch (e) {
      console.log("load tutors error", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [lang, debouncedQ, maxMilesIdx, includeRemote, parentHasCoords]);

  const loadFavs = useCallback(async () => {
    if (user?.role !== "parent") return;
    try { const ids = await apiFetch<string[]>("/favorites"); setFavs(new Set(ids)); } catch {}
  }, [user]);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => { loadFavs(); }, [loadFavs]);
  useEffect(() => {
    if (user?.role !== "parent") return;
    apiFetch<{ latitude?: number | null; longitude?: number | null; city?: string }>("/parents/me/profile")
      .then((p) => {
        setParentHasCoords(p.latitude != null && p.longitude != null);
        setParentCity(p.city || "");
      })
      .catch(() => {});
  }, [user]);
  useEffect(() => {
    apiFetch<MapRow[]>("/tutors/map")
      .then((rows) => setMapPins(rows.map((r) => mapRowToPin(r))))
      .catch(() => {});
  }, []);

  const toggleFav = async (id: string) => {
    const wasFav = favs.has(id);
    // Optimistic: flip the heart immediately, roll back if the request fails.
    const flip = (on: boolean) => setFavs((prev) => {
      const next = new Set(prev);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
    flip(!wasFav);
    try {
      await apiFetch(`/favorites/${id}`, { method: wasFav ? "DELETE" : "POST" });
      if (!wasFav) track("favorite_added", { tutor_id: id });
    } catch {
      flip(wasFav);
    }
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
        {user?.role === "parent" && (
          <View style={styles.distanceBar} testID="distance-filter">
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Feather name="map-pin" size={14} color={theme.color.brand} />
                <Text style={styles.distanceLabel} testID="distance-value">
                  {parentHasCoords
                    ? maxMilesIdx < 0
                      ? "Any distance"
                      : `Within ${DISTANCE_STEPS[maxMilesIdx]} miles`
                    : "Set your city to filter by distance"}
                </Text>
              </View>
              {parentHasCoords && (
                <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                  <Text style={styles.remoteLabel}>Include remote</Text>
                  <Switch
                    testID="distance-include-remote"
                    value={includeRemote}
                    onValueChange={setIncludeRemote}
                    trackColor={{ true: theme.color.brand, false: theme.color.borderStrong }}
                    thumbColor="#fff"
                  />
                </View>
              )}
            </View>
            {parentHasCoords ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.sm, marginTop: 4 }}>
                <Text style={styles.distanceEdge}>Any</Text>
                <Slider
                  testID="distance-slider"
                  style={{ flex: 1, height: 32 }}
                  minimumValue={-1}
                  maximumValue={DISTANCE_STEPS.length - 1}
                  step={1}
                  value={maxMilesIdx}
                  onSlidingComplete={(v) => setMaxMilesIdx(Math.round(v))}
                  minimumTrackTintColor={theme.color.brand}
                  maximumTrackTintColor={theme.color.borderStrong}
                  thumbTintColor={theme.color.brand}
                />
                <Text style={styles.distanceEdge}>1000mi</Text>
              </View>
            ) : (
              <Pressable
                onPress={() => router.push("/edit-parent")}
                style={{ marginTop: 6 }}
                testID="distance-add-city"
              >
                <Text style={styles.distanceCta}>Add your city →</Text>
              </Pressable>
            )}
            {parentHasCoords && !!parentCity && (
              <Text style={styles.distanceCaption}>Distances from {parentCity}</Text>
            )}
          </View>
        )}
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
            <View>
              {mapPins.length > 0 && (
                <View style={{ marginBottom: theme.space.lg }} testID="explore-map">
                  <Text style={{ fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface, marginBottom: theme.space.sm }}>Tutors near and far</Text>
                  <LiveMap
                    markers={mapPins}
                    height={220}
                    onPinPress={(id) => { track("map_pin_tap", { tutor_id: id }); router.push(`/tutor/${id}`); }}
                    testID="explore-live-map"
                  />
                  <Text style={{ color: theme.color.muted, fontSize: theme.font.sm, marginTop: 6 }}>
                    {mapPins.length} tutor{mapPins.length === 1 ? "" : "s"} on the map — use two fingers or click to move it, tap a pin to see who it is.
                  </Text>
                </View>
              )}
              <Text style={{ color: theme.color.onSurfaceSecondary, fontWeight: "600", marginBottom: theme.space.sm }} testID="tutor-count">
                {tutors.length} tutor{tutors.length === 1 ? "" : "s"}{lang !== "All" ? ` · ${flagFor(lang)} ${lang}` : ""}
              </Text>
            </View>
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
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Text style={[cardStyles.name, { flexShrink: 1 }]} numberOfLines={1}>{tutor.name}</Text>
            {tutor.verified && <VerifiedBadge />}
          </View>
          <Text style={cardStyles.meta} numberOfLines={1}>
            {tutor.location || "Location coming soon"}
            {tutor.distance_miles != null ? ` · ${tutor.distance_miles} mi` : ""}
          </Text>
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
  const { user } = useAuth();
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [loading, setLoading] = useState(true);
  const [verification, setVerification] = useState<MyVerification | null>(null);
  useFocusEffect(useCallback(() => {
    apiFetch<Booking[]>("/bookings/me").then(setBookings).catch(() => {}).finally(() => setLoading(false));
    apiFetch<MyVerification>("/tutors/me/verification").then(setVerification).catch(() => {});
  }, []));
  const paid = bookings.filter((b) => b.payment_status === "paid");
  // amount_cents is what the parent paid; the 1% platform fee isn't the tutor's money.
  const earnings = paid.reduce((a, b) => a + b.amount_cents - (b.platform_fee_cents ?? 0), 0);
  const today = new Date().toISOString().slice(0, 10);
  const requests = bookings.filter((b) => b.payment_status === "paid" && b.tutor_response === "pending");
  const upcoming = bookings
    .filter((b) => b.date >= today && b.payment_status !== "canceled" && b.payment_status !== "failed" && b.tutor_response !== "pending")
    .sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
  const firstName = user?.name?.split(" ")[0];
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.color.surface }} edges={["top"]}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: theme.space.md, paddingTop: theme.space.xs }}>
        <MenuButton tint={theme.color.onSurface} />
        <Text style={{ flex: 1, textAlign: "center", fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginRight: 40 }}>Dashboard</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: theme.space["3xl"] }}>
        <Text style={{ fontSize: 28, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5 }}>Welcome, {firstName || "tutor"}</Text>
        <Text style={{ color: theme.color.onSurfaceSecondary, marginTop: theme.space.xs }}>Here&apos;s your day at a glance.</Text>

        {verification && verification.status !== "verified" && (
          <Pressable onPress={() => router.push("/verify-tutor")} style={dashStyles.verifyCard} testID="tutor-verify-banner" accessibilityRole="button">
            <Feather name={verification.status === "pending" ? "clock" : "shield"} size={22} color={theme.color.brandDark} />
            <View style={{ flex: 1 }}>
              <Text style={dashStyles.verifyTitle}>
                {verification.status === "pending" ? "Verification in review" : verification.status === "rejected" ? "Verification needs another look" : "Get verified to start teaching"}
              </Text>
              <Text style={dashStyles.verifyBody}>
                {verification.status === "pending"
                  ? "We're checking your documents (usually 1–2 working days). Families can find and book you once you're approved."
                  : "Families can't find or book you until our team has checked your photo ID and background check."}
              </Text>
            </View>
            {verification.status !== "pending" && <Feather name="chevron-right" size={20} color={theme.color.brandDark} />}
          </Pressable>
        )}

        <View style={dashStyles.grid}>
          <View style={dashStyles.metric} testID="tutor-earnings-card">
            <Feather name="dollar-sign" size={18} color={theme.color.brand} />
            <Text style={dashStyles.metricNum}>${(earnings / 100).toFixed(0)}</Text>
            <Text style={dashStyles.metricLabel}>Earnings</Text>
          </View>
          <View style={dashStyles.metric} testID="tutor-sessions-card">
            <Feather name="calendar" size={18} color={theme.color.brand} />
            <Text style={dashStyles.metricNum}>{paid.length}</Text>
            <Text style={dashStyles.metricLabel}>Paid sessions</Text>
          </View>
        </View>

        {requests.length > 0 && (
          <>
            <Text style={dashStyles.section}>Needs your answer</Text>
            {requests.map((b) => (
              <Pressable key={b.id} style={[dashStyles.bookRow, dashStyles.requestRow]} onPress={() => router.push(`/booking-detail/${b.id}`)}
                testID={`tutor-request-${b.id}`} accessibilityRole="button" accessibilityLabel={`Booking request from ${b.parent_name}, ${b.date} at ${b.time}. Open to accept or decline.`}>
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "700", color: theme.color.brandDark, fontSize: theme.font.lg }}>{b.parent_name} · {b.language}</Text>
                  <Text style={{ color: theme.color.brandDark, marginTop: 2 }}>{b.date} at {b.time} · {b.duration_minutes} min</Text>
                </View>
                <Text style={{ color: theme.color.brandDark, fontWeight: "700" }}>Accept or decline ›</Text>
              </Pressable>
            ))}
          </>
        )}

        <Text style={dashStyles.section}>Upcoming</Text>
        {loading ? (
          <ActivityIndicator color={theme.color.brand} />
        ) : upcoming.length === 0 ? (
          <View style={dashStyles.empty}>
            <Text style={{ color: theme.color.onSurfaceSecondary }}>
              {bookings.length === 0 ? "No bookings yet. Update your profile to attract parents." : "Nothing coming up right now."}
            </Text>
          </View>
        ) : (
          upcoming.slice(0, 5).map((b) => (
            <Pressable key={b.id} style={dashStyles.bookRow} onPress={() => router.push(`/booking-detail/${b.id}`)} testID={`tutor-booking-${b.id}`}>
              <View>
                <Text style={{ fontWeight: "700", color: theme.color.onSurface }}>{b.parent_name} · {b.language}</Text>
                <Text style={{ color: theme.color.onSurfaceSecondary, marginTop: 2 }}>{b.date} at {b.time} · {b.duration_minutes} min</Text>
              </View>
              <Text style={{ color: theme.color.brand, fontWeight: "700" }}>${((b.amount_cents - (b.platform_fee_cents ?? 0)) / 100).toFixed(0)}</Text>
            </Pressable>
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
  chipsRow: { paddingVertical: theme.space.md, minHeight: 64, flexGrow: 0 },
  distanceBar: {
    paddingHorizontal: theme.space.xl,
    paddingBottom: theme.space.md,
    gap: 2,
  },
  distanceLabel: { color: theme.color.onSurface, fontWeight: "600", fontSize: theme.font.sm },
  remoteLabel: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginRight: 4 },
  distanceEdge: { color: theme.color.muted, fontSize: 12, minWidth: 34, textAlign: "center" },
  distanceCta: { color: theme.color.brand, fontWeight: "700" },
  distanceCaption: { color: theme.color.muted, fontSize: 12, textAlign: "right" },
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
  newBadgeText: { color: "#fff", fontWeight: "700", fontSize: 12, letterSpacing: 0.5, textTransform: "uppercase" },
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
  verifyCard: { flexDirection: "row", alignItems: "center", gap: theme.space.md, marginTop: theme.space.xl, padding: theme.space.lg, borderRadius: theme.radius.lg, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand },
  verifyTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.brandDark },
  verifyBody: { color: theme.color.brandDark, marginTop: 2, lineHeight: 20 },
  requestRow: { backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand, gap: theme.space.md },
  bookRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: theme.space.lg, backgroundColor: theme.color.surfaceSecondary,
    borderRadius: theme.radius.lg, marginBottom: theme.space.sm,
  },
});
