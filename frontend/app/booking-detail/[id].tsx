import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Alert, Platform, TextInput } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { apiFetch, Booking, bookingStatus, deviceTimeZone, money, zoneLabel } from "@/src/api";
import { theme } from "@/src/theme";
import { Button } from "@/src/ui";
import { useAuth } from "@/src/auth";
import { useReviewPrompt } from "@/src/reviewprompt";
import { useToast } from "@/src/toast";

/** Alert.alert has no buttons on web; fall back to window.confirm there. */
function confirmAction(title: string, message: string, confirmLabel: string): Promise<boolean> {
  if (Platform.OS === "web") return Promise.resolve(typeof window !== "undefined" && window.confirm(`${title}\n\n${message}`));
  return new Promise((resolve) => {
    Alert.alert(title, message, [
      { text: "Keep it", style: "cancel", onPress: () => resolve(false) },
      { text: confirmLabel, style: "destructive", onPress: () => resolve(true) },
    ]);
  });
}

export default function BookingDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const { openReview } = useReviewPrompt();
  const { show } = useToast();
  const [b, setB] = useState<Booking | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasReviewed, setHasReviewed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [declineNote, setDeclineNote] = useState("");
  const [showDecline, setShowDecline] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const data = await apiFetch<Booking>(`/bookings/${id}`);
      setB(data);
      if (user?.role === "parent") {
        const reviews = await apiFetch<{ booking_id?: string; parent_id: string }[]>(`/reviews/tutor/${data.tutor_id}`).catch(() => []);
        setHasReviewed(reviews.some((r) => r.booking_id === data.id && r.parent_id === user.id));
      }
    } catch {} finally { setLoading(false); }
  }, [id, user]);
  useEffect(() => { load(); }, [load]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  if (!b) return <View style={styles.center}><Text style={{ fontSize: theme.font.lg }}>Booking not found</Text></View>;

  const isParent = user?.role === "parent";
  const isTutor = user?.role === "tutor";
  const status = bookingStatus(b);
  const paid = b.payment_status === "paid";
  const canceled = b.payment_status === "canceled";
  const start = new Date(`${b.date}T${b.time}:00`);  // wall-clock in the session's zone
  const looksPast = start.getTime() + b.duration_minutes * 60000 < Date.now() - 24 * 3600 * 1000;
  const other = isParent ? b.tutor_name : b.parent_name;
  const canPay = isParent && b.payment_status === "pending";
  const canReview = isParent && paid && !hasReviewed && b.tutor_response !== "pending";
  const awaitingMe = isTutor && paid && b.tutor_response === "pending";
  const canChange = !canceled && b.payment_status !== "failed" && !looksPast;
  const deviceTz = deviceTimeZone();
  const showZone = !!b.timezone && b.timezone !== deviceTz;

  const toneColor = { success: theme.color.success, warning: theme.color.warning, error: theme.color.error, muted: theme.color.muted }[status.tone];
  const statusSub = canceled
    ? b.refund_status === "refunded" ? `Refunded ${money(b.refund_cents || 0)}.`
      : b.refund_status === "not_refunded" ? "Cancelled within the no-refund window."
      : b.refund_status === "failed" ? "The refund didn't go through yet — our team has been alerted."
      : "No payment was taken."
    : b.payment_status === "pending" ? "Confirm the details, then pay on the next screen."
    : b.tutor_response === "pending"
      ? isTutor ? `Please accept or decline${b.respond_by ? ` by ${new Date(b.respond_by).toLocaleString()}` : ""}.`
        : `Paid. ${b.tutor_name} has${b.respond_by ? ` until ${new Date(b.respond_by).toLocaleString()}` : " a day"} to confirm — if they don't, you're refunded in full.`
    : "You're all set — the family and tutor have been notified.";

  const respond = async (accept: boolean) => {
    setBusy(accept ? "accept" : "decline");
    try {
      const updated = await apiFetch<Booking>(`/bookings/${b.id}/respond`, { method: "POST", body: JSON.stringify({ accept, note: declineNote.trim() }) });
      setB(updated); setShowDecline(false);
      show({ kind: "success", title: accept ? "Booking confirmed" : "Booking declined", body: accept ? "The family has been told." : "The family gets a full refund." });
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't update", body: e?.message });
    } finally { setBusy(null); }
  };

  const cancel = async () => {
    setBusy("cancel");
    try {
      const p = await apiFetch<{ refund_cents: number; paid: boolean; policy_hours: number }>(`/bookings/${b.id}/cancel-preview`);
      const msg = !p.paid ? "No payment has been taken."
        : p.refund_cents > 0 ? `${isParent ? "You'll" : "The family will"} get a full refund of ${money(p.refund_cents)}.`
        : `This is less than ${p.policy_hours} hours before the start, so it won't be refunded.`;
      if (!(await confirmAction("Cancel this session?", msg, "Cancel session"))) return;
      const updated = await apiFetch<Booking>(`/bookings/${b.id}/cancel`, { method: "POST", body: JSON.stringify({ reason: "" }) });
      setB(updated);
      show({ kind: "success", title: "Session cancelled" });
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't cancel", body: e?.message });
    } finally { setBusy(null); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="booking-detail-back" hitSlop={12} accessibilityRole="button" accessibilityLabel="Go back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle} accessibilityRole="header">Booking</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: 180 }}>
        <View style={[styles.statusCard, { borderColor: toneColor }]} testID="booking-status-card">
          <Feather name={status.tone === "success" ? "check-circle" : canceled ? "x-circle" : "clock"} size={28} color={toneColor} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.statusTitle, { color: toneColor }]}>{status.label}</Text>
            <Text style={styles.statusSub}>{statusSub}</Text>
          </View>
        </View>

        {awaitingMe && (
          <View style={styles.respondCard} testID="booking-respond">
            <Text style={styles.respondTitle}>New request from {b.parent_name}</Text>
            {showDecline ? (
              <>
                <TextInput value={declineNote} onChangeText={setDeclineNote} placeholder="Optional note for the family (e.g. I'm away that week)"
                  placeholderTextColor={theme.color.muted} style={styles.noteInput} multiline maxLength={500} testID="booking-decline-note" />
                <View style={styles.btnRow}>
                  <Button title="Back" variant="ghost" onPress={() => setShowDecline(false)} style={{ flex: 1 }} />
                  <Button title="Decline" onPress={() => respond(false)} loading={busy === "decline"} style={{ flex: 1, backgroundColor: theme.color.error }} testID="booking-decline-confirm" />
                </View>
              </>
            ) : (
              <View style={styles.btnRow}>
                <Button title="Decline" variant="ghost" onPress={() => setShowDecline(true)} style={{ flex: 1 }} testID="booking-decline" />
                <Button title="Accept" onPress={() => respond(true)} loading={busy === "accept"} style={{ flex: 1 }} testID="booking-accept" />
              </View>
            )}
          </View>
        )}

        <Text style={styles.section}>Summary</Text>
        <View style={styles.card}>
          <Row icon="user" label={isParent ? "Tutor" : "Parent"} value={other} />
          <Row icon="calendar" label="Date" value={`${b.date} · ${b.time}`} extra={showZone ? `${zoneLabel(b.timezone)} (the tutor's local time)` : undefined} />
          <Row icon="clock" label="Duration" value={`${b.duration_minutes} min`} />
          <Row icon="book-open" label="Language" value={b.language} />
          {b.is_au_pair && <Row icon="home" label="Booking type" value={`Au-pair · ${b.lessons_count} lessons`} />}
          {b.is_au_pair && !!b.housing_offered && <Row icon="home" label="Housing offered" value={b.housing_offered} />}
          {!b.is_au_pair && b.remote && <Row icon="video" label="Booking type" value="Remote" />}
          {!b.is_au_pair && !b.remote && <Row icon="map-pin" label="Booking type" value="In-person"
            extra={b.distance_miles != null ? `${b.distance_miles} mi away` : undefined} />}
          {b.notes ? <Row icon="edit-3" label="Notes" value={b.notes} /> : null}
          {canceled && b.cancel_reason ? <Row icon="info" label="Cancellation" value={b.cancel_reason} /> : null}
        </View>

        <Text style={styles.section}>{isTutor ? "Your earnings" : "Total"}</Text>
        <View style={styles.totalCard}>
          {b.platform_fee_cents ? (
            <View style={{ alignSelf: "stretch", marginBottom: theme.space.sm, gap: 2 }}>
              <View style={styles.line}><Text style={styles.lineText}>Session</Text><Text style={styles.lineText}>{money(b.amount_cents - b.platform_fee_cents)}</Text></View>
              <View style={styles.line}><Text style={styles.lineText}>Platform fee (1%, paid by the family)</Text><Text style={styles.lineText}>{money(b.platform_fee_cents)}</Text></View>
            </View>
          ) : null}
          <Text style={styles.total}>{money(isTutor ? b.amount_cents - (b.platform_fee_cents || 0) : b.amount_cents)}</Text>
        </View>

        {canReview && (
          <Pressable testID="booking-rate-btn" onPress={() => openReview({ bookingId: b.id, tutorId: b.tutor_id, tutorName: b.tutor_name })} style={styles.rateCta} accessibilityRole="button">
            <Feather name="star" size={20} color="#fff" />
            <View style={{ flex: 1 }}>
              <Text style={styles.rateTitle}>Rate your session</Text>
              <Text style={styles.rateSub}>Share a quick word about {b.tutor_name}</Text>
            </View>
            <Feather name="chevron-right" size={20} color="#fff" />
          </Pressable>
        )}
        {isParent && paid && hasReviewed && (
          <View style={styles.rateDone} testID="booking-already-rated">
            <Feather name="check-circle" size={18} color={theme.color.success} />
            <Text style={styles.rateDoneText}>Review submitted — thanks!</Text>
          </View>
        )}

        {canChange && (isParent || isTutor) && (
          <View style={{ gap: theme.space.sm, marginTop: theme.space.xl }}>
            {paid && (
              <Button title="Move to another time" variant="secondary" testID="booking-reschedule"
                onPress={() => router.push({ pathname: "/booking/[tutorId]", params: { tutorId: b.tutor_id, reschedule: b.id } })} />
            )}
            <Pressable onPress={cancel} disabled={busy === "cancel"} style={styles.cancelBtn} testID="booking-cancel" accessibilityRole="button">
              {busy === "cancel" ? <ActivityIndicator color={theme.color.error} /> : <Text style={styles.cancelText}>Cancel session</Text>}
            </Pressable>
            <Text style={styles.policy}>Families get a full refund if they cancel at least 24 hours ahead, or whenever the tutor cancels.</Text>
          </View>
        )}
      </ScrollView>

      {canPay && (
        <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, theme.space.lg) }]}>
          <Button title={`Continue to payment · ${money(b.amount_cents)}`} onPress={() => router.push(`/payment/${b.id}`)} testID="booking-detail-pay-btn" />
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
  statusCard: { flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.lg, borderRadius: theme.radius.lg, borderWidth: 2, backgroundColor: theme.color.surfaceSecondary },
  statusTitle: { fontSize: theme.font.xl, fontWeight: "700" },
  statusSub: { marginTop: 4, fontSize: theme.font.base, color: theme.color.onSurfaceSecondary, lineHeight: 20 },
  respondCard: { marginTop: theme.space.lg, padding: theme.space.lg, borderRadius: theme.radius.lg, backgroundColor: theme.color.brandSoft, gap: theme.space.md },
  respondTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.brandDark },
  btnRow: { flexDirection: "row", gap: theme.space.sm },
  noteInput: { minHeight: 72, borderWidth: 1, borderColor: theme.color.borderStrong, borderRadius: theme.radius.md, padding: theme.space.md, color: theme.color.onSurface, backgroundColor: theme.color.surface, textAlignVertical: "top", fontSize: theme.font.base },
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  card: { backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, padding: theme.space.lg, gap: theme.space.lg },
  row: { flexDirection: "row", alignItems: "flex-start", gap: theme.space.md },
  rowLabel: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, fontWeight: "600" },
  rowValue: { color: theme.color.onSurface, fontSize: theme.font.lg, marginTop: 2 },
  rowExtra: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: 2 },
  totalCard: { backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, padding: theme.space.xl, alignItems: "center" },
  line: { flexDirection: "row", justifyContent: "space-between", gap: theme.space.md },
  lineText: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base },
  total: { fontSize: 40, fontWeight: "700", color: theme.color.brandDark, letterSpacing: -1 },
  footer: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  rateCta: { marginTop: theme.space.xl, flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.lg, borderRadius: theme.radius.lg, backgroundColor: theme.color.brandDark },
  rateTitle: { color: "#fff", fontWeight: "700", fontSize: theme.font.lg },
  rateSub: { color: "rgba(255,255,255,0.9)", marginTop: 2, fontSize: theme.font.sm },
  rateDone: { marginTop: theme.space.xl, flexDirection: "row", alignItems: "center", gap: theme.space.sm, padding: theme.space.md, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary },
  rateDoneText: { color: theme.color.onSurface, fontWeight: "600" },
  cancelBtn: { minHeight: 48, alignItems: "center", justifyContent: "center", borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.error },
  cancelText: { color: theme.color.error, fontWeight: "700", fontSize: theme.font.lg },
  policy: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, textAlign: "center", lineHeight: 18 },
});
