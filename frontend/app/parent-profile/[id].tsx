import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { Image } from "expo-image";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { apiFetch, fileUrl } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { flagFor } from "@/src/flags";
import { StaticMap } from "@/src/staticmap";

interface Child { id: string; name: string; age: number; avatar_url?: string | null }
interface Parent {
  user_id: string; name: string; avatar_url?: string | null; city: string;
  latitude?: number | null; longitude?: number | null;
  languages_desired: string[]; hours_per_week: number; learning_materials: string; children: Child[];
}

export default function ParentPublic() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const [parent, setParent] = useState<Parent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    apiFetch<Parent>(`/parents/${id}/public`)
      .then(setParent)
      .catch((e) => setError(e?.message || "Family profile not found"))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (!parent) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.header}>
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} hitSlop={12} testID="parent-public-back" accessibilityRole="button" accessibilityLabel="Go back">
            <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
          </Pressable>
          <Text style={styles.headerTitle}>Family profile</Text>
          <View style={{ width: 22 }} />
        </View>
        <View style={styles.center} testID="parent-public-locked">
          <Feather name="lock" size={28} color={theme.color.brand} />
          <Text style={{ color: theme.color.onSurfaceSecondary, textAlign: "center", marginTop: theme.space.md, paddingHorizontal: theme.space.xl }}>
            {error || "Family profile not found"}
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  const isOwner = user?.id === parent.user_id;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} hitSlop={12} testID="parent-public-back" accessibilityRole="button" accessibilityLabel="Go back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Family profile</Text>
        {!isOwner && user && !user.is_admin ? (
          <Pressable
            onPress={() => router.push(`/block/${parent.user_id}?name=${encodeURIComponent(parent.name)}&from=profile`)}
            hitSlop={12}
            testID="parent-block-btn"
            accessibilityLabel="Block family"
          >
            <Feather name="slash" size={20} color={theme.color.error} />
          </Pressable>
        ) : <View style={{ width: 22 }} />}
      </View>

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: theme.space.xl, paddingBottom: insets.bottom + theme.space["3xl"] }}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.heroCard}>
          {parent.avatar_url ? (
            <Image source={{ uri: fileUrl(parent.avatar_url) }} style={styles.avatar} contentFit="cover" />
          ) : (
            <View style={[styles.avatar, styles.avatarFallback]}>
              <Text style={{ color: "#fff", fontWeight: "700", fontSize: 32 }}>{parent.name?.[0] ?? "?"}</Text>
            </View>
          )}
          <Text style={styles.name}>{parent.name}</Text>
          {parent.city ? <Text style={styles.city}>{parent.city}</Text> : null}
          {isOwner && <View style={styles.previewBadge}><Text style={styles.previewBadgeText}>Preview · this is how tutors see you</Text></View>}
        </View>

        <Text style={styles.section}>Looking for</Text>
        {parent.languages_desired.length ? (
          <View style={styles.langs}>
            {parent.languages_desired.map((l) => (
              <View key={l} style={styles.langChip}>
                <Text style={styles.langChipText}>{flagFor(l)}  {l}</Text>
              </View>
            ))}
          </View>
        ) : (
          <Text style={styles.muted}>Any language — open to suggestions</Text>
        )}

        <View style={styles.metaRow}>
          <View style={styles.metaCard}>
            <Feather name="clock" size={16} color={theme.color.brand} />
            <Text style={styles.metaNum}>{parent.hours_per_week}</Text>
            <Text style={styles.metaLabel}>hours / week</Text>
          </View>
          <View style={styles.metaCard}>
            <Feather name="users" size={16} color={theme.color.brand} />
            <Text style={styles.metaNum}>{parent.children.length}</Text>
            <Text style={styles.metaLabel}>{parent.children.length === 1 ? "child" : "children"}</Text>
          </View>
        </View>

        {parent.learning_materials ? (
          <>
            <Text style={styles.section}>Desired learning materials</Text>
            <Text style={styles.body}>{parent.learning_materials}</Text>
          </>
        ) : null}

        {(parent.latitude != null && parent.longitude != null) && (
          <>
            <Text style={styles.section}>Where they live</Text>
            <StaticMap
              latitude={parent.latitude}
              longitude={parent.longitude}
              caption={parent.city}
              height={180}
              zoom={11}
              testID="parent-map"
            />
          </>
        )}

        <Text style={styles.section}>Children</Text>
        {parent.children.length === 0 ? (
          <Text style={styles.muted}>No children listed yet.</Text>
        ) : (
          <View style={styles.childList}>
            {parent.children.map((c, i) => (
              <View key={c.id ?? i} style={styles.childCard} testID={`public-child-${i}`}>
                {isOwner && c.avatar_url ? (
                  <Image source={{ uri: fileUrl(c.avatar_url) }} style={styles.childAvatar} contentFit="cover" />
                ) : (
                  <View style={[styles.childAvatar, styles.avatarFallback]}>
                    <Feather name="user" size={22} color="#fff" />
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <Text style={styles.childName}>{c.name || "—"}</Text>
                  <Text style={styles.childAge}>{c.age} {c.age === 1 ? "year" : "years"} old</Text>
                </View>
              </View>
            ))}
            {!isOwner && (
              <View style={styles.privacyNote}>
                <Feather name="lock" size={14} color={theme.color.muted} />
                <Text style={styles.privacyText}>Photos of children are private and only visible to the family.</Text>
              </View>
            )}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  heroCard: { alignItems: "center", padding: theme.space.xl, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg },
  avatar: { width: 112, height: 112, borderRadius: 56, backgroundColor: theme.color.brand },
  avatarFallback: { alignItems: "center", justifyContent: "center", backgroundColor: theme.color.brand },
  name: { fontSize: 26, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.md, letterSpacing: -0.5 },
  city: { color: theme.color.onSurfaceSecondary, marginTop: 4, fontSize: theme.font.lg },
  previewBadge: { marginTop: theme.space.md, backgroundColor: theme.color.brand, paddingHorizontal: theme.space.md, paddingVertical: 6, borderRadius: theme.radius.pill },
  previewBadgeText: { color: "#fff", fontWeight: "700", fontSize: 12, letterSpacing: 0.5 },
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  langs: { flexDirection: "row", gap: theme.space.sm, flexWrap: "wrap" },
  langChip: { paddingHorizontal: theme.space.lg, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand },
  langChipText: { color: theme.color.brandDark, fontWeight: "600" },
  metaRow: { flexDirection: "row", gap: theme.space.md, marginTop: theme.space.xl },
  metaCard: { flex: 1, padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, gap: 4 },
  metaNum: { fontSize: 22, fontWeight: "700", color: theme.color.onSurface },
  metaLabel: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  body: { fontSize: theme.font.lg, color: theme.color.onSurface, lineHeight: 24 },
  muted: { color: theme.color.onSurfaceSecondary },
  childList: { gap: theme.space.sm },
  childCard: { flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md },
  childAvatar: { width: 52, height: 52, borderRadius: 26, borderWidth: 1, borderColor: theme.color.border },
  childName: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  childAge: { color: theme.color.onSurfaceSecondary, marginTop: 2 },
  privacyNote: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, marginTop: theme.space.md, padding: theme.space.md, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary },
  privacyText: { color: theme.color.onSurfaceSecondary, flex: 1, fontSize: theme.font.sm },
});
