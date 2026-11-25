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

export default function Signup() {
  const router = useRouter();
  const params = useLocalSearchParams<{ role?: string }>();
  const initialRole: Role = params.role === "tutor" ? "tutor" : "parent";
  const { signUp } = useAuth();
  const [role, setRole] = useState<Role>(initialRole);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    setLoading(true); setError("");
    try {
      if (password.length < 8) throw new Error("Password must be at least 8 characters");
      if (name.trim().length < 2) throw new Error("Please enter your name");
      await signUp(email.trim(), password, name.trim(), role);
      track("signup", { role, method: "email", source: "client" });
      router.replace(role === "tutor" ? "/edit-tutor" : "/(tabs)");
    } catch (e: any) {
      setError(e?.message || "Signup failed");
    } finally { setLoading(false); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable testID="signup-back" accessibilityRole="button" accessibilityLabel="Go back" onPress={() => router.back()} hitSlop={12}>
            <Feather name="arrow-left" size={24} color={theme.color.onSurface} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.title}>Create your{"\n"}Babybabel account</Text>
          <Text style={styles.subtitle}>
            {role === "parent"
              ? "Find a warm tutor to care and teach a language."
              : "Share your gift with families around the world."}
          </Text>

          <View style={styles.roleRow}>
            <Pressable
              testID="signup-role-parent"
              style={[styles.roleBtn, role === "parent" && styles.roleBtnActive]}
              onPress={() => setRole("parent")}
            >
              <Feather name="heart" size={18} color={role === "parent" ? theme.color.onBrand : theme.color.onSurface} />
              <Text style={[styles.roleText, role === "parent" && styles.roleTextActive]}>Parent</Text>
            </Pressable>
            <Pressable
              testID="signup-role-tutor"
              style={[styles.roleBtn, role === "tutor" && styles.roleBtnActive]}
              onPress={() => setRole("tutor")}
            >
              <Feather name="book-open" size={18} color={role === "tutor" ? theme.color.onBrand : theme.color.onSurface} />
              <Text style={[styles.roleText, role === "tutor" && styles.roleTextActive]}>Tutor</Text>
            </Pressable>
          </View>

          <View style={{ gap: theme.space.lg, marginTop: theme.space.xl }}>
            <Input testID="signup-name-input" label="Full name" value={name} onChangeText={setName} placeholder="Jane Doe" />
            <Input testID="signup-email-input" label="Email" autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} placeholder="you@example.com" />
            <Input testID="signup-password-input" label="Password" secureTextEntry value={password} onChangeText={setPassword} placeholder="At least 6 characters" />
            {error ? <Text testID="signup-error" style={styles.error}>{error}</Text> : null}
            <Button testID="signup-submit-button" title="Create account" onPress={submit} loading={loading} />
            <Pressable onPress={() => router.replace("/(auth)/login")} testID="signup-goto-login" style={{ alignItems: "center" }}>
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
  subtitle: { fontSize: theme.font.lg, color: theme.color.onSurfaceSecondary, marginTop: theme.space.sm },
  roleRow: { flexDirection: "row", gap: theme.space.md, marginTop: theme.space.xl },
  roleBtn: {
    flex: 1, height: 56, borderRadius: theme.radius.md, flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: theme.space.sm,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface,
  },
  roleBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  roleText: { fontSize: theme.font.lg, fontWeight: "600", color: theme.color.onSurface },
  roleTextActive: { color: theme.color.onBrand },
  error: { color: theme.color.error, fontSize: theme.font.base },
  link: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, marginTop: theme.space.sm },
});
