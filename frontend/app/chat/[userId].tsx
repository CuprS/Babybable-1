import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, FlatList, TextInput, Pressable, KeyboardAvoidingView, Platform, Modal, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { apiFetch } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { track } from "@/src/analytics";
import { useToast } from "@/src/toast";
import { Chip, Button, Input } from "@/src/ui";
import { slotStatus, HOUR_SLOTS, WeeklyAvailability } from "@/src/availability";

interface Invitation {
  price_cents: number; date: string; time: string; duration_minutes: number;
  language: string; note?: string; status: string; booking_id?: string | null;
}
interface Msg {
  id: string; from_user_id: string; to_user_id: string; text: string;
  kind: string; invitation?: Invitation | null; created_at: string;
  /** Contact or payment details shared before a booking (phone, email, address, payment, app, link). */
  flags?: string[];
}
interface ContactWarning { text: string; message: string }

const DURATIONS = [{ label: "60 min", value: 60 }, { label: "90 min", value: 90 }, { label: "2 hrs", value: 120 }, { label: "3 hrs", value: 180 }];
const TIMES = HOUR_SLOTS;
function nextDays(n: number) {
  const out: { key: string; label: string }[] = [];
  const now = new Date();
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const mo = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  for (let i = 0; i < n; i++) {
    const d = new Date(now); d.setDate(now.getDate() + i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.push({ key, label: `${wd[d.getDay()]} ${d.getDate()} ${mo[d.getMonth()]}` });
  }
  return out;
}

export default function Chat() {
  const { userId, name } = useLocalSearchParams<{ userId: string; name?: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const { show } = useToast();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [otherRole, setOtherRole] = useState<"parent" | "tutor" | "admin" | null>(null);
  const [otherTutorId, setOtherTutorId] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [warning, setWarning] = useState<ContactWarning | null>(null);
  const [sending, setSending] = useState(false);
  const listRef = useRef<FlatList>(null);

  const load = useCallback(async () => {
    if (!userId) return;
    try {
      const data = await apiFetch<Msg[]>(`/messages/thread/${userId}`);
      setMsgs(data);
    } catch {}
  }, [userId]);

  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);

  // Look up other user's role and tutor id (if they are a tutor).
  useEffect(() => {
    if (!userId) return;
    apiFetch<{ blocked: boolean }>(`/blocks/status/${userId}`).then((r) => setBlocked(r.blocked)).catch(() => {});
    apiFetch<{ role: string }>(`/tutors/by-user/${userId}`)
      .then((t: any) => { setOtherRole("tutor"); setOtherTutorId(t.id); })
      .catch(() => { setOtherRole("parent"); });
  }, [userId]);

  const send = async (confirmShare = false) => {
    const t = (confirmShare && warning ? warning.text : text).trim();
    if (!t || !userId || sending) return;
    setText("");
    setSending(true);
    try {
      const m = await apiFetch<Msg>("/messages", { method: "POST", body: JSON.stringify({ to_user_id: userId, text: t, confirm_share: confirmShare }) });
      track("chat_sent", { conversation_id: userId, message_type: "text" });
      setWarning(null);
      setMsgs((prev) => [...prev, m]);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 50);
    } catch (e: any) {
      setText(t);
      if (e?.status === 409 && e?.detail?.code === "contact_warning") {
        // Contact or payment details before a booking: explain, and let the person decide.
        track("chat_contact_warning", { kinds: (e.detail.kinds || []).join(",") });
        setWarning({ text: t, message: e.detail.message });
      } else {
        show({ kind: "error", title: "Message not sent", body: e?.message || "Try again" });
      }
    } finally {
      setSending(false);
    }
  };

  const acceptInvite = async (m: Msg) => {
    try {
      await apiFetch(`/messages/invitation/${m.id}/accept`, { method: "POST" });
      track("invitation_accepted", { message_id: m.id });
      show({ kind: "success", title: "Booked!", body: "See you soon — check the Bookings tab." });
      await load();
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't accept", body: e?.message || "Try again" });
    }
  };
  const declineInvite = async (m: Msg) => {
    try { await apiFetch(`/messages/invitation/${m.id}/decline`, { method: "POST" }); await load(); }
    catch (e: any) { show({ kind: "error", title: "Couldn't decline", body: e?.message || "Try again" }); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="chat-back" accessibilityRole="button" accessibilityLabel="Go back" hitSlop={12}>
          <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.name} numberOfLines={1}>{name || "Chat"}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.lg }}>
          {user?.role === "parent" && otherTutorId && !blocked ? (
            <Pressable
              onPress={() => router.push(`/tutor/${otherTutorId}`)}
              testID="chat-view-tutor"
              hitSlop={12}
              accessibilityRole="button"
              accessibilityLabel="View tutor profile"
            >
              <Feather name="user" size={22} color={theme.color.brand} />
            </Pressable>
          ) : null}
          {!blocked && !user?.is_admin && (
            <Pressable
              onPress={() => router.push(`/block/${userId}?name=${encodeURIComponent(name || "")}&from=chat`)}
              testID="chat-block-btn"
              hitSlop={12}
              accessibilityRole="button"
              accessibilityLabel="Block or report"
            >
              <Feather name="slash" size={20} color={theme.color.error} />
            </Pressable>
          )}
        </View>
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }} keyboardVerticalOffset={80}>
        <FlatList
          ref={listRef}
          testID="chat-messages"
          data={msgs}
          keyExtractor={(m) => m.id}
          contentContainerStyle={{ padding: theme.space.lg, gap: theme.space.sm, paddingBottom: theme.space.lg }}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
          renderItem={({ item }) => {
            const mine = item.from_user_id === user?.id;
            if (item.kind === "invitation" && item.invitation) {
              return <InvitationCard item={item} mine={mine} onAccept={() => acceptInvite(item)} onDecline={() => declineInvite(item)} amParent={user?.role === "parent"} />;
            }
            return (
              <View style={{ gap: 4 }}>
                <View style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
                  <Text style={{ color: mine ? "#fff" : theme.color.onSurface, fontSize: theme.font.lg }}>{item.text}</Text>
                </View>
                {item.flags?.length ? <SafetyNote mine={mine} testID={`chat-safety-note-${item.id}`} /> : null}
              </View>
            );
          }}
          ListEmptyComponent={blocked ? null : <Text style={{ color: theme.color.muted, textAlign: "center", marginTop: theme.space["3xl"] }}>Say hi 👋</Text>}
        />

        {blocked ? (
          <View style={styles.blockedBar} testID="chat-blocked-banner">
            <Feather name="slash" size={16} color={theme.color.onSurfaceSecondary} />
            <Text style={styles.blockedText}>You can no longer message each other.</Text>
          </View>
        ) : (
          <>
            {user?.role === "tutor" && (
              <Pressable style={styles.inviteBar} onPress={() => setInviteOpen(true)} testID="chat-open-invite">
                <Feather name="calendar" size={18} color={theme.color.brand} />
                <Text style={styles.inviteBarText}>Send a lesson invitation</Text>
                <Feather name="chevron-up" size={18} color={theme.color.brand} />
              </Pressable>
            )}

            <View style={styles.inputRow}>
              <TextInput
                testID="chat-input"
                value={text}
                onChangeText={setText}
                placeholder="Type a message"
                placeholderTextColor={theme.color.muted}
                style={styles.input}
                accessibilityLabel="Message"
                multiline
              />
              <Pressable onPress={() => send()} style={styles.send} testID="chat-send" accessibilityRole="button" accessibilityLabel="Send message" disabled={sending}>
                <Feather name="send" size={18} color="#fff" />
              </Pressable>
            </View>
          </>
        )}
      </KeyboardAvoidingView>

      <ContactWarningSheet
        warning={warning}
        sending={sending}
        onEdit={() => setWarning(null)}
        onSendAnyway={() => send(true)}
      />

      <InvitationComposer
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        onSent={async () => { setInviteOpen(false); await load(); show({ kind: "success", title: "Invitation sent" }); }}
        toUserId={String(userId)}
      />
    </SafeAreaView>
  );
}

/** Shown under a message that shared contact or payment details before the two had a booking. */
function SafetyNote({ mine, testID }: { mine: boolean; testID?: string }) {
  return (
    <View style={[safetyStyles.note, mine ? { alignSelf: "flex-end" } : { alignSelf: "flex-start" }]} testID={testID}>
      <Feather name="shield" size={14} color={theme.color.brandDark} />
      <Text style={safetyStyles.noteText}>
        {mine
          ? "You shared contact or payment details. Bookings and payments made outside Babybabel aren't protected."
          : "This message has contact or payment details. Never pay outside Babybabel — we can only protect bookings made here."}
      </Text>
    </View>
  );
}

function ContactWarningSheet({ warning, sending, onEdit, onSendAnyway }: {
  warning: ContactWarning | null; sending: boolean; onEdit: () => void; onSendAnyway: () => void;
}) {
  return (
    <Modal visible={!!warning} animationType="fade" transparent onRequestClose={onEdit}>
      <View style={safetyStyles.backdrop}>
        <View style={safetyStyles.sheet} testID="chat-contact-warning" accessibilityViewIsModal>
          <View style={safetyStyles.iconWrap}><Feather name="shield" size={28} color={theme.color.brandDark} /></View>
          <Text style={safetyStyles.title} accessibilityRole="header">Keep it safe on Babybabel</Text>
          <Text style={safetyStyles.body}>{warning?.message}</Text>
          <View style={safetyStyles.tips}>
            <Text style={safetyStyles.tip}>• Only pay through Babybabel. We can&apos;t refund or protect payments made any other way.</Text>
            <Text style={safetyStyles.tip}>• Meet only after a booking is confirmed in the app.</Text>
            <Text style={safetyStyles.tip}>• Our safety team may review messages that share contact details.</Text>
          </View>
          <Button title="Edit my message" onPress={onEdit} testID="chat-warning-edit" />
          <Pressable onPress={onSendAnyway} disabled={sending} style={safetyStyles.sendAnyway} accessibilityRole="button" testID="chat-warning-send">
            <Text style={safetyStyles.sendAnywayText}>{sending ? "Sending…" : "Send anyway"}</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

function InvitationCard({ item, mine, onAccept, onDecline, amParent }: { item: Msg; mine: boolean; onAccept: () => void; onDecline: () => void; amParent: boolean }) {
  const inv = item.invitation!;
  const router = useRouter();
  const price = (inv.price_cents / 100).toFixed(0);
  const statusColor = inv.status === "accepted" ? theme.color.success : inv.status === "declined" ? theme.color.error : theme.color.warning;
  const isAccepted = inv.status === "accepted" && !!inv.booking_id;
  const openReceipt = () => {
    if (!inv.booking_id) return;
    track("invitation_receipt_open", { message_id: item.id, booking_id: inv.booking_id });
    router.push(`/booking-detail/${inv.booking_id}`);
  };
  return (
    <Pressable
      onPress={isAccepted ? openReceipt : undefined}
      disabled={!isAccepted}
      style={[cardStyles.card, mine ? cardStyles.mine : cardStyles.theirs]}
      testID={`invitation-${item.id}`}
    >
      <View style={cardStyles.row}>
        <Feather name="calendar" size={16} color={theme.color.brand} />
        <Text style={cardStyles.title}>Lesson invitation</Text>
        <View style={[cardStyles.badge, { backgroundColor: statusColor }]}>
          <Text style={cardStyles.badgeText}>{inv.status}</Text>
        </View>
      </View>
      <Text style={cardStyles.big}>${price}</Text>
      <Text style={cardStyles.meta}>{inv.language} · {inv.date} at {inv.time} · {inv.duration_minutes} min</Text>
      {inv.note ? <Text style={cardStyles.note}>{inv.note}</Text> : null}
      {amParent && inv.status === "pending" && (
        <View style={cardStyles.actions}>
          <Pressable onPress={onDecline} style={[cardStyles.action, cardStyles.actionGhost]} testID={`invitation-${item.id}-decline`}>
            <Text style={{ color: theme.color.onSurface, fontWeight: "700" }}>Decline</Text>
          </Pressable>
          <Pressable onPress={onAccept} style={[cardStyles.action, cardStyles.actionAccept]} testID={`invitation-${item.id}-accept`}>
            <Text style={{ color: "#fff", fontWeight: "700" }}>Accept & book</Text>
          </Pressable>
        </View>
      )}
      {isAccepted && (
        <View style={cardStyles.receiptCta} testID={`invitation-${item.id}-receipt`}>
          <Feather name="file-text" size={14} color={theme.color.brand} />
          <Text style={cardStyles.receiptText}>Tap to view booking receipt</Text>
          <Feather name="chevron-right" size={14} color={theme.color.brand} />
        </View>
      )}
    </Pressable>
  );
}

function InvitationComposer({ open, onClose, onSent, toUserId }: { open: boolean; onClose: () => void; onSent: () => Promise<void>; toUserId: string }) {
  const days = nextDays(14);
  const [price, setPrice] = useState("40");
  const [date, setDate] = useState(days[0].key);
  const [time, setTime] = useState(TIMES[0]);
  const [duration, setDuration] = useState(60);
  const [language, setLanguage] = useState("English");
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [weekly, setWeekly] = useState<WeeklyAvailability>({});
  const [bookedSlots, setBookedSlots] = useState<{ date: string; time: string }[]>([]);
  const { show } = useToast();

  // Load the tutor's own weekly availability + booked slots so we can grey out unavailable/booked cells.
  useEffect(() => {
    if (!open) return;
    apiFetch<{ weekly_availability?: WeeklyAvailability; id: string }>("/tutors/me/profile")
      .then((prof) => {
        setWeekly((prof.weekly_availability as WeeklyAvailability) || {});
        return apiFetch<{ date: string; time: string }[]>(`/tutors/${prof.id}/booked-slots`);
      })
      .then((rows) => setBookedSlots(rows || []))
      .catch(() => {});
  }, [open]);

  // If the currently selected slot becomes invalid, hop to the first available one.
  useEffect(() => {
    if (!open) return;
    if (slotStatus(weekly, bookedSlots, date, time) === "ok") return;
    const first = TIMES.find((t) => slotStatus(weekly, bookedSlots, date, t) === "ok");
    if (first) setTime(first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, weekly, bookedSlots, open]);

  const submit = async () => {
    setSending(true);
    try {
      await apiFetch("/messages/invitation", {
        method: "POST",
        body: JSON.stringify({
          to_user_id: toUserId,
          price_cents: Math.max(100, Math.round(parseFloat(price) * 100)),
          date, time, duration_minutes: duration, language, note,
        }),
      });
      track("invitation_sent", { language, duration, price_cents: Math.round(parseFloat(price) * 100) });
      await onSent();
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't send", body: e?.message || "Try again" });
    } finally { setSending(false); }
  };
  return (
    <Modal visible={open} animationType="slide" transparent onRequestClose={onClose}>
      <View style={sheetStyles.backdrop}>
        <View style={sheetStyles.sheet} testID="invitation-composer">
          <View style={sheetStyles.grabber} />
          <View style={sheetStyles.header}>
            <Text style={sheetStyles.title}>Send lesson invitation</Text>
            <Pressable onPress={onClose} hitSlop={12} testID="invitation-close"><Feather name="x" size={22} color={theme.color.onSurface} /></Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: theme.space.lg, gap: theme.space.md }}>
            <Input label="Price you'd like ($)" value={price} onChangeText={setPrice} keyboardType="numeric" testID="invitation-price" />
            <Input label="Language" value={language} onChangeText={setLanguage} testID="invitation-language" />
            <Text style={sheetStyles.label}>Date</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: theme.space.sm, paddingRight: theme.space.xl }}>
              {days.map((d) => (
                <Chip key={d.key} label={d.label} selected={date === d.key} onPress={() => setDate(d.key)} testID={`invitation-date-${d.key}`} />
              ))}
            </ScrollView>
            <Text style={sheetStyles.label}>Time</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm }}>
              {TIMES.map((t) => {
                const status = slotStatus(weekly, bookedSlots, date, t);
                const disabled = status !== "ok";
                const selected = time === t;
                return (
                  <Pressable
                    key={t}
                    testID={`invitation-time-${t}`}
                    onPress={() => !disabled && setTime(t)}
                    disabled={disabled}
                    style={[
                      invSlotStyles.chip,
                      selected && !disabled && invSlotStyles.chipOn,
                      disabled && invSlotStyles.chipDisabled,
                    ]}
                  >
                    <Text style={[
                      invSlotStyles.text,
                      selected && !disabled && invSlotStyles.textOn,
                      disabled && invSlotStyles.textDisabled,
                    ]}>{t}</Text>
                    {status === "booked" && <Text style={invSlotStyles.tag}>Booked</Text>}
                  </Pressable>
                );
              })}
            </View>
            <Text style={sheetStyles.label}>Duration</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm }}>
              {DURATIONS.map((d) => (
                <Chip key={d.value} label={d.label} selected={duration === d.value} onPress={() => setDuration(d.value)} testID={`invitation-dur-${d.value}`} />
              ))}
            </View>
            <Input label="Note (optional)" value={note} onChangeText={setNote} multiline placeholder="Anything you'd like the family to know…" style={{ minHeight: 70, textAlignVertical: "top" }} testID="invitation-note" />
            <Button title="Send invitation" onPress={submit} loading={sending} testID="invitation-send" />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const safetyStyles = StyleSheet.create({
  note: { maxWidth: "85%", flexDirection: "row", alignItems: "flex-start", gap: 6, paddingHorizontal: theme.space.md, paddingVertical: 8, borderRadius: theme.radius.md, backgroundColor: theme.color.brandSoft },
  noteText: { flex: 1, color: theme.color.brandDark, fontSize: theme.font.base, lineHeight: 20 },
  backdrop: { flex: 1, backgroundColor: "rgba(44,36,33,0.55)", alignItems: "center", justifyContent: "center", padding: theme.space.xl },
  sheet: { width: "100%", maxWidth: 460, backgroundColor: theme.color.surface, borderRadius: theme.radius.lg, padding: theme.space.xl, gap: theme.space.md },
  iconWrap: { width: 56, height: 56, borderRadius: 28, backgroundColor: theme.color.brandSoft, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 22, fontWeight: "700", color: theme.color.onSurface },
  body: { fontSize: theme.font.lg, lineHeight: 24, color: theme.color.onSurfaceSecondary },
  tips: { gap: 6, padding: theme.space.md, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary },
  tip: { fontSize: theme.font.base, lineHeight: 21, color: theme.color.onSurfaceSecondary },
  sendAnyway: { minHeight: 48, alignItems: "center", justifyContent: "center" },
  sendAnywayText: { color: theme.color.onSurfaceSecondary, fontWeight: "700", fontSize: theme.font.lg, textDecorationLine: "underline" },
});

const invSlotStyles = StyleSheet.create({
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
  tag: { color: theme.color.muted, fontSize: 13, marginTop: 1 },
});

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  name: { flex: 1, textAlign: "center", fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginHorizontal: theme.space.md },
  bubble: { maxWidth: "78%", paddingHorizontal: theme.space.md, paddingVertical: 10, borderRadius: 18 },
  mine: { alignSelf: "flex-end", backgroundColor: theme.color.brand, borderBottomRightRadius: 4 },
  theirs: { alignSelf: "flex-start", backgroundColor: theme.color.surfaceSecondary, borderBottomLeftRadius: 4 },
  inviteBar: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, paddingHorizontal: theme.space.md, paddingVertical: theme.space.sm, backgroundColor: theme.color.brandSoft, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.color.brand },
  inviteBarText: { color: theme.color.brandDark, fontWeight: "700", flex: 1 },
  inputRow: { flexDirection: "row", alignItems: "flex-end", padding: theme.space.md, gap: theme.space.sm, borderTopColor: theme.color.border, borderTopWidth: StyleSheet.hairlineWidth, backgroundColor: theme.color.surface },
  blockedBar: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: theme.space.sm, padding: theme.space.lg, borderTopColor: theme.color.border, borderTopWidth: StyleSheet.hairlineWidth, backgroundColor: theme.color.surfaceSecondary },
  blockedText: { color: theme.color.onSurfaceSecondary, fontWeight: "500" },

  input: { flex: 1, minHeight: 40, maxHeight: 120, paddingHorizontal: theme.space.md, paddingVertical: 10, borderRadius: 20, backgroundColor: theme.color.surfaceSecondary, color: theme.color.onSurface, fontSize: theme.font.lg },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
});

const cardStyles = StyleSheet.create({
  card: { maxWidth: "88%", borderRadius: 18, padding: theme.space.md, gap: 6, borderWidth: 1, borderColor: theme.color.brand, backgroundColor: theme.color.surface },
  mine: { alignSelf: "flex-end" },
  theirs: { alignSelf: "flex-start" },
  row: { flexDirection: "row", alignItems: "center", gap: 6 },
  title: { flex: 1, fontWeight: "700", color: theme.color.onSurface },
  big: { fontSize: 28, fontWeight: "700", color: theme.color.brand, letterSpacing: -0.5, marginTop: 4 },
  meta: { color: theme.color.onSurfaceSecondary },
  note: { color: theme.color.onSurface, marginTop: 4, fontStyle: "italic" },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill },
  badgeText: { color: "#fff", fontWeight: "700", fontSize: 13, textTransform: "capitalize" },
  actions: { flexDirection: "row", gap: theme.space.sm, marginTop: theme.space.md },
  action: { flex: 1, height: 44, borderRadius: theme.radius.pill, alignItems: "center", justifyContent: "center" },
  actionGhost: { borderWidth: 1, borderColor: theme.color.borderStrong },
  actionAccept: { backgroundColor: theme.color.brand },
  receiptCta: {
    marginTop: theme.space.sm,
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.color.brandSoft,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.space.md, paddingVertical: 8,
  },
  receiptText: { flex: 1, color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.sm },
});

const sheetStyles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(44,36,33,0.5)", justifyContent: "flex-end" },
  sheet: { backgroundColor: theme.color.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, maxHeight: "88%" },
  grabber: { alignSelf: "center", width: 44, height: 4, borderRadius: 2, backgroundColor: theme.color.borderStrong, marginTop: 10 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: theme.space.lg, paddingBottom: theme.space.sm },
  title: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  label: { color: theme.color.onSurfaceSecondary, fontWeight: "600", fontSize: theme.font.sm },
});
