import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { apiFetch, Booking } from "@/src/api";
import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";
import { MenuButton } from "@/src/drawer";

export default function Bookings() {
  const { user } = useAuth();
  const router = useRouter();
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<Booking[]>("/bookings/me");
      setBookings(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const statusColor = (s: string) =>
    s === "paid" ? theme.color.success : s === "failed" ? theme.color.error : theme.color.warning;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flexDirection: "row", alignItems: "center", marginLeft: -theme.space.sm }}>
          <MenuButton tint={theme.color.onSurface} />
        </View>
        <Text style={styles.title}>Bookings</Text>
        <Text style={styles.sub}>Your sessions in one place.</Text>
      </View>
      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.space.xl }} />
      ) : (
        <FlatList
          testID="bookings-list"
          data={bookings}
          keyExtractor={(b) => b.id}
          contentContainerStyle={{ padding: theme.space.xl, paddingBottom: theme.space["3xl"], gap: theme.space.md }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Feather name="calendar" size={40} color={theme.color.borderStrong} />
              <Text style={{ color: theme.color.onSurfaceSecondary, marginTop: theme.space.md }}>
                No bookings yet.
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <Pressable
              testID={`booking-${item.id}`}
              onPress={() => router.push(`/booking-detail/${item.id}`)}
              style={styles.card}
            >
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={styles.who}>
                  {user?.role === "parent" ? item.tutor_name : item.parent_name}
                </Text>
                <View style={[styles.badge, { backgroundColor: statusColor(item.payment_status) }]}>
                  <Text style={styles.badgeText}>{item.payment_status}</Text>
                </View>
              </View>
              <Text style={styles.meta}>{item.language} · {item.duration_minutes} min{item.is_au_pair ? ` · au-pair · ${item.lessons_count} lessons` : ""}</Text>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: theme.space.md }}>
                <Text style={styles.date}>{item.date} · {item.time}</Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={styles.amount}>${(item.amount_cents / 100).toFixed(0)}</Text>
                  <Feather name="chevron-right" size={20} color={theme.color.muted} />
                </View>
              </View>
            </Pressable>
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
  empty: { alignItems: "center", paddingTop: theme.space["3xl"] },
  card: { padding: theme.space.lg, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, gap: 4 },
  who: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  meta: { color: theme.color.onSurfaceSecondary },
  date: { color: theme.color.onSurfaceSecondary },
  amount: { color: theme.color.brand, fontWeight: "700", fontSize: theme.font.lg },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: theme.radius.pill },
  badgeText: { color: "#fff", fontWeight: "700", fontSize: 11, textTransform: "capitalize" },
});
