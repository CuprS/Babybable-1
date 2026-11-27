import React, { createContext, useCallback, useContext, useState } from "react";
import { View, Text, StyleSheet, Modal, Pressable, Linking, Platform } from "react-native";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "./theme";
import { Booking, Tutor } from "./api";
import { track } from "./analytics";

interface Payload {
  booking: Booking;
  tutor?: Tutor | null;
}

interface Ctx {
  openReminder: (p: Payload) => void;
}

const ReminderCtx = createContext<Ctx | undefined>(undefined);

export function SessionReminderProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<Payload | null>(null);

  const openReminder = useCallback((p: Payload) => {
    setPayload(p);
    setOpen(true);
  }, []);

  const close = () => { setOpen(false); setPayload(null); };

  return (
    <ReminderCtx.Provider value={{ openReminder }}>
      {children}
      <ReminderSheet open={open} onClose={close} payload={payload} />
    </ReminderCtx.Provider>
  );
}

export function useSessionReminder(): Ctx {
  const v = useContext(ReminderCtx);
  if (!v) throw new Error("useSessionReminder outside SessionReminderProvider");
  return v;
}

function ReminderSheet({ open, onClose, payload }: { open: boolean; onClose: () => void; payload: Payload | null }) {
  const router = useRouter();
  if (!payload) return null;
  const { booking, tutor } = payload;
  // Pick the closest tutor location coords for directions (fallback to legacy top-level lat/lng).
  const loc = (tutor?.locations || []).find((l) => l.latitude != null && l.longitude != null);
  const lat = loc?.latitude ?? tutor?.latitude ?? null;
  const lng = loc?.longitude ?? tutor?.longitude ?? null;
  const hasDirections = !booking.remote && !booking.is_au_pair && lat != null && lng != null;

  const openDirections = () => {
    if (lat == null || lng == null) return;
    // Native maps app on both platforms; web fallback opens Google Maps.
    const label = encodeURIComponent(tutor?.name || "Tutor");
    const url = Platform.select({
      ios: `maps:0,0?q=${label}@${lat},${lng}`,
      android: `geo:0,0?q=${lat},${lng}(${label})`,
      default: `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`,
    })!;
    track("reminder_directions_tap", { booking_id: booking.id, tutor_id: booking.tutor_id });
    Linking.openURL(url).catch(() => {
      // Fallback to Google Maps in-browser
      Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`);
    });
  };

  const openChat = () => {
    if (!tutor) return;
    track("reminder_chat_tap", { booking_id: booking.id, tutor_id: booking.tutor_id });
    onClose();
    router.push(`/chat/${tutor.user_id}?name=${encodeURIComponent(tutor.name)}`);
  };

  const openReceipt = () => {
    track("reminder_receipt_tap", { booking_id: booking.id });
    onClose();
    router.push(`/booking-detail/${booking.id}`);
  };

  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet} testID="reminder-sheet">
          <View style={styles.grabber} />
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.eyebrow}>Session today</Text>
              <Text style={styles.title}>{booking.time} · {tutor?.name || booking.tutor_name}</Text>
              <Text style={styles.sub}>{booking.language} · {booking.duration_minutes} min</Text>
            </View>
            <Pressable onPress={onClose} hitSlop={12} testID="reminder-close">
              <Feather name="x" size={22} color={theme.color.onSurface} />
            </Pressable>
          </View>

          {booking.remote ? (
            <View style={styles.remoteChip}>
              <Feather name="video" size={16} color={theme.color.brandDark} />
              <Text style={styles.remoteText}>Remote session — no travel needed.</Text>
            </View>
          ) : hasDirections ? null : (
            <View style={styles.remoteChip}>
              <Feather name="info" size={16} color={theme.color.brandDark} />
              <Text style={styles.remoteText}>Your tutor hasn&apos;t pinned a location — message them for the address.</Text>
            </View>
          )}

          <View style={styles.actions}>
            {hasDirections && (
              <Pressable style={styles.primary} onPress={openDirections} testID="reminder-directions">
                <Feather name="navigation" size={18} color="#fff" />
                <Text style={styles.primaryText}>Get directions</Text>
              </Pressable>
            )}
            <Pressable style={styles.secondary} onPress={openChat} testID="reminder-chat">
              <Feather name="message-circle" size={18} color={theme.color.brand} />
              <Text style={styles.secondaryText}>Message tutor</Text>
            </Pressable>
            <Pressable style={styles.ghost} onPress={openReceipt} testID="reminder-receipt">
              <Feather name="file-text" size={16} color={theme.color.onSurfaceSecondary} />
              <Text style={styles.ghostText}>View booking receipt</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(44,36,33,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.color.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingBottom: theme.space["3xl"],
  },
  grabber: { alignSelf: "center", width: 44, height: 4, borderRadius: 2, backgroundColor: theme.color.borderStrong, marginTop: 10 },
  header: { flexDirection: "row", alignItems: "flex-start", padding: theme.space.lg, paddingBottom: theme.space.sm, gap: theme.space.md },
  eyebrow: {
    color: theme.color.brand, fontWeight: "700", fontSize: 13,
    textTransform: "uppercase", letterSpacing: 0.6,
  },
  title: { fontSize: 22, fontWeight: "700", color: theme.color.onSurface, marginTop: 2, letterSpacing: -0.3 },
  sub: { color: theme.color.onSurfaceSecondary, marginTop: 2 },
  remoteChip: {
    marginHorizontal: theme.space.lg, marginTop: 4,
    flexDirection: "row", alignItems: "center", gap: 6,
    padding: theme.space.md, backgroundColor: theme.color.brandSoft,
    borderRadius: theme.radius.md,
  },
  remoteText: { color: theme.color.brandDark, fontWeight: "600", flex: 1 },
  actions: { paddingHorizontal: theme.space.lg, marginTop: theme.space.md, gap: theme.space.sm },
  primary: {
    height: 52, borderRadius: theme.radius.pill, backgroundColor: theme.color.brand,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  primaryText: { color: "#fff", fontWeight: "700", fontSize: theme.font.lg },
  secondary: {
    height: 52, borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.brand,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.color.surface,
  },
  secondaryText: { color: theme.color.brand, fontWeight: "700", fontSize: theme.font.lg },
  ghost: {
    marginTop: 4, height: 40, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
  },
  ghostText: { color: theme.color.onSurfaceSecondary, fontWeight: "600" },
});
