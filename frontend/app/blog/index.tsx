import { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Platform, Linking, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/theme";
import { MenuButton } from "@/src/drawer";
import { useAuth } from "@/src/auth";
import { apiFetch, fileUrl, BlogPost } from "@/src/api";
import { Chip } from "@/src/ui";

export default function Blog() {
  const router = useRouter();
  const { user } = useAuth();
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setPosts(await apiFetch<BlogPost[]>("/posts"));
    } catch (e: any) {
      setError(e?.message || "Couldn't load articles");
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const tags = useMemo(() => Array.from(new Set(posts.map((p) => p.tag).filter(Boolean))), [posts]);
  const shown = tag ? posts.filter((p) => p.tag === tag) : posts;
  const isTutor = user?.role === "tutor";

  return (
    <View style={{ flex: 1, backgroundColor: theme.color.surface }} testID="blog-screen">
      <SafeAreaView edges={["top"]} style={styles.headerBar}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} hitSlop={12} testID="blog-back" accessibilityRole="button" accessibilityLabel="Go back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Blog</Text>
        <MenuButton tint={theme.color.onSurface} />
      </SafeAreaView>
      <ScrollView
        contentContainerStyle={{ padding: theme.space.xl, paddingBottom: theme.space["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
      >
        <Text style={styles.eyebrow}>Stories · guides · tutor voices</Text>
        <Text style={styles.title}>The Babybabel Journal</Text>

        {isTutor && (
          <View style={styles.cta} testID="blog-tutor-cta">
            <View style={{ flex: 1 }}>
              <Text style={styles.ctaTitle}>Share what works in your lessons</Text>
              <Text style={styles.ctaSub}>Write an article — our team reviews it before it goes live.</Text>
            </View>
            <View style={{ gap: theme.space.sm }}>
              <Pressable onPress={() => router.push("/blog/compose")} style={styles.ctaBtn} testID="blog-write-btn">
                <Feather name="edit-3" size={14} color={theme.color.onBrand} />
                <Text style={styles.ctaBtnText}>Write</Text>
              </Pressable>
              <Pressable onPress={() => router.push("/blog/me")} hitSlop={8} testID="blog-my-articles-btn">
                <Text style={styles.ctaLink}>My articles</Text>
              </Pressable>
            </View>
          </View>
        )}

        {tags.length > 1 && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: theme.space.xl }} contentContainerStyle={{ gap: theme.space.sm }}>
            <Chip label="All" selected={!tag} onPress={() => setTag(null)} testID="blog-tag-all" />
            {tags.map((t) => (
              <Chip key={t} label={t} selected={tag === t} onPress={() => setTag(t)} testID={`blog-tag-${t}`} />
            ))}
          </ScrollView>
        )}

        {loading ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.space["2xl"] }} />
        ) : error ? (
          <View style={styles.empty}>
            <Text style={styles.emptyText}>{error}</Text>
            <Pressable onPress={load} testID="blog-retry"><Text style={styles.ctaLink}>Try again</Text></Pressable>
          </View>
        ) : shown.length === 0 ? (
          <View style={styles.empty}><Text style={styles.emptyText}>No articles yet — check back soon.</Text></View>
        ) : (
          <View style={{ gap: theme.space.xl, marginTop: theme.space.xl }}>
            {shown.map((p) => {
              const cover = fileUrl(p.cover_image_url || p.image_urls?.[0]);
              return (
                <Pressable key={p.id} style={styles.card} onPress={() => router.push(`/blog/${p.id}`)} testID={`blog-post-${p.id}`}>
                  {cover ? <Image source={{ uri: cover }} style={styles.img} contentFit="cover" transition={200} /> : null}
                  <View style={{ padding: theme.space.md }}>
                    {p.tag ? <Text style={styles.tag}>{p.tag}</Text> : null}
                    <Text style={styles.cardTitle}>{p.title}</Text>
                    <Text style={styles.excerpt} numberOfLines={3}>{p.excerpt}</Text>
                    <Text style={styles.read}>By {p.author_name}{p.published_at ? ` · ${new Date(p.published_at).toLocaleDateString()}` : ""}</Text>
                  </View>
                </Pressable>
              );
            })}
          </View>
        )}

        <View style={styles.footer}>
          {Platform.OS === "web" && (
            <Pressable onPress={() => Linking.openURL("https://expo.dev/")} style={styles.download} testID="blog-download">
              <Feather name="download" size={16} color={theme.color.brand} />
              <Text style={styles.downloadText}>Download the app</Text>
            </Pressable>
          )}
          <Pressable onPress={() => router.push("/privacy")}><Text style={styles.privacy}>Privacy Policy</Text></Pressable>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  headerBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.lg, paddingVertical: theme.space.sm, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { flex: 1, textAlign: "center", fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  eyebrow: { color: theme.color.brand, fontWeight: "700", letterSpacing: 1, textTransform: "uppercase", fontSize: 12 },
  title: { fontSize: 32, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5, marginTop: theme.space.xs },
  cta: { flexDirection: "row", alignItems: "center", gap: theme.space.md, marginTop: theme.space.xl, padding: theme.space.lg, borderRadius: theme.radius.lg, backgroundColor: theme.color.brandSoft },
  ctaTitle: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.lg },
  ctaSub: { color: theme.color.onSurfaceSecondary, marginTop: 4, fontSize: theme.font.sm, lineHeight: 18 },
  ctaBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: theme.color.brand, paddingHorizontal: theme.space.lg, minHeight: 44, borderRadius: theme.radius.pill, justifyContent: "center" },
  ctaBtnText: { color: theme.color.onBrand, fontWeight: "700" },
  ctaLink: { color: theme.color.brandDark, fontWeight: "700", textAlign: "center", textDecorationLine: "underline" },
  empty: { marginTop: theme.space["2xl"], alignItems: "center", gap: theme.space.md },
  emptyText: { color: theme.color.onSurfaceSecondary, textAlign: "center" },
  card: { borderRadius: theme.radius.lg, overflow: "hidden", backgroundColor: theme.color.surfaceSecondary },
  img: { width: "100%", aspectRatio: 16 / 9 },
  tag: { color: theme.color.brand, fontWeight: "700", fontSize: 12, letterSpacing: 1, textTransform: "uppercase" },
  cardTitle: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.xs, lineHeight: 26 },
  excerpt: { color: theme.color.onSurfaceSecondary, marginTop: theme.space.sm, lineHeight: 20 },
  read: { color: theme.color.muted, marginTop: theme.space.md, fontSize: 12 },
  footer: { paddingTop: theme.space.xl, marginTop: theme.space.xl, borderTopColor: theme.color.border, borderTopWidth: StyleSheet.hairlineWidth, gap: theme.space.md },
  download: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, backgroundColor: theme.color.brandSoft, paddingHorizontal: theme.space.md, paddingVertical: theme.space.sm, borderRadius: theme.radius.pill, alignSelf: "flex-start" },
  downloadText: { color: theme.color.brandDark, fontWeight: "700" },
  privacy: { color: theme.color.onSurfaceSecondary, fontWeight: "600", textDecorationLine: "underline" },
});
