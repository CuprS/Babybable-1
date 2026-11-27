import { useState } from "react";
import { View, Text, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { Button, Input } from "@/src/ui";
import { theme } from "@/src/theme";
import { useAuth } from "@/src/auth";
import type { Role } from "@/src/api";
import { track } from "@/src/analytics";
import { suggestEmail } from "@/src/utils/emailTypos";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/**
 * Step 1 of joining: who you are, your email and a password, and agreeing to the terms.
 * After this the app asks for the emailed code (verify-email), then tutors set up their
 * profile and identity check. The redirect lives in app/_layout.tsx, so signing up and logging
 * in always land on the same next step.
 */
export default function Signup() {
  const router = useRouter();
  const params = useLocalSearchParams<{ role?: string }>();
  const { signUp } = useAuth();
  const [role, setRole] = useState<Role>(params.role === "tutor" ? "tutor" : "parent");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const suggestion = suggestEmail(email);

  const problem = (): string => {
    if (name.trim().length < 2) return "Please enter your full name.";
    if (!EMAIL_RE.test(email.trim())) return "Please check your email address — it should look like name@example.com.";
    if (password.length < 8) return "Your password needs at least 8 characters.";
    if (password.length > 72) return "Your password can be at most 72 characters.";
    if (!agreed) return "Please tick the box to agree to the Terms of Service and Privacy Policy.";
    return "";
  };

  const submit = async () => {
    if (loading) return;
    const p = problem();
    if (p) { setError(p); return; }
    setLoading(true); setError("");
    try {
      await signUp(email.trim(), password, name.trim(), role);
      track("signup", { role, method: "email", source: "client" });
      // app/_layout.tsx now moves on to "Confirm your email".
    } catch (e: any) {
      setError(e?.message || "We couldn't create your account. Please try again.");
    } finally { setLoading(false); }
  };

  const RoleOption = ({ value, icon, label, hint }: { value: Role; icon: "heart" | "book-open"; label: string; hint: string }) => {
    const active = role === value;
    return (
      <Pressable
        testID={`signup-role-${value}`}
        style={[styles.roleBtn, active && styles.roleBtnActive]}
        onPress={() => setRole(value)}
        accessibilityRole="radio"
        accessibilityState={{ checked: active }}
        accessibilityLabel={`${label}: ${hint}`}
      >
        <Feather name={icon} size={20} color={active ? theme.color.onBrand : theme.color.onSurface} />
        <View style={{ flexShrink: 1 }}>
          <Text style={[styles.roleText, active && styles.roleTextActive]}>{label}</Text>
          <Text style={[styles.roleHint, active && styles.roleTextActive]}>{hint}</Text>
        </View>
      </Pressable>
    );
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable testID="signup-back" accessibilityRole="button" accessibilityLabel="Go back"
            onPress={() => (router.canGoBack() ? router.back() : router.replace("/onboarding"))} hitSlop={12}>
            <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.title} accessibilityRole="header">Create your{"\n"}Babybabel account</Text>
          <Text style={styles.subtitle}>It takes about a minute. We&apos;ll email you a code to confirm it&apos;s you.</Text>

          <Text style={styles.label}>I am…</Text>
          <View style={styles.roleRow} accessibilityRole="radiogroup">
            <RoleOption value="parent" icon="heart" label="A parent" hint="Looking for a tutor" />
            <RoleOption value="tutor" icon="book-open" label="A tutor" hint="I want to teach" />
          </View>

          <View style={{ gap: theme.space.lg, marginTop: theme.space.xl }}>
            <Input testID="signup-name-input" label="Full name" value={name} onChangeText={setName} placeholder="Jane Doe"
              autoComplete="name" textContentType="name" maxLength={80} />
            <View style={{ gap: 6 }}>
              <Input testID="signup-email-input" label="Email" autoCapitalize="none" autoCorrect={false} keyboardType="email-address"
                autoComplete="email" textContentType="emailAddress" value={email} onChangeText={setEmail} placeholder="you@example.com" />
              {suggestion ? (
                <Pressable onPress={() => setEmail(suggestion)} testID="signup-email-suggestion" accessibilityRole="button"
                  accessibilityLabel={`Did you mean ${suggestion}? Tap to use it.`} hitSlop={6}>
                  <Text style={styles.suggestion}>Did you mean <Text style={styles.suggestionStrong}>{suggestion}</Text>? Tap to fix.</Text>
                </Pressable>
              ) : null}
            </View>
            <View style={{ gap: 6 }}>
              <Input testID="signup-password-input" label="Password" secureTextEntry={!showPassword} value={password} onChangeText={setPassword}
                placeholder="At least 8 characters" autoCapitalize="none" autoCorrect={false} autoComplete="new-password"
                textContentType="newPassword" maxLength={72} />
              <Pressable onPress={() => setShowPassword((v) => !v)} testID="signup-show-password" accessibilityRole="button" hitSlop={6}
                style={styles.inlineRow}>
                <Feather name={showPassword ? "eye-off" : "eye"} size={18} color={theme.color.brandDark} />
                <Text style={styles.inlineLink}>{showPassword ? "Hide password" : "Show password"}</Text>
              </Pressable>
            </View>

            <Pressable onPress={() => setAgreed((v) => !v)} style={styles.agreeRow} testID="signup-agree"
              accessibilityRole="checkbox" accessibilityState={{ checked: agreed }}
              accessibilityLabel="I agree to the Terms of Service and Privacy Policy">
              <View style={[styles.box, agreed && styles.boxOn]}>
                {agreed ? <Feather name="check" size={18} color={theme.color.onBrand} /> : null}
              </View>
              <Text style={styles.agreeText}>I agree to the Terms of Service and Privacy Policy</Text>
            </Pressable>
            {/* Links on their own line, so tapping the sentence above only ticks the box. */}
            <View style={styles.legalRow}>
              <Text style={styles.legalLink} onPress={() => router.push("/terms")} accessibilityRole="link" testID="signup-terms-link">Read the Terms</Text>
              <Text style={styles.legalDot}>·</Text>
              <Text style={styles.legalLink} onPress={() => router.push("/privacy")} accessibilityRole="link" testID="signup-privacy-link">Read the Privacy Policy</Text>
            </View>

            {error ? <Text testID="signup-error" style={styles.error} accessibilityLiveRegion="polite">{error}</Text> : null}
            <Button testID="signup-submit-button" title="Create account" onPress={submit} loading={loading} />
            <Pressable onPress={() => router.replace("/(auth)/login")} testID="signup-goto-login" style={{ alignItems: "center" }} accessibilityRole="link">
              <Text style={styles.link}>Already have an account? <Text style={{ fontWeight: "700", color: theme.color.brand }}>Log in</Text></Text>
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
  content: { paddingHorizontal: theme.space.xl, paddingBottom: theme.space["2xl"] },
  title: { fontSize: 32, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5, lineHeight: 36 },
  subtitle: { fontSize: theme.font.lg, color: theme.color.onSurfaceSecondary, marginTop: theme.space.sm, lineHeight: 24 },
  label: { fontSize: theme.font.sm, color: theme.color.onSurfaceSecondary, fontWeight: "600", marginTop: theme.space.xl },
  roleRow: { flexDirection: "row", gap: theme.space.md, marginTop: theme.space.sm },
  roleBtn: {
    flex: 1, minHeight: 64, borderRadius: theme.radius.md, flexDirection: "row",
    alignItems: "center", gap: theme.space.sm, paddingHorizontal: theme.space.md, paddingVertical: theme.space.sm,
    borderWidth: 2, borderColor: theme.color.border, backgroundColor: theme.color.surface,
  },
  roleBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  roleText: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  roleHint: { fontSize: theme.font.sm, color: theme.color.onSurfaceSecondary },
  roleTextActive: { color: theme.color.onBrand },
  suggestion: { color: theme.color.onSurface, fontSize: theme.font.base },
  suggestionStrong: { fontWeight: "700", color: theme.color.brandDark, textDecorationLine: "underline" },
  inlineRow: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", paddingVertical: 4 },
  inlineLink: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.base },
  agreeRow: { flexDirection: "row", alignItems: "flex-start", gap: theme.space.md, paddingVertical: theme.space.xs },
  box: {
    width: 28, height: 28, borderRadius: 6, borderWidth: 2, borderColor: theme.color.brand,
    alignItems: "center", justifyContent: "center", backgroundColor: theme.color.surface,
  },
  boxOn: { backgroundColor: theme.color.brand },
  agreeText: { flex: 1, color: theme.color.onSurface, fontSize: theme.font.base, lineHeight: 24 },
  error: { color: theme.color.error, fontSize: theme.font.base, lineHeight: 22 },
  link: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, marginTop: theme.space.sm },
  legalLink: { color: theme.color.brandDark, fontWeight: "700", textDecorationLine: "underline", fontSize: theme.font.base, paddingVertical: 4 },
  legalRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: theme.space.sm, marginTop: -theme.space.sm, paddingLeft: 28 + theme.space.md },
  legalDot: { color: theme.color.muted, fontSize: theme.font.base },
});
