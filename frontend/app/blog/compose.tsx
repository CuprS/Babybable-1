import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, KeyboardAvoidingView, Platform, ActivityIndicator, Alert, Linking } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/toast";
import { apiFetch, apiUpload, fileUrl, BlogPost, BLOG_TAGS, MAX_POST_IMAGES } from "@/src/api";
import { Button, Chip, Input } from "@/src/ui";

export default function ComposePost() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { show: showToast } = useToast();
  const [title, setTitle] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const [body, setBody] = useState("");
  const [tag, setTag] = useState<string>("");
  const [images, setImages] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadingPost, setLoadingPost] = useState(!!id);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!id) return;
    apiFetch<BlogPost>(`/posts/${id}`)
      .then((p) => {
        setTitle(p.title); setExcerpt(p.excerpt); setBody(p.body); setTag(p.tag);
        setImages(p.image_urls || []); setNotes(p.status === "rejected" ? p.reviewer_notes || "" : "");
      })
      .catch((e) => showToast({ kind: "error", title: "Couldn't open article", body: e?.message }))
      .finally(() => setLoadingPost(false));
  }, [id, showToast]);

  if (authLoading) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.space["3xl"] }} />
      </SafeAreaView>
    );
  }

  if (user?.role !== "tutor") {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.gate} testID="compose-gate">
          <Feather name="edit-3" size={28} color={theme.color.brand} />
          <Text style={styles.gateTitle}>Tutors write for the blog</Text>
          <Text style={styles.gateSub}>{user ? "Only tutor accounts can submit articles, but you can read every published one." : "Sign in with a tutor account to submit an article."}</Text>
          <Button title={user ? "Back to the blog" : "Sign in"} onPress={() => router.replace(user ? "/blog" : "/(auth)/login")} testID="compose-gate-btn" />
        </View>
      </SafeAreaView>
    );
  }

  const pickPhoto = async () => {
    const remaining = MAX_POST_IMAGES - images.length;
    if (remaining <= 0) return;
    if (Platform.OS !== "web") {
      let perm = await ImagePicker.getMediaLibraryPermissionsAsync();
      if (!perm.granted && perm.canAskAgain) perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Photo access needed", "Allow photo access in Settings to add pictures to your article.", [
          { text: "Not now", style: "cancel" },
          { text: "Open Settings", onPress: () => Linking.openSettings() },
        ]);
        return;
      }
    }
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"], quality: 0.7, allowsMultipleSelection: remaining > 1, selectionLimit: remaining,
    });
    if (res.canceled) return;
    setUploading(true);
    try {
      const uploaded: string[] = [];
      for (const a of res.assets.slice(0, remaining)) {
        const up = await apiUpload(a.uri, a.fileName || "photo.jpg", a.mimeType || "image/jpeg");
        uploaded.push(up.path);
      }
      setImages((prev) => [...prev, ...uploaded].slice(0, MAX_POST_IMAGES));
    } catch (e: any) {
      showToast({ kind: "error", title: "Upload failed", body: e?.message || "Try again" });
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    if (title.trim().length < 4) return showToast({ kind: "error", title: "Add a title", body: "At least 4 characters." });
    if (body.trim().length < 40) return showToast({ kind: "error", title: "Keep writing", body: "Your article needs at least 40 characters." });
    setSaving(true);
    try {
      const payload = JSON.stringify({ title: title.trim(), excerpt: excerpt.trim(), body: body.trim(), tag, image_urls: images });
      if (id) await apiFetch(`/posts/${id}`, { method: "PATCH", body: payload });
      else await apiFetch("/posts", { method: "POST", body: payload });
      showToast({ kind: "success", title: "Sent for review", body: "We'll notify you once an admin reviews it." });
      router.dismissTo("/blog/me");
    } catch (e: any) {
      showToast({ kind: "error", title: "Couldn't submit", body: e?.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]} testID="compose-screen">
      <View style={styles.headerBar}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/blog"))} hitSlop={12} testID="compose-back" accessibilityRole="button" accessibilityLabel="Go back">
          <Feather name="x" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>{id ? "Edit article" : "New article"}</Text>
        <View style={{ width: 22 }} />
      </View>
      {loadingPost ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.space["2xl"] }} />
      ) : (
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
          <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
            {notes ? (
              <View style={styles.notes} testID="compose-reviewer-notes">
                <Text style={styles.notesTitle}>Admin feedback</Text>
                <Text style={styles.notesBody}>{notes}</Text>
              </View>
            ) : null}
            <Input label="Title" value={title} onChangeText={setTitle} maxLength={160} placeholder="e.g. Five songs that teach Spanish colours" testID="compose-title" />
            <View style={{ gap: 6 }}>
              <Text style={styles.label}>Topic</Text>
              <View style={styles.tags}>
                {BLOG_TAGS.map((t) => (
                  <Chip key={t} label={t} selected={tag === t} onPress={() => setTag(tag === t ? "" : t)} testID={`compose-tag-${t}`} />
                ))}
              </View>
            </View>
            <Input label="Short summary (optional)" value={excerpt} onChangeText={setExcerpt} maxLength={300} multiline placeholder="One or two lines shown on the blog list" style={{ minHeight: 64, textAlignVertical: "top" }} testID="compose-excerpt" />
            <Input label="Article" value={body} onChangeText={setBody} maxLength={20000} multiline placeholder="Share an activity, a story or a tip from your lessons…" style={{ minHeight: 220, textAlignVertical: "top" }} testID="compose-body" />
            <Text style={styles.counter}>{body.trim().length} characters · minimum 40</Text>

            <View style={{ gap: 6 }}>
              <Text style={styles.label}>Photos ({images.length}/{MAX_POST_IMAGES})</Text>
              <Text style={styles.hint}>The first photo becomes the cover. Avoid showing children&apos;s faces without permission.</Text>
              <View style={styles.photos}>
                {images.map((p, i) => (
                  <View key={p} style={styles.photo} testID={`compose-photo-${i}`}>
                    <Image source={{ uri: fileUrl(p) }} style={StyleSheet.absoluteFill} contentFit="cover" />
                    {i === 0 && <View style={styles.coverBadge}><Text style={styles.coverText}>Cover</Text></View>}
                    <Pressable onPress={() => setImages(images.filter((x) => x !== p))} style={styles.remove} hitSlop={8} testID={`compose-photo-remove-${i}`}>
                      <Feather name="x" size={14} color={theme.color.onBrand} />
                    </Pressable>
                  </View>
                ))}
                {images.length < MAX_POST_IMAGES && (
                  <Pressable onPress={pickPhoto} disabled={uploading} style={[styles.photo, styles.addPhoto]} testID="compose-add-photo">
                    {uploading ? <ActivityIndicator color={theme.color.brand} /> : (
                      <>
                        <Feather name="image" size={22} color={theme.color.brand} />
                        <Text style={styles.addText}>Add photo</Text>
                      </>
                    )}
                  </Pressable>
                )}
              </View>
            </View>

            <Button title={id ? "Resubmit for review" : "Submit for review"} onPress={submit} loading={saving} disabled={uploading} testID="compose-submit" />
            <Text style={styles.hint}>An admin reviews every article before it appears on the blog.</Text>
          </ScrollView>
        </KeyboardAvoidingView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  headerBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { flex: 1, textAlign: "center", fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  content: { padding: theme.space.xl, gap: theme.space.lg, paddingBottom: theme.space["3xl"] },
  label: { fontSize: theme.font.sm, color: theme.color.onSurfaceSecondary, fontWeight: "600" },
  hint: { color: theme.color.muted, fontSize: theme.font.sm, lineHeight: 18 },
  counter: { color: theme.color.muted, fontSize: 13, marginTop: -theme.space.sm, textAlign: "right" },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm },
  photos: { flexDirection: "row", gap: theme.space.md, marginTop: theme.space.xs },
  photo: { width: 140, height: 105, borderRadius: theme.radius.md, overflow: "hidden", backgroundColor: theme.color.surfaceSecondary },
  addPhoto: { alignItems: "center", justifyContent: "center", gap: 4, borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.borderStrong },
  addText: { color: theme.color.brandDark, fontWeight: "600", fontSize: theme.font.sm },
  coverBadge: { position: "absolute", left: 6, bottom: 6, backgroundColor: theme.color.surfaceInverse, paddingHorizontal: 8, paddingVertical: 2, borderRadius: theme.radius.pill },
  coverText: { color: theme.color.onSurfaceInverse, fontSize: 13, fontWeight: "700" },
  remove: { position: "absolute", right: 6, top: 6, width: 28, height: 28, borderRadius: 14, backgroundColor: theme.color.surfaceInverse, alignItems: "center", justifyContent: "center" },
  notes: { padding: theme.space.lg, borderRadius: theme.radius.md, backgroundColor: theme.color.brandSoft, gap: 4 },
  notesTitle: { color: theme.color.brandDark, fontWeight: "700" },
  notesBody: { color: theme.color.onSurface, lineHeight: 20 },
  gate: { flex: 1, alignItems: "center", justifyContent: "center", padding: theme.space.xl, gap: theme.space.md },
  gateTitle: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  gateSub: { color: theme.color.onSurfaceSecondary, textAlign: "center", marginBottom: theme.space.md },
});
