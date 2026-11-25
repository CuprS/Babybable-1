import { useState } from "react";
import { View, Text, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { Button, Input } from "@/src/ui";
import { theme } from "@/src/theme";
import { apiFetch, UserPublic } from "@/src/api";
import { useAuth } from "@/src/auth";

/** Two steps: email → 6-digit code + new password. Works on phones and web without email links. */
export default function ForgotPassword() {
  const router = useRouter();
  const params = useLocalSearchParams<{ email?: string }>();
  const { signInWithToken } = useAuth();
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState(params.email || "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  const sendCode = async () => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) { setError("Enter the email you signed up with."); return; }
    setLoading(true); setError("");
    try {
      const r = await apiFetch<{ message: string }>("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email: email.trim() }) });
      setInfo(r.message);
      setStep("code");
    } catch (e: any) {
      setError(e?.message || "Something went wrong. Try again.");
    } finally { setLoading(false); }
  };

  const reset = async () => {
    if (code.trim().length !== 6) { setError("The code has 6 digits."); return; }
    if (password.length < 8) { setError("Use at least 8 characters for your new password."); return; }
    setLoading(true); setError("");
    try {
      const r = await apiFetch<{ access_token: string; user: UserPublic }>("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), code: code.trim(), new_password: password }),
      });
      await signInWithToken(r.access_token, r.user);
      router.replace("/(tabs)");
    } catch (e: any) {
      setError(e?.message || "That didn't work. Try again.");
    } finally { setLoading(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable testID="forgot-back" onPress={() => router.back()} hitSlop={12} accessibilityRole="button" accessibilityLabel="Go back">
            <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.title} accessibilityRole="header">Reset your password</Text>
          {step === "email" ? (
            <>
              <Text style={styles.subtitle}>Enter your email and we&apos;ll send you a 6-digit code.</Text>
              <View style={styles.form}>
                <Input testID="forgot-email" label="Email" autoCapitalize="none" keyboardType="email-address" autoComplete="email"
                  value={email} onChangeText={setEmail} placeholder="you@example.com" />
                {error ? <Text style={styles.error} accessibilityLiveRegion="polite">{error}</Text> : null}
                <Button testID="forgot-send" title="Send code" onPress={sendCode} loading={loading} />
              </View>
            </>
          ) : (
            <>
              <Text style={styles.subtitle}>{info} Check your inbox (and spam folder) for an email from Babybabel.</Text>
              <View style={styles.form}>
                <Input testID="forgot-code" label="6-digit code" keyboardType="number-pad" maxLength={6} autoComplete="one-time-code"
                  value={code} onChangeText={(v) => setCode(v.replace(/\D/g, ""))} placeholder="123456" style={styles.code} />
                <Input testID="forgot-password" label="New password" secureTextEntry autoComplete="new-password"
                  value={password} onChangeText={setPassword} placeholder="At least 8 characters" />
                {error ? <Text style={styles.error} accessibilityLiveRegion="polite">{error}</Text> : null}
                <Button testID="forgot-reset" title="Save new password" onPress={reset} loading={loading} />
                <Pressable onPress={sendCode} disabled={loading} style={styles.linkWrap} accessibilityRole="button">
                  <Text style={styles.link}>Didn&apos;t get it? <Text style={styles.linkStrong}>Send a new code</Text></Text>
                </Pressable>
              </View>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md },
  content: { paddingHorizontal: theme.space.xl, paddingBottom: theme.space.xl },
  title: { fontSize: 32, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5 },
  subtitle: { fontSize: theme.font.lg, color: theme.color.onSurfaceSecondary, marginTop: theme.space.sm, lineHeight: 24 },
  form: { gap: theme.space.lg, marginTop: theme.space.xl },
  code: { fontSize: 24, letterSpacing: 6, textAlign: "center" },
  error: { color: theme.color.error, fontSize: theme.font.base },
  linkWrap: { alignItems: "center", paddingVertical: theme.space.sm },
  link: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base },
  linkStrong: { fontWeight: "700", color: theme.color.brandDark },
});
