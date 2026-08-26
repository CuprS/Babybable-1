import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, Pressable, ActivityIndicator, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { apiFetch, apiUpload, fileUrl, Tutor } from "@/src/api";
import { theme } from "@/src/theme";
import { Button, Input, Chip } from "@/src/ui";

export default function EditTutor() {
  const router = useRouter();
  const [tutor, setTutor] = useState<Tutor | null>(null);
  const [bio, setBio] = useState("");
  const [location, setLocation] = useState("");
  const [experience, setExperience] = useState("0");
  const [rate, setRate] = useState("30");
  const [langs, setLangs] = useState<string[]>([]);
  const [langInput, setLangInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<Tutor>("/tutors/me/profile").then((t) => {
      setTutor(t);
      setBio(t.bio); setLocation(t.location);
      setExperience(String(t.experience_years));
      setRate(String(Math.round(t.hourly_rate_cents / 100)));
      setLangs(t.languages);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const pickAndUpload = async (key: "avatar" | "hero" | "accred") => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (res.canceled) return;
    try {
      setSaving(true);
      const asset = res.assets[0];
      const up = await apiUpload(asset.uri, asset.fileName || "photo.jpg", asset.mimeType || "image/jpeg");
      const patch: any = {};
      if (key === "avatar") patch.avatar_url = up.path;
      if (key === "hero") patch.hero_image_url = up.path;
      if (key === "accred") patch.accreditation_urls = [...(tutor?.accreditation_urls || []), up.path];
      const updated = await apiFetch<Tutor>("/tutors/me/profile", { method: "PATCH", body: JSON.stringify(patch) });
      setTutor(updated);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Try again");
    } finally { setSaving(false); }
  };

  const addLang = () => {
    const l = langInput.trim();
    if (l && !langs.includes(l)) setLangs([...langs, l]);
    setLangInput("");
  };
  const removeLang = (l: string) => setLangs(langs.filter((x) => x !== l));

  const save = async () => {
    setSaving(true);
    try {
      const updated = await apiFetch<Tutor>("/tutors/me/profile", {
        method: "PATCH",
        body: JSON.stringify({
          bio, location,
          experience_years: parseInt(experience) || 0,
          hourly_rate_cents: Math.max(500, Math.round(parseFloat(rate) * 100)),
          languages: langs,
        }),
      });
      setTutor(updated);
      router.back();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Try again");
    } finally { setSaving(false); }
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
          <Pressable onPress={() => pickAndUpload("avatar")} style={styles.avatarWrap} testID="edit-avatar">
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
        <Pressable onPress={() => pickAndUpload("hero")} style={styles.hero} testID="edit-hero">
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
        <Input label="Location" value={location} onChangeText={setLocation} placeholder="City, Country" testID="edit-location" />
        <View style={{ flexDirection: "row", gap: theme.space.md }}>
          <View style={{ flex: 1 }}><Input label="Hourly rate ($)" value={rate} onChangeText={setRate} keyboardType="numeric" testID="edit-rate" /></View>
          <View style={{ flex: 1 }}><Input label="Experience (years)" value={experience} onChangeText={setExperience} keyboardType="numeric" testID="edit-exp" /></View>
        </View>

        <Text style={styles.section}>Languages you teach</Text>
        <View style={{ flexDirection: "row", gap: theme.space.sm, flexWrap: "wrap" }}>
          {langs.map((l) => (
            <Pressable key={l} onPress={() => removeLang(l)} style={styles.langPill} testID={`lang-${l}`}>
              <Text style={{ color: theme.color.brandDark, fontWeight: "600" }}>{l}</Text>
              <Feather name="x" size={14} color={theme.color.brandDark} />
            </Pressable>
          ))}
        </View>
        <View style={{ flexDirection: "row", gap: theme.space.sm }}>
          <View style={{ flex: 1 }}><Input value={langInput} onChangeText={setLangInput} placeholder="Add a language" testID="edit-lang-input" /></View>
          <Pressable onPress={addLang} style={styles.addBtn} testID="edit-lang-add"><Feather name="plus" size={20} color="#fff" /></Pressable>
        </View>

        <Text style={styles.section}>Accreditations</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: theme.space.md }}>
          {(tutor?.accreditation_urls || []).map((u, i) => (
            <Image key={i} source={{ uri: fileUrl(u) }} style={styles.accredImg} contentFit="cover" />
          ))}
          <Pressable onPress={() => pickAndUpload("accred")} style={[styles.accredImg, styles.accredAdd]} testID="edit-add-accred">
            <Feather name="plus" size={22} color={theme.color.muted} />
            <Text style={{ color: theme.color.muted, marginTop: 4 }}>Add</Text>
          </Pressable>
        </ScrollView>

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
  langPill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand },
  addBtn: { width: 52, height: 52, borderRadius: 26, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center", alignSelf: "flex-end" },
  accredImg: { width: 120, height: 160, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary },
  accredAdd: { alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.borderStrong, borderStyle: "dashed" },
});
