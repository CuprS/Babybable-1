import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Linking } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import { apiFetch, apiUpload, fileUrl, Tutor } from "@/src/api";
import { theme } from "@/src/theme";
import { Button, Input } from "@/src/ui";
import { useToast } from "@/src/toast";

export default function EditTutor() {
  const router = useRouter();
  const { show } = useToast();
  const [tutor, setTutor] = useState<Tutor | null>(null);
  const [bio, setBio] = useState("");
  const [locations, setLocations] = useState<string[]>([]);
  const [locInput, setLocInput] = useState("");
  const [experience, setExperience] = useState("0");
  const [rate, setRate] = useState("30");
  const [langs, setLangs] = useState<string[]>([]);
  const [langInput, setLangInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<Tutor>("/tutors/me/profile").then((t) => {
      setTutor(t);
      setBio(t.bio);
      const locs = (t.locations || []).map((l) => l.name).filter(Boolean);
      setLocations(locs.length ? locs : (t.location ? [t.location] : []));
      setExperience(String(t.experience_years));
      setRate(String(Math.round(t.hourly_rate_cents / 100)));
      setLangs(t.languages);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const pickImage = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return null;
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (res.canceled) return null;
    const a = res.assets[0];
    return apiUpload(a.uri, a.fileName || "photo.jpg", a.mimeType || "image/jpeg");
  };

  const uploadKey = async (key: "avatar" | "hero" | "accred_photo") => {
    try {
      setSaving(true);
      const up = await pickImage();
      if (!up) return;
      const patch: any = {};
      if (key === "avatar") patch.avatar_url = up.path;
      if (key === "hero") patch.hero_image_url = up.path;
      if (key === "accred_photo") patch.accreditation_photo_url = up.path;
      const updated = await apiFetch<Tutor>("/tutors/me/profile", { method: "PATCH", body: JSON.stringify(patch) });
      setTutor(updated);
    } catch (e: any) { show({ kind: "error", title: "Upload failed", body: e?.message }); }
    finally { setSaving(false); }
  };

  const uploadDocument = async () => {
    try {
      const res = await DocumentPicker.getDocumentAsync({ type: ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain", "application/rtf"], copyToCacheDirectory: true, multiple: false });
      if (res.canceled) return;
      setSaving(true);
      const a = res.assets[0];
      const up = await apiUpload(a.uri, a.name, a.mimeType || "application/pdf");
      const updated = await apiFetch<Tutor>("/tutors/me/profile", { method: "PATCH", body: JSON.stringify({ accreditation_document_url: up.path }) });
      setTutor(updated);
      show({ kind: "success", title: "Document uploaded" });
    } catch (e: any) { show({ kind: "error", title: "Upload failed", body: e?.message }); }
    finally { setSaving(false); }
  };

  const clearAccredPhoto = async () => {
    setSaving(true);
    try {
      const updated = await apiFetch<Tutor>("/tutors/me/profile", { method: "PATCH", body: JSON.stringify({ accreditation_photo_url: "" }) });
      setTutor(updated);
    } finally { setSaving(false); }
  };
  const clearAccredDoc = async () => {
    setSaving(true);
    try {
      const updated = await apiFetch<Tutor>("/tutors/me/profile", { method: "PATCH", body: JSON.stringify({ accreditation_document_url: "" }) });
      setTutor(updated);
    } finally { setSaving(false); }
  };

  const addLang = () => { const l = langInput.trim(); if (l && !langs.includes(l)) setLangs([...langs, l]); setLangInput(""); };
  const removeLang = (l: string) => setLangs(langs.filter((x) => x !== l));
  const addLoc = () => { const v = locInput.trim(); if (v && !locations.includes(v)) setLocations([...locations, v]); setLocInput(""); };
  const removeLoc = (v: string) => setLocations(locations.filter((x) => x !== v));

  const save = async () => {
    setSaving(true);
    try {
      const updated = await apiFetch<Tutor>("/tutors/me/profile", {
        method: "PATCH",
        body: JSON.stringify({
          bio,
          experience_years: parseInt(experience) || 0,
          hourly_rate_cents: Math.max(500, Math.round(parseFloat(rate) * 100)),
          languages: langs,
          locations,
          allows_remote: !!tutor?.allows_remote,
        }),
      });
      setTutor(updated);
      router.back();
    } catch (e: any) { show({ kind: "error", title: "Save failed", body: e?.message }); }
    finally { setSaving(false); }
  };

  if (loading) return <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}><ActivityIndicator color={theme.color.brand} /></View>;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="edit-back"><Feather name="arrow-left" size={24} color={theme.color.onSurface} /></Pressable>
        <Text style={styles.title}>Edit profile</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: theme.space["3xl"], gap: theme.space.lg }}>
        <Text style={styles.section}>Profile photo</Text>
        <View style={styles.photoRow}>
          <Pressable onPress={() => uploadKey("avatar")} style={styles.avatarWrap} testID="edit-avatar">
            {tutor?.avatar_url ? (
              <Image source={{ uri: fileUrl(tutor.avatar_url) }} style={styles.avatar} contentFit="cover" />
            ) : (
              <View style={[styles.avatar, { alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surfaceSecondary }]}>
                <Feather name="camera" size={22} color={theme.color.muted} />
              </View>
            )}
            <View style={styles.camBadge}><Feather name="camera" size={12} color="#fff" /></View>
          </Pressable>
          <Text style={{ color: theme.color.onSurfaceSecondary, flex: 1 }}>Tap to upload a warm, friendly photo of yourself.</Text>
        </View>

        <Text style={styles.section}>Hero image</Text>
        <Pressable onPress={() => uploadKey("hero")} style={styles.hero} testID="edit-hero">
          {tutor?.hero_image_url ? (
            <Image source={{ uri: fileUrl(tutor.hero_image_url) }} style={StyleSheet.absoluteFill as any} contentFit="cover" />
          ) : (
            <View style={{ alignItems: "center", gap: 4 }}>
              <Feather name="image" size={24} color={theme.color.muted} />
              <Text style={{ color: theme.color.muted }}>Upload cover image</Text>
            </View>
          )}
        </Pressable>

        <Input label="Bio" value={bio} onChangeText={setBio} multiline placeholder="Tell parents about your teaching approach…" style={{ minHeight: 100, textAlignVertical: "top" }} testID="edit-bio" />
        <View style={{ flexDirection: "row", gap: theme.space.md }}>
          <View style={{ flex: 1 }}><Input label="Hourly rate ($)" value={rate} onChangeText={setRate} keyboardType="numeric" testID="edit-rate" /></View>
          <View style={{ flex: 1 }}><Input label="Experience (years)" value={experience} onChangeText={setExperience} keyboardType="numeric" testID="edit-exp" /></View>
        </View>

        <Pressable
          onPress={() => tutor && setTutor({ ...tutor, allows_remote: !tutor.allows_remote })}
          style={[styles.toggleRow, tutor?.allows_remote && styles.toggleRowOn]}
          testID="edit-remote-toggle"
        >
          <Feather name="video" size={20} color={tutor?.allows_remote ? theme.color.onBrand : theme.color.onSurface} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.toggleTitle, tutor?.allows_remote && { color: theme.color.onBrand }]}>Offer remote lessons</Text>
            <Text style={[styles.toggleSub, tutor?.allows_remote && { color: "rgba(255,255,255,0.85)" }]}>
              Reach families outside the 100-mile radius.
            </Text>
          </View>
          <View style={[styles.dot, tutor?.allows_remote && styles.dotOn]} />
        </Pressable>

        <Text style={styles.section}>Cities you teach in</Text>
        <View style={{ flexDirection: "row", gap: theme.space.sm, flexWrap: "wrap" }}>
          {locations.map((l) => (
            <Pressable key={l} onPress={() => removeLoc(l)} style={styles.chipPill} testID={`loc-${l}`}>
              <Feather name="map-pin" size={13} color={theme.color.brandDark} />
              <Text style={{ color: theme.color.brandDark, fontWeight: "600" }}>{l}</Text>
              <Feather name="x" size={14} color={theme.color.brandDark} />
            </Pressable>
          ))}
        </View>
        <View style={{ flexDirection: "row", gap: theme.space.sm }}>
          <View style={{ flex: 1 }}><Input value={locInput} onChangeText={setLocInput} placeholder="Add a city (e.g. Barcelona, ES)" testID="edit-loc-input" onSubmitEditing={addLoc} /></View>
          <Pressable onPress={addLoc} style={styles.addBtn} testID="edit-loc-add"><Feather name="plus" size={20} color="#fff" /></Pressable>
        </View>

        <Text style={styles.section}>Languages you teach</Text>
        <View style={{ flexDirection: "row", gap: theme.space.sm, flexWrap: "wrap" }}>
          {langs.map((l) => (
            <Pressable key={l} onPress={() => removeLang(l)} style={styles.chipPill} testID={`lang-${l}`}>
              <Text style={{ color: theme.color.brandDark, fontWeight: "600" }}>{l}</Text>
              <Feather name="x" size={14} color={theme.color.brandDark} />
            </Pressable>
          ))}
        </View>
        <View style={{ flexDirection: "row", gap: theme.space.sm }}>
          <View style={{ flex: 1 }}><Input value={langInput} onChangeText={setLangInput} placeholder="Add a language" testID="edit-lang-input" onSubmitEditing={addLang} /></View>
          <Pressable onPress={addLang} style={styles.addBtn} testID="edit-lang-add"><Feather name="plus" size={20} color="#fff" /></Pressable>
        </View>

        <Text style={styles.section}>Accreditations</Text>
        <Text style={styles.hintText}>One photo + one document (PDF, DOC, TXT).</Text>

        <View style={styles.accredRow}>
          {tutor?.accreditation_photo_url ? (
            <Pressable onPress={() => uploadKey("accred_photo")} style={styles.accredCard} testID="edit-accred-photo">
              <Image source={{ uri: fileUrl(tutor.accreditation_photo_url) }} style={StyleSheet.absoluteFill as any} contentFit="cover" />
              <Pressable onPress={clearAccredPhoto} style={styles.removeBadge} testID="edit-accred-photo-remove" hitSlop={8}>
                <Feather name="x" size={14} color="#fff" />
              </Pressable>
              <View style={styles.accredLabel}>
                <Feather name="image" size={12} color="#fff" />
                <Text style={styles.accredLabelText}>Photo</Text>
              </View>
            </Pressable>
          ) : (
            <Pressable onPress={() => uploadKey("accred_photo")} style={[styles.accredCard, styles.accredEmpty]} testID="edit-accred-photo">
              <Feather name="image" size={22} color={theme.color.muted} />
              <Text style={styles.emptyLabel}>Upload accreditation photo</Text>
            </Pressable>
          )}

          {tutor?.accreditation_document_url ? (
            <View style={[styles.accredCard, styles.accredDocFilled]} testID="edit-accred-doc">
              <Feather name="file-text" size={28} color={theme.color.brand} />
              <Text style={styles.docFilename} numberOfLines={2}>
                {(tutor.accreditation_document_url.split("/").pop() || "document").slice(0, 40)}
              </Text>
              <View style={{ flexDirection: "row", gap: 4 }}>
                <Pressable
                  onPress={() => Linking.openURL(fileUrl(tutor.accreditation_document_url!) || "")}
                  style={styles.docBtnSmall}
                  testID="edit-accred-doc-open"
                >
                  <Text style={styles.docBtnText}>Open</Text>
                </Pressable>
                <Pressable onPress={uploadDocument} style={styles.docBtnSmall} testID="edit-accred-doc-replace">
                  <Text style={styles.docBtnText}>Replace</Text>
                </Pressable>
              </View>
              <Pressable onPress={clearAccredDoc} style={styles.removeBadge} testID="edit-accred-doc-remove" hitSlop={8}>
                <Feather name="x" size={14} color="#fff" />
              </Pressable>
            </View>
          ) : (
            <Pressable onPress={uploadDocument} style={[styles.accredCard, styles.accredEmpty]} testID="edit-accred-doc">
              <Feather name="file-text" size={22} color={theme.color.muted} />
              <Text style={styles.emptyLabel}>Upload accreditation document</Text>
            </Pressable>
          )}
        </View>

        <Button title="Save profile" onPress={save} loading={saving} testID="edit-save" />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  section: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.sm },
  photoRow: { flexDirection: "row", alignItems: "center", gap: theme.space.lg },
  avatarWrap: { position: "relative" },
  avatar: { width: 96, height: 96, borderRadius: 48 },
  camBadge: { position: "absolute", bottom: 0, right: 0, width: 26, height: 26, borderRadius: 13, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: theme.color.surface },
  hero: { height: 160, borderRadius: theme.radius.lg, backgroundColor: theme.color.surfaceSecondary, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  chipPill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand },
  addBtn: { width: 52, height: 52, borderRadius: 26, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center", alignSelf: "flex-end" },
  toggleRow: { flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.lg, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary },
  toggleRowOn: { backgroundColor: theme.color.brand },
  toggleTitle: { fontWeight: "700", color: theme.color.onSurface, fontSize: theme.font.lg },
  toggleSub: { color: theme.color.onSurfaceSecondary, marginTop: 2 },
  dot: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: theme.color.borderStrong, backgroundColor: theme.color.surface },
  dotOn: { borderColor: "#fff", backgroundColor: "#fff" },
  hintText: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: -theme.space.sm },
  accredRow: { flexDirection: "row", gap: theme.space.md },
  accredCard: { flex: 1, height: 180, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary, overflow: "hidden", position: "relative" },
  accredEmpty: { alignItems: "center", justifyContent: "center", gap: 6, borderWidth: 1, borderColor: theme.color.borderStrong, borderStyle: "dashed" },
  accredDocFilled: { alignItems: "center", justifyContent: "center", gap: 8, padding: theme.space.md },
  emptyLabel: { color: theme.color.muted, fontSize: theme.font.sm, textAlign: "center", paddingHorizontal: theme.space.sm },
  accredLabel: { position: "absolute", left: 8, bottom: 8, flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "rgba(44,36,33,0.85)", paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.pill },
  accredLabelText: { color: "#fff", fontSize: 11, fontWeight: "700" },
  removeBadge: { position: "absolute", top: 6, right: 6, width: 26, height: 26, borderRadius: 13, backgroundColor: theme.color.error, alignItems: "center", justifyContent: "center" },
  docFilename: { color: theme.color.onSurface, fontWeight: "600", textAlign: "center", fontSize: theme.font.sm },
  docBtnSmall: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.brand },
  docBtnText: { color: "#fff", fontWeight: "700", fontSize: 12 },
});
