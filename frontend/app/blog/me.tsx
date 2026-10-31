import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Alert, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/toast";
import { apiFetch, fileUrl, BlogPost, PostStatus } from "@/src/api";
import { Button } from "@/src/ui";

const STATUS: Record<PostStatus, { label: string; icon: any; color: string }> = {
  pending: { label: "In review", icon: "clock", color: theme.color.warning },
  published: { label: "Published", icon: "check-circle", color: theme.color.success },
  rejected: { label: "Needs revisions", icon: "alert-circle", color: theme.color.error },
};

function confirm(title: string, msg: string): Promise<boolean> {
  if (Platform.OS === "web") return Promise.resolve(window.confirm(`${title}\n\n${msg}`));
  return new Promise((res) => Alert.alert(title, msg, [
    { text: "Cancel", style: "cancel", onPress: () => res(false) },
    { text: "Delete", style: "destructive", onPress: () => res(true) },
  ]));
}

export default function MyPosts() {
  const router = useRouter();
  const { user } = useAuth();
  const { show: showToast } = useToast();
  const [posts, setPosts] = useState<BlogPost[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setPosts(await apiFetch<BlogPost[]>("/posts/me"));
    } catch (e: any) {
      setPosts([]);
      showToast({ kind: "error", title: "Couldn't load your articles", body: e?.message });
    } finally {
      setRefreshing(false);
    }
  }, [showToast]);

  useFocusEffect(useCallback(() => { if (user?.role === "tutor") load(); }, [load, user?.role]));

  const remove = async (p: BlogPost) => {
    if (!(await confirm("Delete article?", `"${p.title}" will be removed permanently.`))) return;
    try {
      await apiFetch(`/posts/${p.id}`, { method: "DELETE" });
      setPosts((prev) => (prev || []).filter((x) => x.id !== p.id));
    } catch (e: any) {
      showToast({ kind: "error", title: "Couldn't delete", body: e?.message });
    }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]} testID="my-posts-screen">
      <View style={styles.headerBar}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/blog"))} hitSlop={12} testID="my-posts-back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>My articles</Text>
        {user?.role === "tutor" ? (
          <Pressable onPress={() => router.push("/blog/compose")} hitSlop={12} testID="my-posts-new">
            <Feather name="plus" size={22} color={theme.color.brand} />
          </Pressable>
        ) : <View style={{ width: 22 }} />}
      </View>
      {user?.role !== "tutor" ? (
        <Text style={styles.empty}>Only tutors can submit articles.</Text>
      ) : posts === null ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.space["2xl"] }} />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: theme.space.xl, gap: theme.space.md, paddingBottom: theme.space["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
        >
          {posts.length === 0 ? (
            <View style={styles.emptyBox} testID="my-posts-empty">
              <Feather name="feather" size={28} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>No articles yet</Text>
              <Text style={styles.empty}>Share an activity or a story from your lessons with Babybabel families.</Text>
              <Button title="Write your first article" onPress={() => router.push("/blog/compose")} testID="my-posts-write-first" />
            </View>
          ) : posts.map((p) => {
            const s = STATUS[p.status];
            const cover = fileUrl(p.cover_image_url || p.image_urls?.[0]);
            return (
              <View key={p.id} style={styles.card} testID={`my-post-${p.id}`}>
                <Pressable onPress={() => router.push(`/blog/${p.id}`)} style={styles.row}>
                  {cover ? <Image source={{ uri: cover }} style={styles.thumb} contentFit="cover" /> : <View style={[styles.thumb, styles.thumbEmpty]}><Feather name="file-text" size={20} color={theme.color.muted} /></View>}
                  <View style={{ flex: 1 }}>
                    <Text style={styles.title} numberOfLines={2}>{p.title}</Text>
                    <View style={styles.statusRow}>
                      <Feather name={s.icon} size={13} color={s.color} />
                      <Text style={[styles.status, { color: s.color }]} testID={`my-post-status-${p.id}`}>{s.label}</Text>
                      <Text style={styles.date}>· {new Date(p.updated_at).toLocaleDateString()}</Text>
                    </View>
                  </View>
                </Pressable>
                {p.status === "rejected" && p.reviewer_notes ? (
                  <View style={styles.notes}><Text style={styles.notesText}>&ldquo;{p.reviewer_notes}&rdquo;</Text></View>
                ) : null}
                {p.status !== "published" && (
                  <View style={styles.actions}>
                    <Pressable onPress={() => router.push(`/blog/compose?id=${p.id}`)} style={styles.action} testID={`my-post-edit-${p.id}`}>
                      <Feather name="edit-2" size={14} color={theme.color.onSurface} />
                      <Text style={styles.actionText}>{p.status === "rejected" ? "Revise" : "Edit"}</Text>
                    </Pressable>
                    <Pressable onPress={() => remove(p)} style={styles.action} testID={`my-post-delete-${p.id}`}>
                      <Feather name="trash-2" size={14} color={theme.color.error} />
                      <Text style={[styles.actionText, { color: theme.color.error }]}>Delete</Text>
                    </Pressable>
                  </View>
                )}
              </View>
            );
          })}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  headerBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { flex: 1, textAlign: "center", fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  empty: { color: theme.color.onSurfaceSecondary, textAlign: "center", padding: theme.space.md },
  emptyBox: { alignItems: "center", gap: theme.space.sm, marginTop: theme.space["2xl"] },
  emptyTitle: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  card: { backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, padding: theme.space.md, gap: theme.space.sm },
  row: { flexDirection: "row", gap: theme.space.md, alignItems: "center" },
  thumb: { width: 64, height: 64, borderRadius: theme.radius.md },
  thumbEmpty: { backgroundColor: theme.color.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  statusRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  status: { fontWeight: "700", fontSize: theme.font.sm },
  date: { color: theme.color.muted, fontSize: theme.font.sm },
  notes: { backgroundColor: theme.color.surface, borderRadius: theme.radius.md, padding: theme.space.md },
  notesText: { color: theme.color.onSurfaceSecondary, fontStyle: "italic", lineHeight: 20 },
  actions: { flexDirection: "row", gap: theme.space.sm },
  action: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: theme.space.md, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface },
  actionText: { fontWeight: "600", color: theme.color.onSurface },
});
