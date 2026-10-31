import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator } from "react-native";
import { Image } from "expo-image";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "./theme";
import { useToast } from "./toast";
import { apiFetch, fileUrl, BlogPost, PostStatus } from "./api";

const FILTERS: { key: PostStatus; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "published", label: "Published" },
  { key: "rejected", label: "Rejected" },
];

/** Admin dashboard section: review tutor blog submissions. */
export function AdminBlogPanel({ reloadKey }: { reloadKey: number }) {
  const router = useRouter();
  const { show: showToast } = useToast();
  const [status, setStatus] = useState<PostStatus>("pending");
  const [posts, setPosts] = useState<BlogPost[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPosts(await apiFetch<BlogPost[]>(`/admin/posts?status=${status}`));
    } catch {
      setPosts([]);
    }
  }, [status]);
  useEffect(() => { load(); }, [load, reloadKey]);

  const act = async (p: BlogPost, action: "publish" | "reject" | "unpublish") => {
    if (action === "reject" && !notes.trim()) {
      showToast({ kind: "error", title: "Add a note", body: "Tell the tutor what to change before rejecting." });
      return;
    }
    setBusy(action);
    try {
      await apiFetch(`/admin/posts/${p.id}/${action}`, {
        method: "POST",
        body: action === "unpublish" ? undefined : JSON.stringify({ reviewer_notes: notes.trim() }),
      });
      showToast({ kind: "success", title: action === "publish" ? "Published" : action === "reject" ? "Sent back to tutor" : "Unpublished" });
      setOpenId(null); setNotes("");
      load();
    } catch (e: any) {
      showToast({ kind: "error", title: "Action failed", body: e?.message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <View testID="admin-blog-panel">
      <Text style={styles.section}>Blog submissions</Text>
      <View style={styles.filters}>
        {FILTERS.map((f) => (
          <Pressable key={f.key} onPress={() => { setStatus(f.key); setOpenId(null); }} style={[styles.chip, status === f.key && styles.chipActive]} testID={`admin-blog-filter-${f.key}`}>
            <Text style={[styles.chipText, status === f.key && styles.chipTextActive]}>{f.label}</Text>
          </Pressable>
        ))}
      </View>
      {posts === null ? (
        <ActivityIndicator color={theme.color.brand} />
      ) : posts.length === 0 ? (
        <Text style={styles.muted}>No {status} articles.</Text>
      ) : posts.map((p) => {
        const open = openId === p.id;
        const photos = Array.from(new Set([p.cover_image_url, ...(p.image_urls || [])].filter(Boolean))) as string[];
        return (
          <View key={p.id} style={styles.card} testID={`admin-post-${p.id}`}>
            <Pressable onPress={() => { setOpenId(open ? null : p.id); setNotes(p.status === "rejected" ? p.reviewer_notes || "" : ""); }} style={styles.head} testID={`admin-post-toggle-${p.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.title} numberOfLines={2}>{p.title}</Text>
                <Text style={styles.meta}>{p.author_name}{p.tag ? ` · ${p.tag}` : ""} · {new Date(p.submitted_at).toLocaleDateString()} · {photos.length} photo{photos.length === 1 ? "" : "s"}</Text>
              </View>
              <Feather name={open ? "chevron-up" : "chevron-down"} size={18} color={theme.color.muted} />
            </Pressable>
            {open && (
              <View style={{ gap: theme.space.md, marginTop: theme.space.md }}>
                {photos.length > 0 && (
                  <View style={styles.photos}>
                    {photos.map((u) => <Image key={u} source={{ uri: fileUrl(u) }} style={styles.photo} contentFit="cover" />)}
                  </View>
                )}
                <Text style={styles.body} numberOfLines={12}>{p.body}</Text>
                <Pressable onPress={() => router.push(`/blog/${p.id}`)} testID={`admin-post-preview-${p.id}`}>
                  <Text style={styles.link}>Open full preview</Text>
                </Pressable>
                {p.status !== "published" ? (
                  <>
                    <TextInput
                      value={notes}
                      onChangeText={setNotes}
                      placeholder="Note to the tutor (required to reject)"
                      placeholderTextColor={theme.color.muted}
                      multiline
                      maxLength={600}
                      style={styles.notes}
                      testID={`admin-post-notes-${p.id}`}
                    />
                    <View style={styles.actions}>
                      <Pressable onPress={() => act(p, "reject")} disabled={!!busy} style={[styles.btn, styles.btnGhost]} testID={`admin-post-reject-${p.id}`}>
                        {busy === "reject" ? <ActivityIndicator color={theme.color.error} /> : <Text style={[styles.btnText, { color: theme.color.error }]}>Reject</Text>}
                      </Pressable>
                      <Pressable onPress={() => act(p, "publish")} disabled={!!busy} style={[styles.btn, styles.btnPrimary]} testID={`admin-post-publish-${p.id}`}>
                        {busy === "publish" ? <ActivityIndicator color={theme.color.onBrand} /> : <Text style={[styles.btnText, { color: theme.color.onBrand }]}>Publish</Text>}
                      </Pressable>
                    </View>
                  </>
                ) : (
                  <Pressable onPress={() => act(p, "unpublish")} disabled={!!busy} style={[styles.btn, styles.btnGhost]} testID={`admin-post-unpublish-${p.id}`}>
                    {busy === "unpublish" ? <ActivityIndicator color={theme.color.onSurface} /> : <Text style={styles.btnText}>Unpublish</Text>}
                  </Pressable>
                )}
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  filters: { flexDirection: "row", gap: theme.space.sm, marginBottom: theme.space.md },
  chip: { paddingHorizontal: theme.space.md, paddingVertical: 8, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.borderStrong },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.onSurface, fontWeight: "500" },
  chipTextActive: { color: theme.color.onBrand },
  muted: { color: theme.color.onSurfaceSecondary },
  card: { padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, marginBottom: theme.space.sm },
  head: { flexDirection: "row", alignItems: "center", gap: theme.space.sm },
  title: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  meta: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: 4 },
  photos: { flexDirection: "row", gap: theme.space.sm },
  photo: { flex: 1, aspectRatio: 4 / 3, borderRadius: theme.radius.md },
  body: { color: theme.color.onSurface, lineHeight: 20 },
  link: { color: theme.color.brandDark, fontWeight: "700", textDecorationLine: "underline" },
  notes: { minHeight: 64, borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.md, padding: theme.space.md, backgroundColor: theme.color.surface, color: theme.color.onSurface, textAlignVertical: "top" },
  actions: { flexDirection: "row", gap: theme.space.sm },
  btn: { flex: 1, minHeight: 44, borderRadius: theme.radius.pill, alignItems: "center", justifyContent: "center", paddingHorizontal: theme.space.lg },
  btnPrimary: { backgroundColor: theme.color.brand },
  btnGhost: { borderWidth: 1, borderColor: theme.color.borderStrong, backgroundColor: theme.color.surface },
  btnText: { fontWeight: "700", color: theme.color.onSurface },
});
