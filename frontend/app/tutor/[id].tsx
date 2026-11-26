import { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Dimensions } from "react-native";
import { Image } from "expo-image";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { LinearGradient } from "expo-linear-gradient";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { apiFetch, fileUrl, Tutor, Review } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { flagFor } from "@/src/flags";
import { StaticMap, MapMarker } from "@/src/staticmap";
import { VerifiedBadge } from "@/src/ui";
import { PrivateImage, openPrivateFile } from "@/src/privatefile";
import Head from "expo-router/head";

const { width: SCREEN_W } = Dimensions.get("window");

export default function TutorDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const [tutor, setTutor] = useState<Tutor | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [loading, setLoading] = useState(true);
  const [reviewFilter, setReviewFilter] = useState<"all" | "5" | "4+" | "3+" | "latest">("latest");
  const [reviewsExpanded, setReviewsExpanded] = useState(false);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      apiFetch<Tutor>(`/tutors/${id}`),
      apiFetch<Review[]>(`/reviews/tutor/${id}`),
    ]).then(([t, r]) => { setTutor(t); setReviews(r); }).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  const REVIEW_PAGE = 5;
  const filteredReviews = useMemo(() => {
    let list = [...reviews];
    if (reviewFilter === "5") list = list.filter((r) => r.rating === 5);
    else if (reviewFilter === "4+") list = list.filter((r) => r.rating >= 4);
    else if (reviewFilter === "3+") list = list.filter((r) => r.rating >= 3);
    // Latest = default newest-first (already from API), All = same.
    return list;
  }, [reviews, reviewFilter]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (!tutor) {
    return (
      <SafeAreaView style={styles.center}>
        <Text style={{ color: theme.color.onSurfaceSecondary, marginBottom: theme.space.lg }}>Tutor not found</Text>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} hitSlop={12} testID="tutor-notfound-back" accessibilityRole="button" accessibilityLabel="Go back">
          <Text style={{ color: theme.color.brandDark, fontWeight: "700", textDecorationLine: "underline" }}>Go back</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  return (
    <View style={styles.root} testID="tutor-detail-screen">
      <Head>
        <title>{`${tutor.name} — ${tutor.languages.join(", ") || "Language"} tutor | Babybabel`}</title>
        <meta name="description" content={(tutor.bio || `${tutor.name} teaches children while caring for them.`).slice(0, 160)} />
      </Head>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 160 }} showsVerticalScrollIndicator={false}>
        <View style={styles.heroWrap}>
          <Image source={{ uri: fileUrl(tutor.hero_image_url || tutor.avatar_url) }} style={styles.hero} contentFit="cover" />
          <LinearGradient colors={["rgba(0,0,0,0.4)", "rgba(0,0,0,0)"]} style={{ position: "absolute", top: 0, left: 0, right: 0, height: 120 }} />
        </View>

        <View style={styles.body}>
          <Text style={styles.name} accessibilityRole="header">{tutor.name}</Text>
          {tutor.verified && <View style={{ alignSelf: "flex-start", marginTop: 6 }}><VerifiedBadge large /></View>}
          <Text style={styles.location}>{(tutor.locations && tutor.locations.length ? tutor.locations.map((l) => l.name).join(" · ") : tutor.location) || "Location coming soon"}</Text>

          <View style={styles.stats}>
            <Stat icon="star" label={`${tutor.rating.toFixed(1)} · ${tutor.reviews_count} reviews`} />
            <Stat icon="clock" label={`$${(tutor.hourly_rate_cents / 100).toFixed(0)}/hr`} />
            <Stat icon="award" label={`${tutor.experience_years}y experience`} />
          </View>

          <Text style={styles.section}>Languages</Text>
          <View style={styles.langs}>
            {tutor.languages.map((l) => (
              <View key={l} style={styles.langChip}>
                <Text style={styles.langChipText}>{flagFor(l)}  {l}</Text>
              </View>
            ))}
          </View>

          <Text style={styles.section}>About me</Text>
          <Text style={styles.bio}>{tutor.bio}</Text>

          {tutor.allows_remote && (
            <View style={styles.remoteChip} testID="tutor-remote-badge">
              <Feather name="video" size={14} color={theme.color.brandDark} />
              <Text style={styles.remoteText}>Remote lessons available</Text>
            </View>
          )}

          <Text style={styles.section}>Where I&apos;m based</Text>
          <StaticMap
            latitude={tutor.latitude}
            longitude={tutor.longitude}
            markers={(tutor.locations || [])
              .filter((l) => l.latitude != null && l.longitude != null)
              .map((l): MapMarker => ({ latitude: l.latitude as number, longitude: l.longitude as number, label: l.name, color: "red" }))}
            caption={(tutor.locations || []).map((l) => l.name).join(" · ") || tutor.location}
            height={180}
            zoom={tutor.locations && tutor.locations.length > 1 ? 5 : 11}
            testID="tutor-map"
          />
          {tutor.locations && tutor.locations.length > 0 && (
            <View style={styles.locChipsRow}>
              {tutor.locations.map((l) => (
                <View key={l.name} style={styles.locChip}>
                  <Feather name="map-pin" size={12} color={theme.color.brandDark} />
                  <Text style={styles.locChipText}>{l.name}</Text>
                </View>
              ))}
            </View>
          )}

          {(tutor.accreditation_photo_url || tutor.accreditation_document_url || (tutor.accreditation_urls && tutor.accreditation_urls.length > 0)) && (
            <>
              <Text style={styles.section}>Accreditations</Text>
              <View style={styles.accredWrap}>
                {tutor.accreditation_photo_url && (
                  <PrivateImage path={tutor.accreditation_photo_url} style={styles.accredImg} />
                )}
                {/* Legacy list fallback */}
                {!tutor.accreditation_photo_url && tutor.accreditation_urls && tutor.accreditation_urls.slice(0, 1).map((u, i) => (
                  <Image key={i} source={{ uri: fileUrl(u) }} style={styles.accredImg} contentFit="cover" />
                ))}
                {tutor.accreditation_document_url && (
                  <Pressable
                    onPress={() => openPrivateFile(tutor.accreditation_document_url)}
                    style={styles.accredDoc}
                    testID="tutor-accred-doc"
                  >
                    <Feather name="file-text" size={28} color={theme.color.brand} />
                    <Text style={styles.accredDocTitle}>View credentials</Text>
                    <Text style={styles.accredDocMeta}>PDF · tap to open</Text>
                  </Pressable>
                )}
              </View>
            </>
          )}

          <View style={styles.reviewsHeader}>
            <Text style={[styles.section, { marginBottom: 0, marginTop: 0 }]}>Reviews {reviews.length > 0 ? `(${reviews.length})` : ""}</Text>
            {tutor.rating > 0 && (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                <Feather name="star" size={14} color={theme.color.brand} />
                <Text style={{ color: theme.color.onSurface, fontWeight: "700" }}>{tutor.rating.toFixed(1)}</Text>
              </View>
            )}
          </View>
          {reviews.length > 0 && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: theme.space.sm, paddingBottom: theme.space.sm }}>
              {(["latest", "all", "5", "4+", "3+"] as const).map((f) => {
                const label = f === "latest" ? "Latest" : f === "all" ? "All" : f === "5" ? "5★ only" : f === "4+" ? "4★ & up" : "3★ & up";
                const count = f === "5" ? reviews.filter((r) => r.rating === 5).length
                  : f === "4+" ? reviews.filter((r) => r.rating >= 4).length
                  : f === "3+" ? reviews.filter((r) => r.rating >= 3).length
                  : reviews.length;
                return (
                  <Pressable
                    key={f}
                    testID={`review-filter-${f}`}
                    onPress={() => { setReviewFilter(f); setReviewsExpanded(false); }}
                    style={[
                      styles.filterChip,
                      reviewFilter === f && styles.filterChipOn,
                    ]}
                  >
                    <Text style={[styles.filterChipText, reviewFilter === f && styles.filterChipTextOn]}>
                      {label} · {count}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          )}
          {reviews.length === 0 ? (
            <Text style={styles.muted}>No reviews yet. Be the first to book!</Text>
          ) : filteredReviews.length === 0 ? (
            <Text style={styles.muted}>No reviews matching this filter.</Text>
          ) : (
            <>
              {(reviewsExpanded ? filteredReviews : filteredReviews.slice(0, REVIEW_PAGE)).map((r) => (
                <View key={r.id} style={styles.reviewCard}>
                  <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                    <Text style={{ fontWeight: "700", color: theme.color.onSurface }}>{r.parent_name}</Text>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                      <Feather name="star" size={12} color={theme.color.brand} />
                      <Text style={{ color: theme.color.onSurface, fontWeight: "600" }}>{r.rating}</Text>
                    </View>
                  </View>
                  {r.comment ? <Text style={{ color: theme.color.onSurfaceSecondary, marginTop: 6 }}>{r.comment}</Text> : null}
                </View>
              ))}
              {filteredReviews.length > REVIEW_PAGE && (
                <Pressable
                  onPress={() => setReviewsExpanded((v) => !v)}
                  style={styles.showMore}
                  testID="reviews-show-more"
                >
                  <Text style={styles.showMoreText}>
                    {reviewsExpanded ? "Show less" : `Show all ${filteredReviews.length} reviews`}
                  </Text>
                  <Feather name={reviewsExpanded ? "chevron-up" : "chevron-down"} size={16} color={theme.color.brand} />
                </Pressable>
              )}
            </>
          )}
        </View>
      </ScrollView>

      <SafeAreaView edges={["top"]} style={styles.topBar}>
        <Pressable onPress={() => router.back()} style={styles.iconBtn} testID="tutor-back-btn">
          <Feather name="arrow-left" size={22} color="#fff" />
        </Pressable>
        <View style={{ flex: 1 }} />
        {user && !user.is_admin && user.id !== tutor.user_id && (
          <Pressable
            onPress={() => router.push(`/block/${tutor.user_id}?name=${encodeURIComponent(tutor.name)}&from=profile`)}
            style={styles.iconBtn}
            testID="tutor-block-btn"
            accessibilityLabel="Block tutor"
          >
            <Feather name="slash" size={20} color="#fff" />
          </Pressable>
        )}
        <Pressable
          onPress={() => user && router.push(`/chat/${tutor.user_id}?name=${encodeURIComponent(tutor.name)}`)}
          style={styles.iconBtn}
          testID="tutor-message-btn"
        >
          <Feather name="message-circle" size={22} color="#fff" />
        </Pressable>
      </SafeAreaView>

      {user?.role === "parent" && (
        <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, theme.space.lg) }]}>
          <View>
            <Text style={styles.priceLarge}>${(tutor.hourly_rate_cents / 100).toFixed(0)}<Text style={{ fontSize: theme.font.base, color: theme.color.onSurfaceSecondary, fontWeight: "500" }}> / hour</Text></Text>
            <Text style={{ color: theme.color.onSurfaceSecondary }}>Includes childcare + language</Text>
          </View>
          <Pressable
            testID="tutor-book-btn"
            onPress={() => router.push(`/booking/${tutor.id}`)}
            style={styles.bookBtn}
          >
            <Text style={styles.bookBtnText}>Book session</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

function Stat({ icon, label }: { icon: any; label: string }) {
  return (
    <View style={styles.stat}>
      <Feather name={icon} size={16} color={theme.color.brand} />
      <Text style={styles.statText}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  heroWrap: { width: SCREEN_W, height: SCREEN_W * 0.85, backgroundColor: theme.color.surfaceSecondary },
  hero: { width: "100%", height: "100%" },
  body: { padding: theme.space.xl },
  name: { fontSize: 28, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5 },
  location: { color: theme.color.onSurfaceSecondary, marginTop: 4, fontSize: theme.font.lg },
  stats: { flexDirection: "row", gap: theme.space.lg, marginTop: theme.space.xl, flexWrap: "wrap" },
  stat: { flexDirection: "row", alignItems: "center", gap: 6 },
  statText: { color: theme.color.onSurface, fontWeight: "500" },
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  langs: { flexDirection: "row", gap: theme.space.sm, flexWrap: "wrap" },
  langChip: { paddingHorizontal: theme.space.lg, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand },
  langChipText: { color: theme.color.brandDark, fontWeight: "600" },
  remoteChip: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", paddingHorizontal: theme.space.md, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand, marginTop: theme.space.md },
  remoteText: { color: theme.color.brandDark, fontWeight: "700" },
  bio: { fontSize: theme.font.lg, color: theme.color.onSurface, lineHeight: 24 },
  accredImg: { width: 160, height: 220, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary },
  accredWrap: { flexDirection: "row", gap: theme.space.md, flexWrap: "wrap" },
  accredDoc: { width: 160, height: 220, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary, alignItems: "center", justifyContent: "center", gap: 6, padding: theme.space.md, borderWidth: 1, borderColor: theme.color.borderStrong },
  accredDocTitle: { color: theme.color.onSurface, fontWeight: "700", fontSize: theme.font.lg, textAlign: "center" },
  accredDocMeta: { color: theme.color.muted, fontSize: theme.font.sm },
  locChipsRow: { flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm, marginTop: theme.space.md },
  locChip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: theme.space.md, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand },
  locChipText: { color: theme.color.brandDark, fontWeight: "600", fontSize: 13 },
  reviewCard: { padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, marginBottom: theme.space.sm },
  reviewsHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: theme.space["2xl"],
    marginBottom: theme.space.md,
  },
  filterChip: {
    paddingHorizontal: theme.space.md, paddingVertical: 8,
    borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.borderStrong,
    backgroundColor: theme.color.surface,
  },
  filterChipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterChipText: { color: theme.color.onSurface, fontWeight: "600", fontSize: theme.font.sm },
  filterChipTextOn: { color: "#fff" },
  showMore: {
    flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6,
    paddingVertical: theme.space.md,
  },
  showMoreText: { color: theme.color.brand, fontWeight: "700", fontSize: theme.font.base },
  muted: { color: theme.color.onSurfaceSecondary },
  topBar: {
    position: "absolute", top: 0, left: 0, right: 0,
    flexDirection: "row", justifyContent: "space-between",
    paddingHorizontal: theme.space.lg,
  },
  iconBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: "rgba(0,0,0,0.35)", alignItems: "center", justifyContent: "center", margin: theme.space.sm },
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    padding: theme.space.lg,
    backgroundColor: theme.color.surface,
    borderTopWidth: 1, borderTopColor: theme.color.border,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  priceLarge: { fontSize: 22, fontWeight: "700", color: theme.color.onSurface },
  bookBtn: { backgroundColor: theme.color.brand, borderRadius: theme.radius.pill, paddingHorizontal: theme.space.xl, height: 52, alignItems: "center", justifyContent: "center" },
  bookBtnText: { color: "#fff", fontWeight: "700", fontSize: theme.font.lg },
});
