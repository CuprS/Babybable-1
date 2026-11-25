import { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { apiFetch, Tutor, Booking, deviceTimeZone, zoneLabel } from "@/src/api";
import { theme } from "@/src/theme";
import { Chip, Button } from "@/src/ui";
import { track } from "@/src/analytics";
import { slotStatus, HOUR_SLOTS, WeeklyAvailability } from "@/src/availability";

const DURATIONS = [
  { label: "60 min", value: 60 },
  { label: "90 min", value: 90 },
  { label: "2 hrs", value: 120 },
  { label: "3 hrs", value: 180 },
];
const TIMES = HOUR_SLOTS;

function nextDays(n: number) {
  const days: { key: string; date: string; day: number; month: string; weekday: string }[] = [];
  const now = new Date();
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const weekdays = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  for (let i = 0; i < n; i++) {
    const d = new Date(now); d.setDate(now.getDate() + i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    days.push({ key, date: key, day: d.getDate(), month: months[d.getMonth()], weekday: weekdays[d.getDay()] });
  }
  return days;
}

export default function BookingScreen() {
  // `reschedule` = id of an existing booking to move instead of creating a new one.
  const { tutorId, reschedule } = useLocalSearchParams<{ tutorId: string; reschedule?: string }>();
  const [existing, setExisting] = useState<Booking | null>(null);
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [tutor, setTutor] = useState<Tutor | null>(null);
  const [language, setLanguage] = useState<string>("");
  const [date, setDate] = useState<string>("");
  const [time, setTime] = useState<string>("");
  const [duration, setDuration] = useState(60);
  const [notes, setNotes] = useState("");
  const [isAuPair, setIsAuPair] = useState(false);
  const [housing, setHousing] = useState("");
  const [lessons, setLessons] = useState(1);
  const [loading, setLoading] = useState(true);
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState("");
  const [bookedSlots, setBookedSlots] = useState<{ date: string; time: string }[]>([]);

  const days = useMemo(() => nextDays(14), []);

  useEffect(() => {
    if (!tutorId) return;
    apiFetch<Tutor>(`/tutors/${tutorId}`).then((t) => {
      setTutor(t);
      setLanguage(t.languages[0] || "");
      setDate(days[0].date);
      setTime(TIMES[0]);
    }).finally(() => setLoading(false));
    apiFetch<{ date: string; time: string }[]>(`/tutors/${tutorId}/booked-slots`)
      .then(setBookedSlots)
      .catch(() => {});
  }, [tutorId, days]);

  // Reschedule mode: start from the booking being moved.
  useEffect(() => {
    if (!reschedule) return;
    apiFetch<Booking>(`/bookings/${reschedule}`).then((b) => {
      setExisting(b);
      setLanguage(b.language);
      setDuration(b.duration_minutes);
      setIsAuPair(!!b.is_au_pair);
    }).catch(() => setError("Couldn't load the booking to move."));
  }, [reschedule]);

  // The booking being moved shouldn't block its own hours.
  const blockedSlots = useMemo(() => {
    if (!existing) return bookedSlots;
    const startH = parseInt(existing.time.slice(0, 2), 10);
    const hours = Math.ceil((parseInt(existing.time.slice(3), 10) + existing.duration_minutes) / 60);
    const own = new Set(Array.from({ length: hours }, (_, i) => `${existing.date} ${String(startH + i).padStart(2, "0")}:00`));
    let removed = 0;
    return bookedSlots.filter((s) => {
      if (removed < own.size && own.has(`${s.date} ${s.time}`)) { removed += 1; return false; }
      return true;
    });
  }, [bookedSlots, existing]);

  // When date changes, if the currently picked time is no longer bookable, jump to first open slot.
  useEffect(() => {
    if (!tutor || !date || isAuPair) return;
    const weekly = (tutor.weekly_availability as WeeklyAvailability) || {};
    if (slotStatus(weekly, blockedSlots, date, time) !== "ok") {
      const first = TIMES.find((t) => slotStatus(weekly, blockedSlots, date, t) === "ok");
      if (first) setTime(first);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, tutor, blockedSlots, isAuPair]);

  if (loading || !tutor) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;

  const effectiveLessons = isAuPair ? Math.max(30, lessons) : lessons;
  const baseCents = Math.ceil((tutor.hourly_rate_cents * duration) / 60) * effectiveLessons;
  const feeCents = Math.max(1, Math.round(baseCents * 0.01));
  const totalCents = baseCents + feeCents;

  const confirmBooking = async () => {
    setBooking(true); setError("");
    if (existing) {
      try {
        await apiFetch<Booking>(`/bookings/${existing.id}/reschedule`, { method: "POST", body: JSON.stringify({ date, time }) });
        track("booking_rescheduled", { booking_id: existing.id });
        router.replace(`/booking-detail/${existing.id}`);
      } catch (e: any) {
        setError(e?.message || "Couldn't move the session");
      } finally { setBooking(false); }
      return;
    }
    try {
      const b = await apiFetch<Booking>("/bookings", {
        method: "POST",
        body: JSON.stringify({
          tutor_id: tutor.id, date, time, duration_minutes: duration, language, notes,
          is_au_pair: isAuPair, lessons_count: effectiveLessons,
          housing_offered: isAuPair ? housing.trim() : "",
        }),
      });
      track("booking_submitted", { booking_id: b.id, tutor_id: tutor.id, language, duration_minutes: duration, is_au_pair: isAuPair, lessons: effectiveLessons, housing_len: isAuPair ? housing.trim().length : 0 });
      router.replace(`/booking-detail/${b.id}`);
    } catch (e: any) {
      setError(e?.message || "Booking failed");
    } finally { setBooking(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="booking-back" accessibilityRole="button" accessibilityLabel="Go back">
          <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.title} accessibilityRole="header">{existing ? "Move session" : `Book ${tutor.name.split(" ")[0]}`}</Text>
        <View style={{ width: 24 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: 160 }}>
        {existing && (
          <View style={styles.hint} testID="booking-reschedule-hint">
            <Feather name="repeat" size={16} color={theme.color.brandDark} />
            <Text style={styles.hintText}>Currently {existing.date} at {existing.time}. Pick a new day and time — nothing extra to pay.</Text>
          </View>
        )}
        {!!tutor.timezone && tutor.timezone !== deviceTimeZone() && (
          <View style={styles.hint} testID="booking-timezone-hint">
            <Feather name="globe" size={16} color={theme.color.brandDark} />
            <Text style={styles.hintText}>Times are shown in {zoneLabel(tutor.timezone)}, where {tutor.name.split(" ")[0]} teaches.</Text>
          </View>
        )}
        {!existing && <Text style={styles.section}>Language</Text>}
        {!existing && (
          <View style={{ flexDirection: "row", gap: theme.space.sm, flexWrap: "wrap" }}>
            {tutor.languages.map((l) => (
              <Chip key={l} label={l} selected={language === l} onPress={() => setLanguage(l)} testID={`booking-lang-${l}`} />
            ))}
          </View>
        )}

        <Text style={styles.section}>Date</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: theme.space.sm, paddingRight: theme.space.xl }}>
          {days.map((d) => {
            const selected = d.date === date;
            return (
              <Pressable
                key={d.key}
                testID={`booking-date-${d.key}`}
                onPress={() => setDate(d.date)}
                style={[styles.dateCell, selected && styles.dateCellSelected]}
              >
                <Text style={[styles.dateWeek, selected && { color: theme.color.onBrand }]}>{d.weekday}</Text>
                <Text style={[styles.dateDay, selected && { color: theme.color.onBrand }]}>{d.day}</Text>
                <Text style={[styles.dateMonth, selected && { color: theme.color.onBrand }]}>{d.month}</Text>
              </Pressable>
            );
          })}
        </ScrollView>

        <Text style={styles.section}>Time</Text>
        <View style={{ flexDirection: "row", gap: theme.space.sm, flexWrap: "wrap" }}>
          {TIMES.map((t) => {
            const weekly = (tutor?.weekly_availability as WeeklyAvailability) || {};
            const status = isAuPair ? "ok" : slotStatus(weekly, blockedSlots, date, t);
            const disabled = status !== "ok";
            const selected = time === t;
            return (
              <Pressable
                key={t}
                testID={`booking-time-${t}`}
                onPress={() => !disabled && setTime(t)}
                disabled={disabled}
                style={[
                  slotChipStyles.chip,
                  selected && !disabled && slotChipStyles.chipOn,
                  disabled && slotChipStyles.chipDisabled,
                ]}
              >
                <Text style={[
                  slotChipStyles.text,
                  selected && !disabled && slotChipStyles.textOn,
                  disabled && slotChipStyles.textDisabled,
                ]}>{t}</Text>
                {status === "booked" && <Text style={slotChipStyles.tag}>Booked</Text>}
              </Pressable>
            );
          })}
        </View>

        {!existing && (<>
        <Text style={styles.section}>Duration</Text>
        <View style={{ flexDirection: "row", gap: theme.space.sm, flexWrap: "wrap" }}>
          {DURATIONS.map((d) => (
            <Chip key={d.value} label={d.label} selected={duration === d.value} onPress={() => setDuration(d.value)} testID={`booking-dur-${d.value}`} />
          ))}
        </View>

        <Text style={styles.section}>Booking type</Text>
        <View style={{ flexDirection: "row", gap: theme.space.sm }}>
          <Pressable
            onPress={() => { setIsAuPair(false); setLessons(1); }}
            style={[styles.typeCard, !isAuPair && styles.typeCardOn]}
            testID="booking-type-single"
          >
            <Feather name="calendar" size={18} color={!isAuPair ? theme.color.onBrand : theme.color.onSurface} />
            <Text style={[styles.typeTitle, !isAuPair && { color: theme.color.onBrand }]}>Single session</Text>
            <Text style={[styles.typeSub, !isAuPair && { color: "rgba(255,255,255,0.85)" }]}>Within 100 mi or remote</Text>
          </Pressable>
          <Pressable
            onPress={() => { setIsAuPair(true); setLessons(30); }}
            style={[styles.typeCard, isAuPair && styles.typeCardOn]}
            testID="booking-type-aupair"
          >
            <Feather name="home" size={18} color={isAuPair ? theme.color.onBrand : theme.color.onSurface} />
            <Text style={[styles.typeTitle, isAuPair && { color: theme.color.onBrand }]}>Au-pair</Text>
            <Text style={[styles.typeSub, isAuPair && { color: "rgba(255,255,255,0.85)" }]}>Any distance · 30+ lessons</Text>
          </Pressable>
        </View>

        {isAuPair && (
          <View style={styles.stepperRow} testID="booking-lessons-stepper">
            <Text style={{ color: theme.color.onSurfaceSecondary }}>Lessons</Text>
            <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.md }}>
              <Pressable onPress={() => setLessons((n) => Math.max(30, n - 1))} style={styles.stepBtn} testID="booking-lessons-minus"><Feather name="minus" size={16} color={theme.color.onSurface} /></Pressable>
              <Text style={styles.stepValue}>{Math.max(30, lessons)}</Text>
              <Pressable onPress={() => setLessons((n) => Math.min(200, n + 1))} style={styles.stepBtn} testID="booking-lessons-plus"><Feather name="plus" size={16} color={theme.color.onSurface} /></Pressable>
            </View>
          </View>
        )}
        {isAuPair && (
          <View style={styles.housingBlock} testID="booking-housing">
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 }}>
              <Feather name="home" size={16} color={theme.color.brandDark} />
              <Text style={styles.housingLabel}>Housing offered</Text>
              <Text style={styles.housingOpt}>optional</Text>
            </View>
            <Text style={styles.housingHint}>Give the tutor a warm sense of where they&apos;ll live — private room, meals included, family pets, etc.</Text>
            <TextInput
              testID="booking-housing-input"
              multiline
              value={housing}
              onChangeText={setHousing}
              placeholder="e.g. Private ensuite room, meals included, family of 4 + one friendly dog…"
              placeholderTextColor={theme.color.muted}
              style={styles.housingInput}
              maxLength={800}
            />
            <Text style={styles.housingCount}>{housing.trim().length}/800</Text>
          </View>
        )}
        {!isAuPair && tutor.allows_remote && (
          <View style={styles.hint} testID="booking-remote-hint">
            <Feather name="video" size={14} color={theme.color.brandDark} />
            <Text style={styles.hintText}>This tutor offers remote lessons — distance doesn&apos;t matter.</Text>
          </View>
        )}
        {!isAuPair && !tutor.allows_remote && (
          <View style={styles.hint}>
            <Feather name="map-pin" size={14} color={theme.color.brandDark} />
            <Text style={styles.hintText}>In-person only. Booking blocks if you&apos;re more than 100 mi away.</Text>
          </View>
        )}

        <Text style={styles.section}>Notes (optional)</Text>
        <TextInput
          testID="booking-notes"
          multiline
          value={notes}
          onChangeText={setNotes}
          placeholder="Any special requests?"
          placeholderTextColor={theme.color.muted}
          style={styles.notes}
        />

        <View style={styles.summary}>
          <Text style={styles.summaryTitle}>Summary</Text>
          <Row label={`$${(tutor.hourly_rate_cents / 100).toFixed(0)}/hr × ${duration} min${effectiveLessons > 1 ? ` × ${effectiveLessons} lessons` : ""}`} value={`$${(baseCents / 100).toFixed(2)}`} />
          <Row label="Platform fee (1%)" value={`$${(feeCents / 100).toFixed(2)}`} />
          <View style={{ height: 1, backgroundColor: theme.color.border, marginVertical: theme.space.md }} />
          <Row label="Total" value={`$${(totalCents / 100).toFixed(2)}`} bold />
        </View>
        </>)}

        {error ? <Text style={{ color: theme.color.error, marginTop: theme.space.md }}>{error}</Text> : null}
      </ScrollView>

      <View style={[styles.footer, { paddingBottom: Math.max(insets.bottom, theme.space.lg) }]}>
        <Button
          testID="booking-confirm-btn"
          title={existing ? `Move to ${date} at ${time}` : `Continue · $${(totalCents / 100).toFixed(2)}`}
          onPress={confirmBooking}
          loading={booking}
        />
        <Text style={styles.stripeNote}>
          {existing ? "The other side is notified straight away." : "Review and pay on the next screen. The tutor then confirms your request."}
        </Text>
      </View>
    </SafeAreaView>
  );
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
      <Text style={{ color: theme.color.onSurfaceSecondary, fontSize: theme.font.lg, fontWeight: bold ? "700" : "500" }}>{label}</Text>
      <Text style={{ color: theme.color.onSurface, fontSize: theme.font.lg, fontWeight: bold ? "700" : "600" }}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.xl, marginBottom: theme.space.md },
  dateCell: { width: 68, height: 88, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  dateCellSelected: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  dateWeek: { color: theme.color.onSurfaceSecondary, fontSize: 12, fontWeight: "600" },
  dateDay: { color: theme.color.onSurface, fontSize: 22, fontWeight: "700", marginTop: 2 },
  dateMonth: { color: theme.color.onSurfaceSecondary, fontSize: 12 },
  notes: { minHeight: 80, borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.md, padding: theme.space.md, textAlignVertical: "top", color: theme.color.onSurface },
  housingBlock: {
    marginTop: theme.space.md,
    padding: theme.space.lg,
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.color.brand,
    backgroundColor: theme.color.brandSoft,
    gap: 4,
  },
  housingLabel: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.lg, flex: 1 },
  housingOpt: { color: theme.color.brandDark, opacity: 0.75, fontSize: 12, textTransform: "uppercase", letterSpacing: 0.5 },
  housingHint: { color: theme.color.brandDark, opacity: 0.85, fontSize: theme.font.sm, marginBottom: 6 },
  housingInput: {
    minHeight: 96,
    borderWidth: 1,
    borderColor: theme.color.brand,
    borderRadius: theme.radius.md,
    padding: theme.space.md,
    color: theme.color.onSurface,
    textAlignVertical: "top",
    backgroundColor: theme.color.surface,
  },
  housingCount: { color: theme.color.brandDark, opacity: 0.65, fontSize: 12, textAlign: "right" },
  summary: { marginTop: theme.space.xl, backgroundColor: theme.color.surfaceSecondary, padding: theme.space.lg, borderRadius: theme.radius.lg, gap: theme.space.sm },
  summaryTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface, marginBottom: theme.space.xs },
  footer: { position: "absolute", left: 0, right: 0, bottom: 0, padding: theme.space.lg, backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border },
  stripeNote: { textAlign: "center", color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: theme.space.sm },
  typeCard: { flex: 1, padding: theme.space.md, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary, gap: 4 },
  typeCardOn: { backgroundColor: theme.color.brand },
  typeTitle: { fontWeight: "700", color: theme.color.onSurface, fontSize: theme.font.lg },
  typeSub: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  stepperRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: theme.space.md, padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md },
  stepBtn: { width: 34, height: 34, borderRadius: 17, backgroundColor: theme.color.surface, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: theme.color.border },
  stepValue: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, minWidth: 32, textAlign: "center" },
  hint: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, marginTop: theme.space.sm, padding: theme.space.md, backgroundColor: theme.color.brandSoft, borderRadius: theme.radius.md },
  hintText: { color: theme.color.brandDark, fontSize: theme.font.sm, flex: 1 },
});

const slotChipStyles = StyleSheet.create({
  chip: {
    minWidth: 66, paddingHorizontal: theme.space.md, paddingVertical: 6,
    borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.borderStrong,
    backgroundColor: "transparent", alignItems: "center", justifyContent: "center",
  },
  chipOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipDisabled: { backgroundColor: theme.color.surfaceSecondary, borderColor: theme.color.border, opacity: 0.6 },
  text: { color: theme.color.onSurface, fontWeight: "600", fontSize: theme.font.base },
  textOn: { color: theme.color.onBrand },
  textDisabled: { color: theme.color.muted, textDecorationLine: "line-through" },
  tag: { color: theme.color.muted, fontSize: 12, marginTop: 1 },
});
