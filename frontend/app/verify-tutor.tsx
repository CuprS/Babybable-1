import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import { apiFetch, apiUpload, MyVerification } from "@/src/api";
import { theme } from "@/src/theme";
import { Button } from "@/src/ui";
import { useToast } from "@/src/toast";

const DOC_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/heic"];

const STATUS_COPY: Record<MyVerification["status"], { title: string; body: string; icon: any; color: string }> = {
  none: { title: "Get the Verified badge", body: "Families are far more likely to book tutors who've had an identity and background check.", icon: "shield", color: theme.color.brandDark },
  pending: { title: "We're reviewing your documents", body: "This usually takes 1–2 working days. We'll notify you as soon as it's done.", icon: "clock", color: theme.color.warning },
  verified: { title: "You're verified", body: "Families see a Verified badge on your profile and in search.", icon: "check-circle", color: theme.color.success },
  rejected: { title: "Please take another look", body: "", icon: "alert-circle", color: theme.color.error },
};

/** Tutors upload a photo ID and a background-check certificate; an admin reviews them. */
export default function VerifyTutor() {
  const router = useRouter();
  const { show } = useToast();
  const [status, setStatus] = useState<MyVerification | null>(null);
  const [idDoc, setIdDoc] = useState<{ path: string; name: string } | null>(null);
  const [checkDoc, setCheckDoc] = useState<{ path: string; name: string } | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    apiFetch<MyVerification>("/tutors/me/verification").then(setStatus).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const pick = async (which: "id" | "check") => {
    const res = await DocumentPicker.getDocumentAsync({ type: DOC_TYPES, copyToCacheDirectory: true, multiple: false });
    if (res.canceled) return;
    setBusy(which);
    try {
      const a = res.assets[0];
      const up = await apiUpload(a.uri, a.name, a.mimeType || "application/pdf");
      (which === "id" ? setIdDoc : setCheckDoc)({ path: up.path, name: a.name });
    } catch (e: any) {
      show({ kind: "error", title: "Upload failed", body: e?.message });
    } finally { setBusy(null); }
  };

  const submit = async () => {
    if (!idDoc || !checkDoc) { show({ kind: "error", title: "Add both documents first" }); return; }
    if (!consent) { show({ kind: "error", title: "Please tick the consent box" }); return; }
    setBusy("submit");
    try {
      const s = await apiFetch<MyVerification>("/tutors/me/verification", {
        method: "POST",
        body: JSON.stringify({ id_document_url: idDoc.path, background_check_url: checkDoc.path, consent }),
      });
      setStatus(s);
      setIdDoc(null); setCheckDoc(null); setConsent(false);
      show({ kind: "success", title: "Sent for review" });
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't send", body: e?.message });
    } finally { setBusy(null); }
  };

  if (!status) return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  const copy = STATUS_COPY[status.status];
  const canSubmit = status.status !== "pending";

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="verify-tutor-back" accessibilityRole="button" accessibilityLabel="Go back">
          <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.title} accessibilityRole="header">Verification</Text>
        <View style={{ width: 24 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: theme.space.xl, gap: theme.space.lg, paddingBottom: theme.space["3xl"] }}>
        <View style={[styles.statusCard, { borderColor: copy.color }]} testID={`verify-status-${status.status}`}>
          <Feather name={copy.icon} size={28} color={copy.color} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.statusTitle, { color: copy.color }]}>{copy.title}</Text>
            <Text style={styles.body}>{status.status === "rejected" ? status.note : copy.body}</Text>
          </View>
        </View>

        {canSubmit && (
          <>
            <Text style={styles.section}>1. Photo ID</Text>
            <Text style={styles.body}>Passport, driving licence or national ID card. Only the Babybabel team can see it.</Text>
            <DocButton label={idDoc ? idDoc.name : "Upload photo ID"} done={!!idDoc} loading={busy === "id"} onPress={() => pick("id")} testID="verify-id-upload" />

            <Text style={styles.section}>2. Background check</Text>
            <Text style={styles.body}>
              A recent criminal-record / child-safety check certificate (for example a US background check report, UK Enhanced DBS,
              or your country&apos;s equivalent), issued within the last 12 months.
            </Text>
            <DocButton label={checkDoc ? checkDoc.name : "Upload certificate"} done={!!checkDoc} loading={busy === "check"} onPress={() => pick("check")} testID="verify-check-upload" />

            <Pressable onPress={() => setConsent(!consent)} style={styles.consent} testID="verify-consent"
              accessibilityRole="checkbox" accessibilityState={{ checked: consent }}>
              <View style={[styles.box, consent && styles.boxOn]}>{consent && <Feather name="check" size={16} color="#fff" />}</View>
              <Text style={[styles.body, { flex: 1 }]}>
                I confirm these documents are mine and genuine, and I agree to Babybabel checking them to verify my identity.
              </Text>
            </Pressable>

            <Button title="Send for review" onPress={submit} loading={busy === "submit"} testID="verify-submit" />
          </>
        )}
        <Text style={styles.fine}>Documents are stored privately and only used for verification.</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function DocButton({ label, done, loading, onPress, testID }: { label: string; done: boolean; loading: boolean; onPress: () => void; testID: string }) {
  return (
    <Pressable onPress={onPress} style={[styles.doc, done && styles.docDone]} testID={testID} accessibilityRole="button">
      {loading ? <ActivityIndicator color={theme.color.brand} /> : <Feather name={done ? "check-circle" : "upload"} size={20} color={done ? theme.color.success : theme.color.brandDark} />}
      <Text style={styles.docText} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  title: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  statusCard: { flexDirection: "row", gap: theme.space.md, padding: theme.space.lg, borderRadius: theme.radius.lg, borderWidth: 2, backgroundColor: theme.color.surfaceSecondary },
  statusTitle: { fontSize: theme.font.lg, fontWeight: "700" },
  section: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.sm },
  body: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, lineHeight: 21 },
  doc: { flexDirection: "row", alignItems: "center", gap: theme.space.md, minHeight: 56, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: theme.color.borderStrong },
  docDone: { borderStyle: "solid", borderColor: theme.color.success },
  docText: { flex: 1, color: theme.color.onSurface, fontWeight: "600", fontSize: theme.font.base },
  consent: { flexDirection: "row", gap: theme.space.md, alignItems: "flex-start", paddingVertical: theme.space.sm },
  box: { width: 26, height: 26, borderRadius: 6, borderWidth: 2, borderColor: theme.color.borderStrong, alignItems: "center", justifyContent: "center" },
  boxOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  fine: { color: theme.color.muted, fontSize: theme.font.sm, textAlign: "center" },
});
