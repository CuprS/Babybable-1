import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { theme } from "@/src/theme";
import { apiFetch, fileUrl, BlogPost, readMinutes } from "@/src/api";
import Head from "expo-router/head";

const STATUS_LABEL: Record<string, string> = { pending: "Awaiting review", rejected: "Needs revisions", published: "Published" };

export default function BlogPostScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [post, setPost] = useState<BlogPost | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<BlogPost>(`/posts/${id}`).then(setPost).catch((e) => setError(e?.message || "Article not found"));
  }, [id]);

  const photos = post ? Array.from(new Set([post.cover_image_url, ...(post.image_urls || [])].filter(Boolean))) as string[] : [];
  const [hero, ...rest] = photos;

  return (
    <View style={{ flex: 1, backgroundColor: theme.color.surface }} testID="blog-detail-screen">
      {post && (
        <Head>
          <title>{`${post.title} | Babybabel`}</title>
          <meta name="description" content={(post.excerpt || post.title).slice(0, 160)} />
        </Head>
      )}
      <SafeAreaView edges={["top"]} style={styles.headerBar}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/blog"))} hitSlop={12} testID="blog-detail-back" accessibilityRole="button" accessibilityLabel="Go back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle} numberOfLines={1}>Blog</Text>
        <View style={{ width: 22 }} />
      </SafeAreaView>
      {!post && !error ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.space["2xl"] }} />
      ) : error ? (
        <Text style={styles.error}>{error}</Text>
      ) : post ? (
        <ScrollView contentContainerStyle={{ paddingBottom: theme.space["3xl"] }}>
          {hero ? <Image source={{ uri: fileUrl(hero) }} style={styles.hero} contentFit="cover" transition={200} testID="blog-detail-hero" /> : null}
          <View style={{ padding: theme.space.xl }}>
            {post.status !== "published" && (
              <View style={styles.statusPill} testID="blog-detail-status">
                <Text style={styles.statusText}>{STATUS_LABEL[post.status]}</Text>
              </View>
            )}
            {post.tag ? <Text style={styles.tag}>{post.tag}</Text> : null}
            <Text style={styles.title} testID="blog-detail-title">{post.title}</Text>
            <View style={styles.byline}>
              {post.author_avatar_url ? (
                <Image source={{ uri: fileUrl(post.author_avatar_url) }} style={styles.avatar} />
              ) : (
                <View style={[styles.avatar, styles.avatarFallback]}><Text style={styles.avatarLetter}>{post.author_name[0]}</Text></View>
              )}
              <Text style={styles.meta}>
                {post.author_name} · {readMinutes(post.body)} min read
                {post.published_at ? ` · ${new Date(post.published_at).toLocaleDateString()}` : ""}
              </Text>
            </View>
            <Text style={styles.body} testID="blog-detail-body">{post.body}</Text>
            {rest.map((p) => (
              <Image key={p} source={{ uri: fileUrl(p) }} style={styles.inline} contentFit="cover" transition={200} testID="blog-detail-photo" />
            ))}
          </View>
        </ScrollView>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  headerBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { flex: 1, textAlign: "center", fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  error: { color: theme.color.onSurfaceSecondary, textAlign: "center", marginTop: theme.space["2xl"] },
  hero: { width: "100%", aspectRatio: 4 / 3 },
  statusPill: { alignSelf: "flex-start", backgroundColor: theme.color.brandSoft, paddingHorizontal: theme.space.md, paddingVertical: 4, borderRadius: theme.radius.pill, marginBottom: theme.space.md },
  statusText: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.sm },
  tag: { color: theme.color.brand, fontWeight: "700", fontSize: 13, letterSpacing: 1, textTransform: "uppercase" },
  title: { fontSize: 28, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5, marginTop: theme.space.xs, lineHeight: 34 },
  byline: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, marginTop: theme.space.lg, marginBottom: theme.space.xl },
  avatar: { width: 32, height: 32, borderRadius: 16 },
  avatarFallback: { backgroundColor: theme.color.brandSoft, alignItems: "center", justifyContent: "center" },
  avatarLetter: { color: theme.color.brandDark, fontWeight: "700" },
  meta: { flex: 1, color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  body: { color: theme.color.onSurface, fontSize: theme.font.lg, lineHeight: 26 },
  inline: { width: "100%", aspectRatio: 4 / 3, borderRadius: theme.radius.lg, marginTop: theme.space.xl },
});
