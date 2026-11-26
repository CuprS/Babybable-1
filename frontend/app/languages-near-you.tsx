import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { LandingPage } from "@/src/landing";
import { apiFetch, Tutor } from "@/src/api";
import { flagFor } from "@/src/flags";
import { theme } from "@/src/theme";

const NEARBY_MILES = 50;

interface LangCount { language: string; tutors: number; nearby: number }

/** Real numbers only: languages taught by verified tutors, counted from the live tutor list. */
function countLanguages(tutors: Tutor[]): LangCount[] {
  const map = new Map<string, LangCount>();
  for (const t of tutors) {
    const near = t.distance_miles != null && t.distance_miles <= NEARBY_MILES;
    for (const raw of t.languages || []) {
      const language = raw.trim();
      if (!language) continue;
      const key = language.toLowerCase();
      const row = map.get(key) || { language, tutors: 0, nearby: 0 };
      row.tutors += 1;
      if (near) row.nearby += 1;
      map.set(key, row);
    }
  }
  return [...map.values()].sort((a, b) => b.nearby - a.nearby || b.tutors - a.tutors || a.language.localeCompare(b.language));
}

export default function LanguagesNearYou() {
  const router = useRouter();
  const [rows, setRows] = useState<LangCount[] | null>(null);
  const [hasDistance, setHasDistance] = useState(false);

  useEffect(() => {
    apiFetch<Tutor[]>("/tutors")
      .then((tutors) => {
        setHasDistance(tutors.some((t) => t.distance_miles != null));
        setRows(countLanguages(tutors));
      })
      .catch(() => setRows([]));
  }, []);

  return (
    <LandingPage
      testID="languages-near-you-screen"
      eyebrow="Explore"
      title="Languages near you"
      heroImage="https://images.unsplash.com/photo-1591123120675-6f7f1aae0e5b?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"
      intro={hasDistance
        ? `Languages taught by verified tutors, starting with the ones within ${NEARBY_MILES} miles of your city.`
        : "Languages taught by verified tutors on Babybabel. Sign in as a family and add your city to see what's near you."}
      cta={{ label: "Explore tutors", testID: "languages-cta", onPress: () => router.push("/(tabs)") }}
    >
      <View style={styles.wrap} testID="languages-list">
        {rows === null ? (
          <ActivityIndicator color={theme.color.brand} />
        ) : rows.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>No verified tutors yet</Text>
            <Text style={styles.emptyBody}>Tutors appear here once our team has checked their ID and background check.</Text>
            <Pressable onPress={() => router.push("/become-tutor")} accessibilityRole="link">
              <Text style={styles.link}>Teach a language on Babybabel →</Text>
            </Pressable>
          </View>
        ) : (
          rows.map((r) => (
            <View key={r.language} style={styles.row} testID={`language-${r.language.toLowerCase()}`}>
              <Text style={styles.flag}>{flagFor(r.language)}</Text>
              <Text style={styles.lang}>{r.language}</Text>
              <Text style={styles.count}>
                {hasDistance ? `${r.nearby} nearby · ` : ""}{r.tutors} tutor{r.tutors === 1 ? "" : "s"}
              </Text>
            </View>
          ))
        )}
      </View>
    </LandingPage>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: theme.space.xl, paddingBottom: theme.space.xl, gap: theme.space.sm },
  row: { flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.lg, borderRadius: theme.radius.lg, backgroundColor: theme.color.surfaceSecondary },
  flag: { fontSize: 22 },
  lang: { flex: 1, fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  count: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base },
  empty: { padding: theme.space.lg, borderRadius: theme.radius.lg, backgroundColor: theme.color.surfaceSecondary, gap: theme.space.xs },
  emptyTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  emptyBody: { color: theme.color.onSurfaceSecondary, lineHeight: 20 },
  link: { color: theme.color.brandDark, fontWeight: "700", marginTop: theme.space.sm },
});
