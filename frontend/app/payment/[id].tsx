import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { apiFetch, Booking } from "@/src/api";
import { theme } from "@/src/theme";
import { Button } from "@/src/ui";
import { track } from "@/src/analytics";
import { useToast } from "@/src/toast";

export default function Payment() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { show } = useToast();
  const [b, setB] = useState<Booking | null>(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);

  useEffect(() => {
    if (!id) return;
    apiFetch<Booking>(`/bookings/${id}`).then(setB).catch(() => {}).finally(() => setLoading(false));
  }, [id]);

  const pay = async () => {
    if (!b) return;
    setPaying(true);
    try {
      await apiFetch<Booking>(`/bookings/${b.id}/confirm-mock`, { method: "POST" });
      track("booking_created", { booking_id: b.id, tutor_id: b.tutor_id, amount_cents: b.amount_cents });
      show({ kind: "success", title: "Payment complete", body: "Your booking is confirmed." });
      router.replace(`/booking-detail/${b.id}`);
    } catch (e: any) {
      show({ kind: "error", title: "Payment failed", body: e?.message || "Try again" });
    } finally { setPaying(false); }
  };

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (!b) return <View style={styles.center}><Text>Booking not found</Text></View>;

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="payment-back" hitSlop={12}>
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Payment</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: 200 }}>
        <View style={styles.receipt}>
          <Text style={styles.eyebrow}>Order summary</Text>
          <Text style={styles.title}>{b.tutor_name}</Text>
          <Text style={styles.sub}>{b.language} · {b.duration_minutes} min · {b.date} at {b.time}</Text>
          {b.is_au_pair && <Text style={styles.sub}>Au-pair · {b.lessons_count} lessons</Text>}

          <View style={styles.divider} />

          <View style={styles.lineRow}>
            <Text style={styles.lineLabel}>Session</Text>
            <Text style={styles.lineValue}>${(((b.amount_cents || 0) - (b.platform_fee_cents || 0)) / 100).toFixed(2)}</Text>
          </View>
          {b.platform_fee_cents ? (
            <View style={styles.lineRow}>
              <Text style={styles.lineLabel}>Platform fee (1%)</Text>
              <Text style={styles.lineValue}>${(b.platform_fee_cents / 100).toFixed(2)}</Text>
            </View>
          ) : null}
          <View style={[styles.lineRow, { marginTop: theme.space.md }]}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalValue}>${(b.amount_cents / 100).toFixed(2)}</Text>
          </View>
        </View>

        <View style={styles.methodCard} testID="payment-method">
          <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.md }}>
            <View style={styles.stripeIcon}><Feather name="credit-card" size={18} color="#fff" /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.methodTitle}>Pay with Stripe</Text>
              <Text style={styles.methodSub}>Secure card payment · MVP mock confirmation</Text>
            </View>
            <Feather name="check-circle" size={20} color={theme.color.brand} />
          </View>
        </View>

        <Text style={styles.smallprint}>
          By tapping "Pay", you agree to Babybabel's terms and confirm the session details above. In MVP the payment is
          mocked — no card is charged; the booking simply flips to "paid".
        </Text>
      </ScrollView>

      <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, theme.space.lg) }]}>
        <Button
          title={`Pay $${(b.amount_cents / 100).toFixed(2)}`}
          onPress={pay}
          loading={paying}
          testID="payment-pay-btn"
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  receipt: { padding: theme.space.xl, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg },
  eyebrow: { color: theme.color.brand, fontWeight: "700", letterSpacing: 1, textTransform: "uppercase", fontSize: 11 },
  title: { fontSize: 26, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.xs, letterSpacing: -0.5 },
  sub: { color: theme.color.onSurfaceSecondary, marginTop: 4 },
  divider: { height: 1, backgroundColor: theme.color.border, marginVertical: theme.space.lg },
  lineRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  lineLabel: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.lg },
  lineValue: { color: theme.color.onSurface, fontSize: theme.font.lg, fontWeight: "600" },
  totalLabel: { color: theme.color.onSurface, fontSize: theme.font.xl, fontWeight: "700" },
  totalValue: { color: theme.color.brand, fontSize: theme.font.xl, fontWeight: "700" },
  methodCard: { marginTop: theme.space.xl, padding: theme.space.lg, borderRadius: theme.radius.lg, borderWidth: 2, borderColor: theme.color.brand, backgroundColor: theme.color.surface },
  stripeIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  methodTitle: { color: theme.color.onSurface, fontWeight: "700", fontSize: theme.font.lg },
  methodSub: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: 2 },
  smallprint: { color: theme.color.muted, fontSize: 12, marginTop: theme.space.xl, lineHeight: 18 },
  footer: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
});
