import { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { theme } from "@/src/theme";
import { useToast } from "@/src/toast";
import { apiFetch } from "@/src/api";
import { Button, Input } from "@/src/ui";

const REASONS = [
  { key: "spam", label: "Spam or unwanted messages" },
  { key: "harassment", label: "Harassment or bullying" },
  { key: "inappropriate", label: "Inappropriate content or behaviour" },
  { key: "safety", label: "I'm worried about a child's safety" },
  { key: "fake", label: "Fake profile or scam" },
  { key: "other", label: "Something else" },
] as const;
type Reason = (typeof REASONS)[number]["key"];

export default function BlockUser() {
  const { userId, name, from } = useLocalSearchParams<{ userId: string; name?: string; from?: string }>();
  const router = useRouter();
  const { show } = useToast();
  const who = name || "this person";
  const [reason, setReason] = useState<Reason | null>(null);
  const [details, setDetails] = useState("");
  const [understood, setUnderstood] = useState(false);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  const needsDetails = reason === "other" && details.trim().length < 10;
  const canSubmit = !!reason && understood && !needsDetails;
  const exit = () => router.dismissTo(from === "chat" ? "/(tabs)/messages" : "/(tabs)");

  const submit = async () => {
    if (!canSubmit) return;
    setSaving(true);
    try {
      await apiFetch("/blocks", { method: "POST", body: JSON.stringify({ user_id: userId, reason, details: details.trim() }) });
      setDone(true);
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't block", body: e?.message || "Try again" });
    } finally {
      setSaving(false);
    }
  };

  if (done) {
    return (
      <SafeAreaView style={styles.root} testID="block-done-screen">
        <View style={styles.doneWrap}>
          <View style={styles.doneIcon}><Feather name="check" size={28} color={theme.color.onBrand} /></View>
          <Text style={styles.doneTitle}>{who} is blocked</Text>
          <Text style={styles.doneSub}>
            You won&apos;t see each other&apos;s profiles or messages any more. They aren&apos;t told why. Thanks for helping keep Babybabel safe.
          </Text>
          {reason === "safety" && (
            <Pressable onPress={() => router.push("/support")} testID="block-done-support">
              <Text style={styles.link}>Contact our safety team</Text>
            </Pressable>
          )}
          <Button title="Done" onPress={exit} testID="block-done-btn" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]} testID="block-screen">
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} hitSlop={12} testID="block-back">
          <Feather name="x" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Block {who}</Text>
        <View style={{ width: 22 }} />
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.title}>Why are you blocking {who}?</Text>
          <Text style={styles.sub}>Only the Babybabel team sees your answer. {who} won&apos;t be told.</Text>

          <View style={{ gap: theme.space.sm }}>
            {REASONS.map((r) => {
              const on = reason === r.key;
              return (
                <Pressable key={r.key} onPress={() => setReason(r.key)} style={[styles.option, on && styles.optionOn]} testID={`block-reason-${r.key}`} accessibilityRole="radio" accessibilityState={{ checked: on }}>
                  <View style={[styles.radio, on && styles.radioOn]}>{on && <View style={styles.radioDot} />}</View>
                  <Text style={styles.optionText}>{r.label}</Text>
                </Pressable>
              );
            })}
          </View>

          <Input
            label={reason === "other" ? "Tell us what happened (required)" : "Anything else we should know? (optional)"}
            value={details}
            onChangeText={setDetails}
            multiline
            maxLength={1000}
            placeholder="Describe what happened"
            style={{ minHeight: 96, textAlignVertical: "top" }}
            testID="block-details"
          />
          {reason === "other" && needsDetails && <Text style={styles.hint}>At least 10 characters.</Text>}

          <View style={styles.warn}>
            <Text style={styles.warnTitle}>What happens next</Text>
            <Text style={styles.warnItem}>• You can&apos;t message each other or see each other&apos;s profiles.</Text>
            <Text style={styles.warnItem}>• Your conversation is hidden from both of your inboxes.</Text>
            <Text style={styles.warnItem}>• You can&apos;t book or invite each other to lessons.</Text>
            <Text style={[styles.warnItem, { fontWeight: "700" }]}>• Blocking is permanent and can&apos;t be undone.</Text>
          </View>

          <Pressable onPress={() => setUnderstood(!understood)} style={styles.confirmRow} testID="block-confirm-check" accessibilityRole="checkbox" accessibilityState={{ checked: understood }}>
            <View style={[styles.check, understood && styles.checkOn]}>
              {understood && <Feather name="check" size={14} color={theme.color.onBrand} />}
            </View>
            <Text style={styles.confirmText}>I understand that blocking {who} is permanent.</Text>
          </Pressable>

          <Pressable onPress={submit} disabled={!canSubmit || saving} style={[styles.blockBtn, (!canSubmit || saving) && { opacity: 0.4 }]} testID="block-submit">
            <Feather name="slash" size={16} color={theme.color.onBrand} />
            <Text style={styles.blockBtnText}>{saving ? "Blocking…" : `Block ${who}`}</Text>
          </Pressable>
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} style={styles.cancel} testID="block-cancel">
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { flex: 1, textAlign: "center", fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  content: { padding: theme.space.xl, gap: theme.space.lg, paddingBottom: theme.space["3xl"] },
  title: { fontSize: theme.font["2xl"], fontWeight: "700", color: theme.color.onSurface },
  sub: { color: theme.color.onSurfaceSecondary, marginTop: -theme.space.sm, lineHeight: 20 },
  option: { flexDirection: "row", alignItems: "center", gap: theme.space.md, minHeight: 52, paddingHorizontal: theme.space.lg, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface },
  optionOn: { borderColor: theme.color.brand, backgroundColor: theme.color.brandSoft },
  optionText: { flex: 1, color: theme.color.onSurface, fontSize: theme.font.base, fontWeight: "500" },
  radio: { width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: theme.color.borderStrong, alignItems: "center", justifyContent: "center" },
  radioOn: { borderColor: theme.color.brand },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.color.brand },
  hint: { color: theme.color.error, fontSize: theme.font.sm, marginTop: -theme.space.sm },
  warn: { padding: theme.space.lg, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary, gap: 6 },
  warnTitle: { fontWeight: "700", color: theme.color.onSurface, marginBottom: 2 },
  warnItem: { color: theme.color.onSurfaceSecondary, lineHeight: 20 },
  confirmRow: { flexDirection: "row", alignItems: "center", gap: theme.space.md, minHeight: 44 },
  check: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: theme.color.borderStrong, alignItems: "center", justifyContent: "center" },
  checkOn: { backgroundColor: theme.color.error, borderColor: theme.color.error },
  confirmText: { flex: 1, color: theme.color.onSurface, fontWeight: "500" },
  blockBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: theme.space.sm, minHeight: 52, borderRadius: theme.radius.pill, backgroundColor: theme.color.error },
  blockBtnText: { color: theme.color.onBrand, fontWeight: "700", fontSize: theme.font.lg },
  cancel: { alignItems: "center", minHeight: 44, justifyContent: "center" },
  cancelText: { color: theme.color.onSurfaceSecondary, fontWeight: "600" },
  doneWrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: theme.space.xl, gap: theme.space.md },
  doneIcon: { width: 64, height: 64, borderRadius: 32, backgroundColor: theme.color.success, alignItems: "center", justifyContent: "center" },
  doneTitle: { fontSize: theme.font["2xl"], fontWeight: "700", color: theme.color.onSurface, textAlign: "center" },
  doneSub: { color: theme.color.onSurfaceSecondary, textAlign: "center", lineHeight: 20, marginBottom: theme.space.md },
  link: { color: theme.color.brandDark, fontWeight: "700", textDecorationLine: "underline", marginBottom: theme.space.md },
});
