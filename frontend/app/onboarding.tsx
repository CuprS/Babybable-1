import { View, Text, StyleSheet, ImageBackground, Pressable } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Button } from "@/src/ui";
import { theme } from "@/src/theme";
import { MenuButton } from "@/src/drawer";
import { BrandLink } from "@/src/brand";

const HERO = "https://images.unsplash.com/photo-1583468982228-19f19164aee2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200";

export default function Onboarding() {
  const router = useRouter();
  return (
    <View style={styles.root} testID="onboarding-screen">
      <ImageBackground source={{ uri: HERO }} style={StyleSheet.absoluteFill as any} resizeMode="cover" />
      <LinearGradient
        colors={["rgba(44,36,33,0.05)", "rgba(44,36,33,0.55)", "rgba(44,36,33,0.92)"]}
        style={StyleSheet.absoluteFill}
      />
      <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
        <View style={styles.header}>
          <BrandLink tone="light" size={32} />
          <MenuButton />
        </View>
        <View style={styles.bottom}>
          <Text style={styles.title}>Care, in{"\n"}every language.</Text>
          <Text style={styles.subtitle}>
            Trusted tutors who watch, play, and teach a new language — one warm session at a time.
          </Text>
          <View style={{ gap: theme.space.md, marginTop: theme.space.xl }}>
            <Button
              testID="onboarding-parent-btn"
              title="I'm looking for a tutor"
              onPress={() => router.push({ pathname: "/(auth)/signup", params: { role: "parent" } })}
            />
            <Button
              testID="onboarding-tutor-btn"
              title="I want to teach"
              variant="secondary"
              onPress={() => router.push({ pathname: "/(auth)/signup", params: { role: "tutor" } })}
            />
            <Pressable onPress={() => router.push("/(auth)/login")} style={{ alignItems: "center", paddingVertical: theme.space.md }} testID="onboarding-login-link">
              <Text style={{ color: "#fff", fontWeight: "600", fontSize: theme.font.lg }}>I already have an account</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surfaceInverse },
  safe: { flex: 1, justifyContent: "space-between", paddingHorizontal: theme.space.xl },
  header: { paddingTop: theme.space.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  bottom: { paddingBottom: theme.space.lg },
  title: { color: "#fff", fontSize: 40, fontWeight: "700", lineHeight: 44, letterSpacing: -1 },
  subtitle: { color: "rgba(255,255,255,0.9)", fontSize: theme.font.lg, marginTop: theme.space.md, lineHeight: 22 },
});
