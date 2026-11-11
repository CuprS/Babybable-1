import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { theme } from "./theme";
import { apiFetch } from "./api";

interface Person { id: string; name: string; email: string; role: string }
interface BlockRow {
  id: string; reason: string; details: string; created_at: string; times_blocked: number;
  blocker?: Person | null; blocked?: Person | null;
}

const REASON_LABEL: Record<string, string> = {
  spam: "Spam", harassment: "Harassment", inappropriate: "Inappropriate", safety: "Child safety", fake: "Fake / scam", other: "Other",
};

/** Admin dashboard section: who blocked whom and why. */
export function AdminBlocksPanel({ reloadKey }: { reloadKey: number }) {
  const [rows, setRows] = useState<BlockRow[] | null>(null);
  useEffect(() => {
    apiFetch<BlockRow[]>("/admin/blocks").then(setRows).catch(() => setRows([]));
  }, [reloadKey]);

  return (
    <View testID="admin-blocks-panel">
      <Text style={styles.section}>Blocks & reports</Text>
      {rows === null ? <ActivityIndicator color={theme.color.brand} /> : rows.length === 0 ? (
        <Text style={styles.muted}>No one has been blocked yet.</Text>
      ) : rows.map((r) => (
        <View key={r.id} style={styles.card} testID={`admin-block-${r.id}`}>
          <View style={styles.row}>
            <View style={[styles.pill, r.reason === "safety" && styles.pillUrgent]}>
              <Text style={[styles.pillText, r.reason === "safety" && styles.pillTextUrgent]}>{REASON_LABEL[r.reason] || r.reason}</Text>
            </View>
            <Text style={styles.date}>{new Date(r.created_at).toLocaleDateString()}</Text>
          </View>
          <Text style={styles.line}>
            <Text style={styles.bold}>{r.blocker?.name || "Deleted user"}</Text> ({r.blocker?.role}) blocked{" "}
            <Text style={styles.bold}>{r.blocked?.name || "Deleted user"}</Text> ({r.blocked?.role})
          </Text>
          {r.blocked?.email ? <Text style={styles.muted}>{r.blocked.email}{r.times_blocked > 1 ? ` · blocked ${r.times_blocked} times` : ""}</Text> : null}
          {r.details ? <Text style={styles.details}>&ldquo;{r.details}&rdquo;</Text> : null}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space["2xl"], marginBottom: theme.space.md },
  muted: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  card: { padding: theme.space.md, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, marginBottom: theme.space.sm, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pill: { paddingHorizontal: theme.space.sm, paddingVertical: 2, borderRadius: theme.radius.pill, backgroundColor: theme.color.brandSoft },
  pillUrgent: { backgroundColor: theme.color.error },
  pillText: { color: theme.color.brandDark, fontWeight: "700", fontSize: 12 },
  pillTextUrgent: { color: theme.color.onBrand },
  date: { color: theme.color.muted, fontSize: 12 },
  line: { color: theme.color.onSurface, lineHeight: 20 },
  bold: { fontWeight: "700" },
  details: { color: theme.color.onSurfaceSecondary, fontStyle: "italic", lineHeight: 20 },
});
