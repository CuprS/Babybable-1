import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { apiFetch, Booking } from "@/src/api";
import { theme } from "@/src/theme";
import { Button } from "@/src/ui";
import { useAuth } from "@/src/auth";

export default function BookingDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const [b, setB] = useState<Booking | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    apiFetch<Booking>(`/bookings/${id}`).then(setB).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (!b) return <View style={styles.center}><Text>Booking not found</Text></View>;

  const paid = b.payment_status === "paid";
  const other = user?.role === "parent" ? b.tutor_name : b.parent_name;
  const canPay = user?.role === "parent" && !paid;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="booking-detail-back" hitSlop={12}>
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Booking</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: 160 }}>
        <View style={[styles.statusCard, { backgroundColor: paid ? theme.color.success : theme.color.brandSoft }]} testID="booking-status-card">
          <Feather name={paid ? "check-circle" : "clock"} size={28} color={paid ? "#fff" : theme.color.brandDark} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.statusTitle, { color: paid ? "#fff" : theme.color.brandDark }]}>
              {paid ? "Payment complete" : "Waiting for payment"}
            </Text>
            <Text style={[styles.statusSub, { color: paid ? "rgba(255,255,255,0.9)" : theme.color.brandDark }]}>
              {paid ? "You're all set — the family and tutor have been notified." : "Confirm the details, then pay on the next screen."}
            </Text>
          </View>
        </View>

        <Text style={styles.section}>Summary</Text>
        <View style={styles.card}>
          <Row icon="user" label={user?.role === "parent" ? "Tutor" : "Parent"} value={other} />
          <Row icon="calendar" label="Date" value={`${b.date} · ${b.time}`} />
          <Row icon="clock" label="Duration" value={`${b.duration_minutes} min`} />
          <Row icon="book-open" label="Language" value={b.language} />
          {b.is_au_pair && <Row icon="home" label="Booking type" value={`Au-pair · ${b.lessons_count} lessons`} />}
          {!b.is_au_pair && b.remote && <Row icon="video" label="Booking type" value="Remote" />}
          {!b.is_au_pair && !b.remote && <Row icon="map-pin" label="Booking type" value="In-person"
            extra={b.distance_miles != null ? `${b.distance_miles} mi away` : undefined} />}
          {b.notes ? <Row icon="edit-3" label="Notes" value={b.notes} /> : null}
        </View>

        <Text style={styles.section}>Total</Text>
        <View style={styles.totalCard}>
          <Text style={styles.total}>${(b.amount_cents / 100).toFixed(2)}</Text>
          <Text style={styles.totalNote}>Includes childcare + language</Text>
        </View>
      </ScrollView>

      {canPay && (
        <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, theme.space.lg) }]}>
          <Button
            title={`Continue to payment · $${(b.amount_cents / 100).toFixed(2)}`}
            onPress={() => router.push(`/payment/${b.id}`)}
            testID="booking-detail-pay-btn"
          />
        </View>
      )}
    </SafeAreaView>
  );
}

function Row({ icon, label, value, extra }: { icon: any; label: string; value: string; extra?: string }) {
  return (
    <View style={styles.row}>
      <Feather name={icon} size={16} color={theme.color.brand} />
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text style={styles.rowValue}>{value}</Text>
        {extra ? <Text style={styles.rowExtra}>{extra}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  statusCard: { flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.lg, borderRadius: theme.radius.lg },
  statusTitle: { fontSize: theme.font.xl, fontWeight: "700" },
  statusSub: { marginTop: 4, fontSize: theme.font.sm },
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  card: { backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, padding: theme.space.lg, gap: theme.space.lg },
  row: { flexDirection: "row", alignItems: "flex-start", gap: theme.space.md },
  rowLabel: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, fontWeight: "600" },
  rowValue: { color: theme.color.onSurface, fontSize: theme.font.lg, marginTop: 2 },
  rowExtra: { color: theme.color.muted, fontSize: theme.font.sm, marginTop: 2 },
  totalCard: { backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, padding: theme.space.xl, alignItems: "center" },
  total: { fontSize: 40, fontWeight: "700", color: theme.color.brand, letterSpacing: -1 },
  totalNote: { color: theme.color.onSurfaceSecondary, marginTop: 4 },
  footer: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
});
