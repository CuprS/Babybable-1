import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator, Pressable } from "react-native";
import { theme } from "./theme";
import { apiFetch } from "./api";
import { useToast } from "./toast";

interface Person { id: string; name: string; role: string; suspended?: boolean }
interface Flag {
  id: string; kinds: string[]; text: string; warned: boolean; created_at: string; sender_flag_count: number;
  from_user?: Person | null; to_user?: Person | null;
}

const KIND_LABEL: Record<string, string> = {
  phone: "Phone number", email: "Email", address: "Address", payment: "Outside payment", app: "Other app", link: "Link",
};

/** Admin dashboard section: messages that shared contact or payment details before a booking. */
export function AdminMessageSafetyPanel({ reloadKey }: { reloadKey: number }) {
  const [flags, setFlags] = useState<Flag[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const { show } = useToast();

  const load = useCallback(() => {
    apiFetch<{ flags: Flag[] }>("/admin/message-flags").then((r) => setFlags(r.flags)).catch(() => setFlags([]));
  }, []);
  useEffect(load, [load, reloadKey]);

  const resolve = async (f: Flag, outcome: "fine" | "reviewed") => {
    setBusy(f.id);
    try {
      await apiFetch(`/admin/message-flags/${f.id}/resolve`, { method: "POST", body: JSON.stringify({ outcome }) });
      setFlags((prev) => (prev || []).filter((x) => x.id !== f.id));
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't update", body: e?.message });
    } finally { setBusy(null); }
  };

  return (
    <View testID="admin-message-safety-panel">
      <Text style={styles.section}>Message safety {flags && flags.length ? `(${flags.length})` : ""}</Text>
      <Text style={styles.intro}>
        Messages that shared contact details, an address or an outside payment method before the two people had a booking.
        The sender was warned first. Look for patterns, such as one tutor asking many families to pay outside the site.
      </Text>
      {flags === null ? <ActivityIndicator color={theme.color.brand} /> : flags.length === 0 ? (
        <Text style={styles.muted}>Nothing to review.</Text>
      ) : flags.map((f) => (
        <View key={f.id} style={styles.card} testID={`admin-flag-${f.id}`}>
          <View style={styles.row}>
            <View style={styles.pills}>
              {f.kinds.map((k) => (
                <View key={k} style={[styles.pill, k === "payment" && styles.pillUrgent]}>
                  <Text style={[styles.pillText, k === "payment" && styles.pillTextUrgent]}>{KIND_LABEL[k] || k}</Text>
                </View>
              ))}
            </View>
            <Text style={styles.date}>{new Date(f.created_at).toLocaleString()}</Text>
          </View>
          <Text style={styles.line}>
            <Text style={styles.bold}>{f.from_user?.name || "Deleted user"}</Text> ({f.from_user?.role || "?"}) to{" "}
            <Text style={styles.bold}>{f.to_user?.name || "Deleted user"}</Text> ({f.to_user?.role || "?"})
          </Text>
          {f.sender_flag_count > 1 ? (
            <Text style={styles.repeat}>This sender has been flagged {f.sender_flag_count} times.</Text>
          ) : null}
          {f.from_user?.suspended ? <Text style={styles.repeat}>The sender&apos;s account is paused.</Text> : null}
          <Text style={styles.quote}>&ldquo;{f.text}&rdquo;</Text>
          {!f.warned ? <Text style={styles.muted}>Sent in a lesson-invitation note.</Text> : null}
          <View style={styles.actions}>
            <Pressable onPress={() => resolve(f, "fine")} disabled={busy === f.id} style={[styles.btn, styles.btnGhost]}
              accessibilityRole="button" testID={`admin-flag-${f.id}-fine`}>
              <Text style={styles.btnGhostText}>Looks fine</Text>
            </Pressable>
            <Pressable onPress={() => resolve(f, "reviewed")} disabled={busy === f.id} style={[styles.btn, styles.btnMain]}
              accessibilityRole="button" testID={`admin-flag-${f.id}-reviewed`}>
              <Text style={styles.btnMainText}>Reviewed, handled</Text>
            </Pressable>
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.sm },
  intro: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, lineHeight: 20, marginBottom: theme.space.md },
  muted: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  card: { padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, marginBottom: theme.space.sm, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: theme.space.sm, flexWrap: "wrap" },
  pills: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  pill: { paddingHorizontal: theme.space.sm, paddingVertical: 2, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft },
  pillUrgent: { backgroundColor: theme.color.error },
  pillText: { color: theme.color.brandDark, fontWeight: "700", fontSize: 13 },
  pillTextUrgent: { color: theme.color.onBrand },
  date: { color: theme.color.onSurfaceSecondary, fontSize: 13 },
  line: { color: theme.color.onSurface, lineHeight: 20 },
  bold: { fontWeight: "700" },
  repeat: { color: theme.color.error, fontWeight: "700", fontSize: theme.font.sm },
  quote: { color: theme.color.onSurface, fontStyle: "italic", lineHeight: 21, backgroundColor: theme.color.surface, padding: theme.space.sm, borderRadius: theme.radius.sm },
  actions: { flexDirection: "row", gap: theme.space.sm, marginTop: 4 },
  btn: { flex: 1, minHeight: 44, borderRadius: theme.radius.pill, alignItems: "center", justifyContent: "center", paddingHorizontal: theme.space.md },
  btnGhost: { borderWidth: 1, borderColor: theme.color.borderStrong },
  btnGhostText: { color: theme.color.onSurface, fontWeight: "700" },
  btnMain: { backgroundColor: theme.color.brandDark },
  btnMainText: { color: "#fff", fontWeight: "700" },
});
