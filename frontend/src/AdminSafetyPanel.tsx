import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator } from "react-native";
import { theme } from "./theme";
import { useToast } from "./toast";
import { apiFetch } from "./api";

interface Paused { id: string; name: string; email: string; role: string; suspended_at?: string; suspended_reason?: string; blocked_by: number }

/** Admin: where child-safety alerts go, and accounts auto-paused after repeated blocks. */
export function AdminSafetyPanel({ reloadKey }: { reloadKey: number }) {
  const { show } = useToast();
  const [email, setEmail] = useState("");
  const [savedEmail, setSavedEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [paused, setPaused] = useState<Paused[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [e, p] = await Promise.all([
        apiFetch<{ email: string }>("/admin/settings/safety-email"),
        apiFetch<Paused[]>("/admin/suspended"),
      ]);
      setEmail(e.email); setSavedEmail(e.email); setPaused(p);
    } catch {
      setPaused([]);
    }
  }, []);
  useEffect(() => { load(); }, [load, reloadKey]);

  const saveEmail = async () => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      show({ kind: "error", title: "Couldn't save", body: "Enter a valid email address" });
      return;
    }
    setSaving(true);
    try {
      const r = await apiFetch<{ email: string }>("/admin/settings/safety-email", { method: "PUT", body: JSON.stringify({ email: email.trim() }) });
      setEmail(r.email); setSavedEmail(r.email);
      show({ kind: "success", title: "Alert email updated" });
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't save", body: e?.message || "Try again" });
    } finally {
      setSaving(false);
    }
  };

  const reinstate = async (p: Paused) => {
    setBusyId(p.id);
    try {
      await apiFetch(`/admin/users/${p.id}/reinstate`, { method: "POST" });
      setPaused((prev) => (prev || []).filter((x) => x.id !== p.id));
      show({ kind: "success", title: `${p.name} reinstated` });
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't reinstate", body: e?.message });
    } finally {
      setBusyId(null);
    }
  };

  const dirty = email.trim().toLowerCase() !== savedEmail;

  return (
    <View testID="admin-safety-panel">
      <Text style={styles.section}>Safety</Text>
      <Text style={styles.label}>Child-safety alerts are emailed to</Text>
      <View style={styles.emailRow}>
        <TextInput
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          placeholder="you@example.com"
          placeholderTextColor={theme.color.muted}
          style={styles.input}
          testID="admin-safety-email-input"
        />
        <Pressable onPress={saveEmail} disabled={!dirty || saving} style={[styles.save, (!dirty || saving) && { opacity: 0.4 }]} testID="admin-safety-email-save">
          {saving ? <ActivityIndicator color={theme.color.onBrand} /> : <Text style={styles.saveText}>Save</Text>}
        </Pressable>
      </View>
      <Text style={styles.hint}>You&apos;ll also get an email whenever an account is paused automatically.</Text>

      <Text style={[styles.label, { marginTop: theme.space.lg }]}>Paused accounts (blocked by 3+ people)</Text>
      {paused === null ? <ActivityIndicator color={theme.color.brand} /> : paused.length === 0 ? (
        <Text style={styles.muted}>No paused accounts.</Text>
      ) : paused.map((p) => (
        <View key={p.id} style={styles.card} testID={`admin-paused-${p.id}`}>
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{p.name} <Text style={styles.muted}>({p.role})</Text></Text>
            <Text style={styles.muted}>{p.email}</Text>
            <Text style={styles.muted}>{p.suspended_reason || `Blocked by ${p.blocked_by} people`}{p.suspended_at ? ` · ${new Date(p.suspended_at).toLocaleDateString()}` : ""}</Text>
          </View>
          <Pressable onPress={() => reinstate(p)} disabled={busyId === p.id} style={styles.reinstate} testID={`admin-reinstate-${p.id}`}>
            {busyId === p.id ? <ActivityIndicator color={theme.color.onSurface} /> : <Text style={styles.reinstateText}>Reinstate</Text>}
          </Pressable>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  label: { fontSize: theme.font.sm, color: theme.color.onSurfaceSecondary, fontWeight: "600", marginBottom: theme.space.sm },
  emailRow: { flexDirection: "row", gap: theme.space.sm },
  input: { flex: 1, minHeight: 44, borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.md, paddingHorizontal: theme.space.md, color: theme.color.onSurface, backgroundColor: theme.color.surface },
  save: { minHeight: 44, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.pill, backgroundColor: theme.color.brand, alignItems: "center", justifyContent: "center" },
  saveText: { color: theme.color.onBrand, fontWeight: "700" },
  hint: { color: theme.color.muted, fontSize: 13, marginTop: theme.space.xs },
  muted: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  card: { flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, marginBottom: theme.space.sm },
  name: { fontWeight: "700", color: theme.color.onSurface },
  reinstate: { minHeight: 44, paddingHorizontal: theme.space.md, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.borderStrong, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  reinstateText: { fontWeight: "700", color: theme.color.onSurface },
});
