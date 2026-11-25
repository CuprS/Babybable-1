import { View, Text, StyleSheet, Pressable, ScrollView, Alert, ActivityIndicator } from "react-native";
import { useEffect, useState } from "react";
import * as ImagePicker from "expo-image-picker";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { apiFetch, apiUpload, fileUrl, UserPublic } from "@/src/api";
import { Button } from "@/src/ui";
import { MenuButton } from "@/src/drawer";

export default function Profile() {
  const { user, signOut, refresh } = useAuth();
  const router = useRouter();
  const [uploading, setUploading] = useState(false);
  const [tutorId, setTutorId] = useState<string | null>(null);

  useEffect(() => {
    if (user?.role === "tutor") {
      apiFetch<{ id: string }>("/tutors/me/profile").then((p) => setTutorId(p.id)).catch(() => {});
    }
  }, [user?.role]);

  if (!user) return null;

  const openPublicView = () => {
    if (user.role === "tutor" && tutorId) router.push(`/tutor/${tutorId}`);
    else if (user.role === "parent") router.push(`/parent-profile/${user.id}`);
  };

  const uploadAvatar = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) { Alert.alert("Permission needed", "Please allow photo library access."); return; }
      const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.7, allowsEditing: true, aspect: [1, 1] });
      if (res.canceled) return;
      setUploading(true);
      const asset = res.assets[0];
      const up = await apiUpload(asset.uri, asset.fileName || "photo.jpg", asset.mimeType || "image/jpeg");
      await apiFetch<UserPublic>("/auth/me", { method: "PATCH", body: JSON.stringify({ avatar_url: up.path }) });
      await refresh();
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Try again");
    } finally { setUploading(false); }
  };

  const confirmDelete = () => {
    Alert.alert(
      "Delete account?",
      "This permanently deletes your account, messages and photos, and cancels your upcoming sessions (normal refund rules apply). Records of past sessions are kept without your name, for accounting. This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete", style: "destructive", onPress: async () => {
            try {
              await apiFetch("/auth/me", { method: "DELETE" });
              await signOut();
              router.replace("/onboarding");
            } catch (e: any) {
              Alert.alert("Delete failed", e?.message || "Try again");
            }
          },
        },
      ],
    );
  };
  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: theme.space.md, paddingTop: theme.space.xs }}>
        <MenuButton tint={theme.color.onSurface} />
        <Text style={{ flex: 1, textAlign: "center", fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginRight: 40 }}>Profile</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: theme.space["3xl"] }}>
        <View style={styles.headerCard}>
          <Pressable onPress={uploadAvatar} testID="profile-avatar-btn" style={styles.avatarWrap}>
            {user.avatar_url ? (
              <Image source={{ uri: fileUrl(user.avatar_url) }} style={styles.avatar} contentFit="cover" />
            ) : (
              <View style={[styles.avatar, styles.avatarFallback]}>
                <Text style={{ color: "#fff", fontWeight: "700", fontSize: 28 }}>{user.name[0]}</Text>
              </View>
            )}
            <View style={styles.camBadge}>
              {uploading ? <ActivityIndicator size="small" color="#fff" /> : <Feather name="camera" size={14} color="#fff" />}
            </View>
          </Pressable>
          <Text style={styles.name}>{user.name}</Text>
          <Text style={styles.role}>{user.role === "tutor" ? "Tutor" : "Parent"} · {user.email}</Text>
          <Text style={styles.hint}>Tap the photo to update your profile picture</Text>
        </View>

        {user.email_verified === false && (
          <Pressable testID="profile-verify-email" onPress={() => router.push("/verify-email")} style={styles.notice} accessibilityRole="button">
            <Feather name="mail" size={20} color={theme.color.brandDark} />
            <View style={{ flex: 1 }}>
              <Text style={styles.noticeTitle}>Confirm your email</Text>
              <Text style={styles.noticeBody}>We sent you a 6-digit code. It keeps your account recoverable.</Text>
            </View>
            <Feather name="chevron-right" size={20} color={theme.color.brandDark} />
          </Pressable>
        )}
        {user.role === "tutor" && (
          <Pressable testID="profile-verify-tutor" onPress={() => router.push("/verify-tutor")} style={styles.row} accessibilityRole="button">
            <Feather name="shield" size={20} color={theme.color.onSurface} />
            <Text style={styles.rowText}>Identity &amp; background check</Text>
            <Feather name="chevron-right" size={20} color={theme.color.muted} />
          </Pressable>
        )}
        {(user.role === "tutor" || user.role === "parent") && (
          <Pressable
            testID="profile-view-public-btn"
            onPress={openPublicView}
            style={styles.row}
            disabled={user.role === "tutor" && !tutorId}
          >
            <Feather name="eye" size={20} color={theme.color.brand} />
            <Text style={[styles.rowText, { color: theme.color.brand }]}>See how others view my profile</Text>
            <Feather name="chevron-right" size={20} color={theme.color.muted} />
          </Pressable>
        )}
        {user.role === "tutor" && (
          <Pressable
            testID="profile-edit-tutor-btn"
            onPress={() => router.push("/edit-tutor")}
            style={styles.row}
          >
            <Feather name="edit-3" size={20} color={theme.color.onSurface} />
            <Text style={styles.rowText}>Edit tutor profile</Text>
            <Feather name="chevron-right" size={20} color={theme.color.muted} />
          </Pressable>
        )}
        {user.role === "tutor" && (
          <Pressable
            testID="profile-w9-btn"
            onPress={() => router.push("/w9")}
            style={styles.row}
          >
            <Feather name="file-text" size={20} color={theme.color.onSurface} />
            <Text style={styles.rowText}>Tax forms (W-9)</Text>
            <Feather name="chevron-right" size={20} color={theme.color.muted} />
          </Pressable>
        )}
        {user.role === "parent" && (
          <Pressable
            testID="profile-edit-parent-btn"
            onPress={() => router.push("/edit-parent")}
            style={styles.row}
          >
            <Feather name="users" size={20} color={theme.color.onSurface} />
            <Text style={styles.rowText}>Edit family profile</Text>
            <Feather name="chevron-right" size={20} color={theme.color.muted} />
          </Pressable>
        )}
        <Pressable testID="profile-bookings-btn" onPress={() => router.push("/(tabs)/bookings")} style={styles.row}>
          <Feather name="calendar" size={20} color={theme.color.onSurface} />
          <Text style={styles.rowText}>My bookings</Text>
          <Feather name="chevron-right" size={20} color={theme.color.muted} />
        </Pressable>
        <Pressable testID="profile-messages-btn" onPress={() => router.push("/(tabs)/messages")} style={styles.row}>
          <Feather name="message-circle" size={20} color={theme.color.onSurface} />
          <Text style={styles.rowText}>Messages</Text>
          <Feather name="chevron-right" size={20} color={theme.color.muted} />
        </Pressable>

        <View style={{ marginTop: theme.space["2xl"] }}>
          <Button testID="profile-signout-btn" title="Log out" variant="ghost" onPress={signOut} />
        </View>
        <Pressable onPress={confirmDelete} testID="profile-delete-btn" style={styles.deleteBtn}>
          <Feather name="trash-2" size={16} color={theme.color.error} />
          <Text style={styles.deleteText}>Delete account</Text>
        </Pressable>
        <Text style={styles.tag}>Babybabel · care in every language</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  headerCard: { alignItems: "center", paddingVertical: theme.space.xl, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, marginBottom: theme.space.xl },
  avatarWrap: { position: "relative" },
  avatar: { width: 96, height: 96, borderRadius: 48, backgroundColor: theme.color.brand },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  camBadge: { position: "absolute", bottom: 0, right: 0, width: 30, height: 30, borderRadius: 15, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center", borderWidth: 3, borderColor: theme.color.surfaceSecondary },
  hint: { color: theme.color.muted, fontSize: 12, marginTop: theme.space.sm },
  name: { fontSize: 22, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.md },
  role: { color: theme.color.onSurfaceSecondary, marginTop: 4 },
  row: { flexDirection: "row", alignItems: "center", gap: theme.space.md, paddingVertical: theme.space.lg, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  rowText: { flex: 1, fontSize: theme.font.lg, color: theme.color.onSurface, fontWeight: "500" },
  deleteBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: theme.space.sm, marginTop: theme.space.lg, paddingVertical: theme.space.md },
  deleteText: { color: theme.color.error, fontWeight: "700", fontSize: theme.font.base },
  tag: { textAlign: "center", color: theme.color.muted, marginTop: theme.space["2xl"] },
  notice: { flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.lg, borderRadius: theme.radius.lg, backgroundColor: theme.color.brandSoft, marginBottom: theme.space.md },
  noticeTitle: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.lg },
  noticeBody: { color: theme.color.brandDark, fontSize: theme.font.base, marginTop: 2 },
});
