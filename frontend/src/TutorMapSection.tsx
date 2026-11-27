// "Tutors near you" on the landing page: the live map of verified tutors, shown when visitors
// scroll down past the welcome screen. Public, so it shows first names, the city and the rate
// only. With no verified tutors yet, the map still shows, with a friendly note on top.
import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { apiFetch } from "./api";
import { LiveMap, LiveMapMarker, MapRow, mapRowToPin } from "./livemap";
import { theme } from "./theme";
import { Button } from "./ui";
import { track } from "./analytics";

export function TutorMapSection() {
  const router = useRouter();
  const { width, height } = useWindowDimensions();
  const [pins, setPins] = useState<LiveMapMarker[] | null>(null);

  useEffect(() => {
    apiFetch<MapRow[]>("/tutors/map")
      .then((rows) => setPins(rows.map((r) => mapRowToPin(r, { firstNameOnly: true }))))
      .catch(() => setPins([]));
  }, []);

  const tutorCount = pins ? new Set(pins.map((p) => p.id)).size : 0;
  const cityCount = pins ? new Set(pins.map((p) => p.location || `${p.latitude},${p.longitude}`)).size : 0;
  const mapHeight = Math.round(Math.min(Math.max(height * 0.55, 320), 520));
  const wide = width >= 720;

  return (
    <View style={styles.section} testID="landing-map-section" nativeID="tutor-map">
      <View style={[styles.inner, wide && styles.innerWide]}>
        <Text style={styles.eyebrow}>Tutors near you</Text>
        <Text style={styles.title} accessibilityRole="header">Find a tutor in your city — or online</Text>
        <Text style={styles.lead}>
          Every tutor on the map has passed our identity and background check. Tap a pin to meet them.
        </Text>

        <View style={styles.mapWrap}>
          {pins === null ? (
            <View style={[styles.loading, { height: mapHeight }]}><ActivityIndicator color={theme.color.brand} /></View>
          ) : (
            <LiveMap
              markers={pins}
              height={mapHeight}
              title="Map of verified Babybabel tutors"
              testID="landing-live-map"
              onPinPress={(id) => { track("map_pin_tap", { tutor_id: id, source: "landing" }); router.push(`/tutor/${id}`); }}
            />
          )}
          {pins !== null && pins.length === 0 ? (
            <View style={styles.emptyNote} pointerEvents="none" testID="landing-map-empty">
              <Feather name="map-pin" size={22} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>Our first verified tutors are joining now</Text>
              <Text style={styles.emptyText}>Create a free account and we&apos;ll show you who&apos;s near you as they join.</Text>
            </View>
          ) : null}
        </View>

        {tutorCount > 0 ? (
          <Text style={styles.count} testID="landing-map-count">
            {tutorCount} verified tutor{tutorCount === 1 ? "" : "s"} in {cityCount} {cityCount === 1 ? "place" : "places"}
          </Text>
        ) : null}

        <View style={[styles.ctas, wide && styles.ctasWide]}>
          <Button
            title="Find a tutor near me"
            testID="landing-map-find"
            onPress={() => router.push({ pathname: "/(auth)/signup", params: { role: "parent" } })}
            style={wide ? { flex: 1 } : undefined}
          />
          <Button
            title="I want to teach"
            variant="secondary"
            testID="landing-map-teach"
            onPress={() => router.push({ pathname: "/(auth)/signup", params: { role: "tutor" } })}
            style={wide ? { flex: 1 } : undefined}
          />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { backgroundColor: theme.color.surface, paddingVertical: theme.space["2xl"], paddingHorizontal: theme.space.xl },
  inner: { width: "100%", alignSelf: "center", gap: theme.space.md },
  innerWide: { maxWidth: 960 },
  eyebrow: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.base, textTransform: "uppercase", letterSpacing: 1 },
  title: { color: theme.color.onSurface, fontSize: 30, fontWeight: "700", lineHeight: 36, letterSpacing: -0.5 },
  lead: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.lg, lineHeight: 24 },
  mapWrap: { marginTop: theme.space.sm, position: "relative" },
  loading: { borderRadius: theme.radius.lg, backgroundColor: theme.color.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  emptyNote: {
    position: "absolute", left: theme.space.lg, right: theme.space.lg, bottom: theme.space.lg,
    backgroundColor: theme.color.surface, borderRadius: theme.radius.md, padding: theme.space.lg, gap: 4,
    shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 10, shadowOffset: { width: 0, height: 2 }, elevation: 3,
  },
  emptyTitle: { color: theme.color.onSurface, fontSize: theme.font.lg, fontWeight: "700" },
  emptyText: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, lineHeight: 20 },
  count: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, fontWeight: "600" },
  ctas: { gap: theme.space.md, marginTop: theme.space.md },
  ctasWide: { flexDirection: "row" },
});
