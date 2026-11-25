import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, Platform } from "react-native";
import { theme } from "./theme";
import { useToast } from "./toast";
import { apiFetch, TOKEN_KEY } from "./api";
import { storage } from "./utils/storage";

interface Pending {
  id: string; user_id: string; name: string; email: string;
  verification_status: string; verification_submitted_at?: string;
  id_document_url?: string; background_check_url?: string; accreditation_document_url?: string;
}

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL as string;

/** Identity documents are private, so they're fetched with the admin's token and opened as a blob. */
async function openPrivateFile(path: string) {
  if (Platform.OS !== "web") {
    throw new Error("Open the Admin page in a web browser to review identity documents.");
  }
  const token = await storage.secureGet<string>(TOKEN_KEY, "");
  const res = await fetch(`${BASE}/api/files/${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`Couldn't open the file (${res.status})`);
  window.open(URL.createObjectURL(await res.blob()), "_blank", "noopener");
}

/** Admin: review tutors' identity + background-check documents. */
export function AdminVerificationPanel({ reloadKey }: { reloadKey: number }) {
  const { show } = useToast();
  const [rows, setRows] = useState<Pending[] | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setRows(await apiFetch<Pending[]>("/admin/verifications?status=pending")); } catch { setRows([]); }
  }, []);
  useEffect(() => { load(); }, [load, reloadKey]);

  const open = async (path?: string) => {
    if (!path) return;
    try { await openPrivateFile(path); } catch (e: any) { show({ kind: "error", title: "Couldn't open", body: e?.message }); }
  };

  const decide = async (r: Pending, approve: boolean) => {
    const note = (notes[r.id] || "").trim();
    if (!approve && !note) { show({ kind: "error", title: "Add a note", body: "Tell the tutor what to fix." }); return; }
    setBusy(r.id);
    try {
      await apiFetch(`/admin/verifications/${r.id}/${approve ? "approve" : "reject"}`, { method: "POST", body: JSON.stringify({ note }) });
      setRows((prev) => (prev || []).filter((x) => x.id !== r.id));
      show({ kind: "success", title: approve ? `${r.name} verified` : "Sent back to the tutor" });
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't save", body: e?.message });
    } finally { setBusy(null); }
  };

  return (
    <View testID="admin-verification-panel">
      <Text style={styles.section}>Tutor verification</Text>
      {rows === null ? <ActivityIndicator color={theme.color.brand} /> : rows.length === 0 ? (
        <Text style={styles.muted}>Nothing waiting for review.</Text>
      ) : rows.map((r) => (
        <View key={r.id} style={styles.card} testID={`admin-verify-${r.id}`}>
          <Text style={styles.name}>{r.name}</Text>
          <Text style={styles.muted}>{r.email}{r.verification_submitted_at ? ` · sent ${new Date(r.verification_submitted_at).toLocaleDateString()}` : ""}</Text>
          <View style={styles.links}>
            <Pressable onPress={() => open(r.id_document_url)} style={styles.link} accessibilityRole="button"><Text style={styles.linkText}>Photo ID</Text></Pressable>
            <Pressable onPress={() => open(r.background_check_url)} style={styles.link} accessibilityRole="button"><Text style={styles.linkText}>Background check</Text></Pressable>
            {r.accreditation_document_url ? (
              <Pressable onPress={() => open(r.accreditation_document_url)} style={styles.link} accessibilityRole="button"><Text style={styles.linkText}>Accreditation</Text></Pressable>
            ) : null}
          </View>
          <TextInput
            value={notes[r.id] || ""}
            onChangeText={(v) => setNotes((n) => ({ ...n, [r.id]: v }))}
            placeholder="Note to the tutor (required to send back)"
            placeholderTextColor={theme.color.muted}
            style={styles.input}
            multiline
          />
          <View style={styles.actions}>
            <Pressable onPress={() => decide(r, false)} disabled={busy === r.id} style={[styles.btn, styles.reject]} accessibilityRole="button">
              <Text style={[styles.btnText, { color: theme.color.error }]}>Send back</Text>
            </Pressable>
            <Pressable onPress={() => decide(r, true)} disabled={busy === r.id} style={[styles.btn, styles.approve]} accessibilityRole="button">
              {busy === r.id ? <ActivityIndicator color="#fff" /> : <Text style={[styles.btnText, { color: "#fff" }]}>Approve</Text>}
            </Pressable>
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  muted: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  card: { padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, marginBottom: theme.space.sm, gap: theme.space.sm },
  name: { fontWeight: "700", color: theme.color.onSurface, fontSize: theme.font.lg },
  links: { flexDirection: "row", flexWrap: "wrap", gap: theme.space.sm },
  link: { minHeight: 40, paddingHorizontal: theme.space.md, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.borderStrong, justifyContent: "center", backgroundColor: theme.color.surface },
  linkText: { color: theme.color.onSurface, fontWeight: "600" },
  input: { minHeight: 56, borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.md, padding: theme.space.md, color: theme.color.onSurface, backgroundColor: theme.color.surface, textAlignVertical: "top" },
  actions: { flexDirection: "row", gap: theme.space.sm },
  btn: { flex: 1, minHeight: 44, borderRadius: theme.radius.pill, alignItems: "center", justifyContent: "center" },
  reject: { borderWidth: 1, borderColor: theme.color.error, backgroundColor: theme.color.surface },
  approve: { backgroundColor: theme.color.success },
  btnText: { fontWeight: "700" },
});
