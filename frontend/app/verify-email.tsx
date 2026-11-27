import { useState } from "react";
import { View, Text, StyleSheet, Pressable, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { Button, Input } from "@/src/ui";
import { theme } from "@/src/theme";
import { apiFetch, Tutor, UserPublic } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/toast";

export default function VerifyEmail() {
  const router = useRouter();
  const { user, setUser } = useAuth();
  const { show } = useToast();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);

  /** The next step of joining: tutors who haven't filled in their profile do that next
   * (then the identity check); everyone else goes into the app. */
  const carryOn = async () => {
    if (user?.role === "tutor") {
      const t = await apiFetch<Tutor>("/tutors/me/profile").catch(() => null);
      if (t && (!t.bio?.trim() || !(t.languages || []).length)) {
        router.replace({ pathname: "/edit-tutor", params: { setup: "1" } });
        return;
      }
    }
    router.replace("/");
  };

  if (!user) return null;

  if (user.email_verified !== false) {
    return (
      <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} hitSlop={12} testID="verify-back" accessibilityRole="button" accessibilityLabel="Go back">
            <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
          </Pressable>
        </View>
        <View style={styles.content} testID="verify-already-done">
          <Feather name="check-circle" size={40} color={theme.color.success} />
          <Text style={styles.title} accessibilityRole="header">Email confirmed</Text>
          <Text style={styles.subtitle}><Text style={{ fontWeight: "700" }}>{user.email}</Text> is confirmed — nothing else to do.</Text>
          <View style={{ marginTop: theme.space.xl }}>
            <Button title="Continue" onPress={carryOn} testID="verify-done-home" />
          </View>
        </View>
      </SafeAreaView>
    );
  }

  const verify = async () => {
    if (code.length !== 6) { setError("The code has 6 digits."); return; }
    setLoading(true); setError("");
    try {
      const u = await apiFetch<UserPublic>("/auth/verify-email", { method: "POST", body: JSON.stringify({ code }) });
      setUser(u);
      show({ kind: "success", title: "Email confirmed", body: "Thanks — that's you confirmed." });
      await carryOn();
    } catch (e: any) {
      setError(e?.message || "That code didn't work.");
    } finally { setLoading(false); }
  };

  const resend = async () => {
    setResending(true);
    try {
      await apiFetch("/auth/resend-verification", { method: "POST" });
      show({ kind: "info", title: "New code sent", body: `Check ${user.email}` });
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't send", body: e?.message });
    } finally { setResending(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <View style={styles.header}>
          {router.canGoBack() ? (
            <Pressable onPress={() => router.back()} hitSlop={12} testID="verify-back" accessibilityRole="button" accessibilityLabel="Go back">
              <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
            </Pressable>
          ) : null}
        </View>
        <View style={styles.content}>
          <Text style={styles.step}>{user.role === "tutor" ? "Step 1 of 3" : "Last step"}</Text>
          <Feather name="mail" size={40} color={theme.color.brand} />
          <Text style={styles.title} accessibilityRole="header">Confirm your email</Text>
          <Text style={styles.subtitle}>We sent a 6-digit code to <Text style={{ fontWeight: "700" }}>{user.email}</Text>. It can take a minute to arrive — check your spam folder too.</Text>
          <View style={{ gap: theme.space.lg, marginTop: theme.space.xl }}>
            <Input testID="verify-code" label="6-digit code" keyboardType="number-pad" maxLength={6} autoComplete="one-time-code"
              value={code} onChangeText={(v) => setCode(v.replace(/\D/g, ""))} placeholder="123456"
              style={{ fontSize: 24, letterSpacing: 6, textAlign: "center" }} />
            {error ? <Text style={styles.error} accessibilityLiveRegion="polite">{error}</Text> : null}
            <Button testID="verify-submit" title="Confirm" onPress={verify} loading={loading} />
            <Pressable onPress={resend} disabled={resending} style={{ alignItems: "center", padding: theme.space.sm }} accessibilityRole="button">
              <Text style={styles.link}>Didn&apos;t get it? <Text style={{ fontWeight: "700", color: theme.color.brandDark }}>{resending ? "Sending…" : "Send a new code"}</Text></Text>
            </Pressable>
            <Pressable onPress={carryOn} style={{ alignItems: "center", padding: theme.space.sm }} accessibilityRole="button" testID="verify-later">
              <Text style={styles.link}>I&apos;ll do this later</Text>
              <Text style={styles.laterHint}>You&apos;ll need to confirm before booking or messaging. Find it under Profile.</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md },
  content: { paddingHorizontal: theme.space.xl },
  title: { fontSize: 28, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.md },
  subtitle: { fontSize: theme.font.lg, color: theme.color.onSurfaceSecondary, marginTop: theme.space.sm, lineHeight: 24 },
  error: { color: theme.color.error, fontSize: theme.font.base },
  step: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.sm, marginBottom: theme.space.sm },
  laterHint: { color: theme.color.muted, fontSize: theme.font.sm, textAlign: "center", marginTop: 2 },
  link: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base },
});
