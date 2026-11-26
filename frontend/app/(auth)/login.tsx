import { useState } from "react";
import { View, Text, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { Button, Input } from "@/src/ui";
import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";

export default function Login() {
  const router = useRouter();
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  // The admin account has a second step: a 6-digit code emailed after the password is accepted.
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    setLoading(true); setError("");
    try {
      const u = await signIn(email.trim(), password, needsCode ? code.trim() : undefined);
      router.replace(u.is_admin ? "/admin" : "/(tabs)");
    } catch (e: any) {
      if (e?.status === 428) {
        setNeedsCode(true); setCode(""); setNotice(e.message);
      } else {
        if (needsCode && e?.status === 400) { setNeedsCode(false); setCode(""); setNotice(""); }
        setError(e?.message || "Login failed");
      }
    } finally { setLoading(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable testID="login-back" accessibilityRole="button" accessibilityLabel="Go back" onPress={() => router.back()} hitSlop={12}>
            <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.title}>Welcome back</Text>
          <Text style={styles.subtitle}>Log in to continue with Babybabel.</Text>
          <View style={{ gap: theme.space.lg, marginTop: theme.space.xl }}>
            <Input testID="login-email-input" label="Email" autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} placeholder="you@example.com" />
            <Input testID="login-password-input" label="Password" secureTextEntry value={password} onChangeText={setPassword} placeholder="Your password" />
            {needsCode ? (
              <>
                {notice ? <Text style={styles.notice}>{notice}</Text> : null}
                <Input testID="login-code-input" label="Sign-in code" keyboardType="number-pad" maxLength={6} autoComplete="one-time-code" value={code} onChangeText={setCode} placeholder="6-digit code" />
              </>
            ) : null}
            {error ? <Text testID="login-error" style={styles.error}>{error}</Text> : null}
            <Button testID="login-submit-button" title={needsCode ? "Finish signing in" : "Log in"} onPress={submit} loading={loading} />
            <Pressable
              onPress={() => router.push({ pathname: "/(auth)/forgot-password", params: { email: email.trim() } })}
              testID="login-forgot"
              accessibilityRole="button"
              style={{ alignItems: "center", paddingVertical: theme.space.xs }}
            >
              <Text style={{ color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.base }}>Forgot password?</Text>
            </Pressable>
            <Pressable onPress={() => router.replace("/onboarding")} testID="login-goto-signup" style={{ alignItems: "center" }}>
              <Text style={styles.link}>New here? <Text style={{ fontWeight: "700", color: theme.color.brand }}>Create an account</Text></Text>
            </Pressable>
          </View>
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
  subtitle: { fontSize: theme.font.lg, color: theme.color.onSurfaceSecondary, marginTop: theme.space.sm },
  error: { color: theme.color.error, fontSize: theme.font.base },
  notice: { color: theme.color.onSurface, fontSize: theme.font.base, lineHeight: 22 },
  link: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, marginTop: theme.space.sm },
});
