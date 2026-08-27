import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { Image } from "expo-image";
import { apiFetch, fileUrl } from "@/src/api";
import { theme } from "@/src/theme";
import { MenuButton } from "@/src/drawer";

interface Thread {
  other_user_id: string;
  other_user_name: string;
  other_user_avatar?: string | null;
  other_user_role: string;
  last_message: string;
  created_at: string;
}

export default function Messages() {
  const router = useRouter();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<Thread[]>("/messages/threads");
      setThreads(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flexDirection: "row", alignItems: "center", marginLeft: -theme.space.sm }}>
          <MenuButton tint={theme.color.onSurface} />
        </View>
        <Text style={styles.title}>Messages</Text>
        <Text style={styles.sub}>Conversations with your matches.</Text>
      </View>
      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.space.xl }} />
      ) : (
        <FlatList
          testID="messages-list"
          data={threads}
          keyExtractor={(t) => t.other_user_id}
          contentContainerStyle={{ paddingHorizontal: theme.space.xl, paddingBottom: theme.space["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Feather name="message-circle" size={40} color={theme.color.borderStrong} />
              <Text style={{ color: theme.color.onSurfaceSecondary, marginTop: theme.space.md }}>
                No messages yet. Open a tutor profile and say hello!
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <View style={styles.rowWrap}>
              <Pressable
                testID={`thread-${item.other_user_id}`}
                onPress={() => router.push(`/chat/${item.other_user_id}?name=${encodeURIComponent(item.other_user_name)}`)}
                style={styles.row}
              >
                {item.other_user_avatar ? (
                  <Image source={{ uri: fileUrl(item.other_user_avatar) }} style={styles.avatar} contentFit="cover" />
                ) : (
                  <View style={[styles.avatar, styles.avatarFallback]}>
                    <Text style={{ color: "#fff", fontWeight: "700" }}>{item.other_user_name?.[0] ?? "?"}</Text>
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <Text style={styles.name} numberOfLines={1}>{item.other_user_name}</Text>
                  <Text style={styles.preview} numberOfLines={1}>{item.last_message}</Text>
                </View>
                <Feather name="chevron-right" size={20} color={theme.color.muted} />
              </Pressable>
              {item.other_user_role === "tutor" && (
                <Pressable
                  onPress={async () => {
                    try {
                      const t = await apiFetch<{ id: string }>(`/tutors/by-user/${item.other_user_id}`);
                      router.push(`/tutor/${t.id}`);
                    } catch {}
                  }}
                  style={styles.viewProfileBtn}
                  testID={`thread-view-profile-${item.other_user_id}`}
                  hitSlop={6}
                >
                  <Feather name="user" size={14} color={theme.color.brandDark} />
                  <Text style={styles.viewProfileText}>View profile</Text>
                </Pressable>
              )}
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { paddingHorizontal: theme.space.xl, paddingTop: theme.space.md, paddingBottom: theme.space.sm },
  title: { fontSize: 28, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5 },
  sub: { color: theme.color.onSurfaceSecondary, marginTop: 4 },
  empty: { alignItems: "center", paddingTop: theme.space["3xl"], paddingHorizontal: theme.space.xl },
  row: { flexDirection: "row", alignItems: "center", gap: theme.space.md, paddingVertical: theme.space.md },
  rowWrap: { borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth, paddingBottom: theme.space.sm },
  viewProfileBtn: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand, marginLeft: 66, marginBottom: theme.space.sm },
  viewProfileText: { color: theme.color.brandDark, fontWeight: "600", fontSize: 12 },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: theme.color.surfaceSecondary },
  avatarFallback: { alignItems: "center", justifyContent: "center", backgroundColor: theme.color.brand },
  name: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  preview: { color: theme.color.onSurfaceSecondary, marginTop: 2 },
});
