import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import Slider from "@react-native-community/slider";
import { apiFetch, apiUpload, fileUrl } from "@/src/api";
import { theme } from "@/src/theme";
import { Button, Input } from "@/src/ui";
import { useAuth } from "@/src/auth";

interface Child { id: string; name: string; age: number; avatar_url?: string | null }
interface ParentProfile {
  user_id: string; name: string; avatar_url?: string | null; city: string;
  languages_desired: string[]; hours_per_week: number; learning_materials: string; children: Child[];
}

const MAX_CHILDREN = 10;

export default function EditParent() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [profile, setProfile] = useState<ParentProfile | null>(null);
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [hours, setHours] = useState(5);
  const [materials, setMaterials] = useState("");
  const [langs, setLangs] = useState<string[]>([]);
  const [langInput, setLangInput] = useState("");
  const [children, setChildren] = useState<Child[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<ParentProfile>("/parents/me/profile").then((p) => {
      setProfile(p); setName(p.name); setCity(p.city); setHours(p.hours_per_week);
      setMaterials(p.learning_materials); setLangs(p.languages_desired); setChildren(p.children);
    }).finally(() => setLoading(false));
  }, []);

  const pickImage = async (): Promise<{ path: string } | null> => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return null;
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7 });
    if (res.canceled) return null;
    const a = res.assets[0];
    return apiUpload(a.uri, a.fileName || "photo.jpg", a.mimeType || "image/jpeg");
  };

  const uploadAvatar = async () => {
    try {
      setSaving(true);
      const up = await pickImage();
      if (!up) return;
      const p = await apiFetch<ParentProfile>("/parents/me/profile", { method: "PATCH", body: JSON.stringify({ avatar_url: up.path }) });
      setProfile(p); await refresh();
    } catch (e: any) { Alert.alert("Upload failed", e?.message || "Try again"); }
    finally { setSaving(false); }
  };

  const uploadChildAvatar = async (idx: number) => {
    try {
      setSaving(true);
      const up = await pickImage();
      if (!up) return;
      const next = [...children];
      next[idx] = { ...next[idx], avatar_url: up.path };
      setChildren(next);
    } catch (e: any) { Alert.alert("Upload failed", e?.message || "Try again"); }
    finally { setSaving(false); }
  };

  const addChild = () => {
    if (children.length >= MAX_CHILDREN) { Alert.alert("Limit reached", "Up to 10 children."); return; }
    setChildren([...children, { id: String(Date.now()), name: "", age: 3 }]);
  };
  const updateChild = (idx: number, patch: Partial<Child>) => {
    const next = [...children]; next[idx] = { ...next[idx], ...patch }; setChildren(next);
  };
  const removeChild = (idx: number) => setChildren(children.filter((_, i) => i !== idx));

  const addLang = () => {
    const l = langInput.trim(); if (l && !langs.includes(l)) setLangs([...langs, l]); setLangInput("");
  };
  const removeLang = (l: string) => setLangs(langs.filter((x) => x !== l));

  const save = async () => {
    setSaving(true);
    try {
      const clean = children.filter((c) => c.name.trim());
      const p = await apiFetch<ParentProfile>("/parents/me/profile", {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim() || profile?.name,
          city, hours_per_week: hours, learning_materials: materials,
          languages_desired: langs,
          children: clean,
        }),
      });
      setProfile(p); await refresh(); router.back();
    } catch (e: any) { Alert.alert("Save failed", e?.message || "Try again"); }
    finally { setSaving(false); }
  };

  if (loading) return <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}><ActivityIndicator color={theme.color.brand} /></View>;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="edit-parent-back"><Feather name="arrow-left" size={24} color={theme.color.onSurface} /></Pressable>
        <Text style={styles.title}>Family profile</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.xl, gap: theme.space.lg, paddingBottom: theme.space["3xl"] }}>
        <View style={styles.photoRow}>
          <Pressable onPress={uploadAvatar} testID="parent-avatar-btn">
            {profile?.avatar_url ? (
              <Image source={{ uri: fileUrl(profile.avatar_url) }} style={styles.avatar} contentFit="cover" />
            ) : (
              <View style={[styles.avatar, { alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surfaceSecondary }]}>
                <Feather name="camera" size={22} color={theme.color.muted} />
              </View>
            )}
          </Pressable>
          <Text style={{ color: theme.color.onSurfaceSecondary, flex: 1 }}>Tap to upload your parent photo.</Text>
        </View>

        <Input label="Your name" value={name} onChangeText={setName} testID="parent-name" />
        <Input label="City of residence" value={city} onChangeText={setCity} placeholder="New York, NY" testID="parent-city" />

        <View>
          <Text style={styles.label}>Languages desired</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm, marginTop: 6 }}>
            {langs.map((l) => (
              <Pressable key={l} onPress={() => removeLang(l)} style={styles.langPill} testID={`parent-lang-${l}`}>
                <Text style={{ color: theme.color.brandDark, fontWeight: "600" }}>{l}</Text>
                <Feather name="x" size={14} color={theme.color.brandDark} />
              </Pressable>
            ))}
          </View>
          <View style={{ flexDirection: "row", gap: theme.space.sm, marginTop: theme.space.sm }}>
            <View style={{ flex: 1 }}><Input value={langInput} onChangeText={setLangInput} placeholder="Add a language" testID="parent-lang-input" /></View>
            <Pressable onPress={addLang} style={styles.addBtn} testID="parent-lang-add"><Feather name="plus" size={20} color="#fff" /></Pressable>
          </View>
        </View>

        <View>
          <Text style={styles.label}>Hours needed per week</Text>
          <Text style={styles.hoursValue}>{hours} {hours === 1 ? "hour" : "hours"} / week</Text>
          <Slider
            testID="parent-hours-slider"
            minimumValue={1}
            maximumValue={40}
            step={1}
            value={hours}
            onValueChange={setHours}
            minimumTrackTintColor={theme.color.brand}
            maximumTrackTintColor={theme.color.border}
            thumbTintColor={theme.color.brand}
            style={{ marginTop: theme.space.sm }}
          />
        </View>

        <Input label="Desired learning materials" value={materials} onChangeText={setMaterials} multiline placeholder="Books, songs, flashcards, apps you'd like the tutor to use…" style={{ minHeight: 90, textAlignVertical: "top" }} testID="parent-materials" />

        <View>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text style={styles.section}>Children ({children.length}/{MAX_CHILDREN})</Text>
            <Pressable onPress={addChild} style={styles.addBtn} testID="parent-add-child"><Feather name="plus" size={20} color="#fff" /></Pressable>
          </View>
          {children.map((c, i) => (
            <View key={c.id} style={styles.childCard} testID={`parent-child-${i}`}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.md }}>
                <Pressable onPress={() => uploadChildAvatar(i)} testID={`child-avatar-${i}`}>
                  {c.avatar_url ? (
                    <Image source={{ uri: fileUrl(c.avatar_url) }} style={styles.childAvatar} contentFit="cover" />
                  ) : (
                    <View style={[styles.childAvatar, { alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface }]}>
                      <Feather name="camera" size={18} color={theme.color.muted} />
                    </View>
                  )}
                </Pressable>
                <View style={{ flex: 1, gap: theme.space.sm }}>
                  <Input value={c.name} onChangeText={(t) => updateChild(i, { name: t })} placeholder="Child's name" testID={`child-name-${i}`} />
                  <Input value={String(c.age)} onChangeText={(t) => updateChild(i, { age: Math.max(0, Math.min(18, parseInt(t) || 0)) })} keyboardType="numeric" placeholder="Age" testID={`child-age-${i}`} />
                </View>
                <Pressable onPress={() => removeChild(i)} hitSlop={10} testID={`child-remove-${i}`}>
                  <Feather name="trash-2" size={18} color={theme.color.error} />
                </Pressable>
              </View>
            </View>
          ))}
        </View>

        <Button title="Save family profile" onPress={save} loading={saving} testID="parent-save" />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  photoRow: { flexDirection: "row", alignItems: "center", gap: theme.space.lg },
  avatar: { width: 96, height: 96, borderRadius: 48 },
  label: { fontSize: theme.font.sm, color: theme.color.onSurfaceSecondary, fontWeight: "600" },
  hoursValue: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.brand, marginTop: 4 },
  section: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  addBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  langPill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand },
  childCard: { padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, marginTop: theme.space.md },
  childAvatar: { width: 56, height: 56, borderRadius: 28, borderWidth: 1, borderColor: theme.color.border },
});
