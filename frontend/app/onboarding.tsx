import { useRef } from "react";
import { View, Text, StyleSheet, ImageBackground, Pressable, ScrollView, useWindowDimensions } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Button } from "@/src/ui";
import { theme } from "@/src/theme";
import { MenuButton } from "@/src/drawer";
import { BrandLink } from "@/src/brand";
import { IntroVideo } from "@/src/introVideo";
import { TutorMapSection } from "@/src/TutorMapSection";
import { SiteFooter } from "@/src/footer";

const HERO = "https://images.unsplash.com/photo-1583468982228-19f19164aee2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200";

/** The landing page for visitors who aren't signed in: the welcome screen fills the window,
 * and scrolling down shows the map of verified tutors, then the footer. */
export default function Onboarding() {
  const router = useRouter();
  const scroller = useRef<ScrollView>(null);
  const mapY = useRef(0); // where the map section starts, for the "See tutors near you" cue
  const { height } = useWindowDimensions();
  const heroHeight = Math.max(height, 560);

  return (
    <ScrollView ref={scroller} style={styles.root} testID="onboarding-screen" contentContainerStyle={{ flexGrow: 1 }}>
      <View style={[styles.hero, { minHeight: heroHeight }]}>
        <ImageBackground source={{ uri: HERO }} style={StyleSheet.absoluteFill as any} resizeMode="cover" />
        <IntroVideo />
        <LinearGradient
          colors={["rgba(44,36,33,0.05)", "rgba(44,36,33,0.55)", "rgba(44,36,33,0.92)"]}
          style={StyleSheet.absoluteFill}
        />
        <SafeAreaView style={styles.safe} edges={["top"]}>
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
            <Pressable
              onPress={() => scroller.current?.scrollTo({ y: mapY.current || heroHeight, animated: true })}
              style={styles.cue}
              testID="onboarding-see-map"
              accessibilityRole="button"
              accessibilityLabel="See tutors near you on the map"
            >
              <Text style={styles.cueText}>See tutors near you</Text>
              <Feather name="chevron-down" size={22} color="#fff" />
            </Pressable>
          </View>
        </SafeAreaView>
      </View>
      <View onLayout={(e) => { mapY.current = e.nativeEvent.layout.y; }}>
        <TutorMapSection />
      </View>
      <SiteFooter />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  hero: { backgroundColor: theme.color.surfaceInverse, overflow: "hidden" },
  safe: { flex: 1, justifyContent: "space-between", paddingHorizontal: theme.space.xl },
  header: { paddingTop: theme.space.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  bottom: { paddingBottom: theme.space.md },
  title: { color: "#fff", fontSize: 40, fontWeight: "700", lineHeight: 44, letterSpacing: -1 },
  subtitle: { color: "rgba(255,255,255,0.9)", fontSize: theme.font.lg, marginTop: theme.space.md, lineHeight: 22 },
  cue: { flexDirection: "column", alignItems: "center", paddingVertical: theme.space.sm, gap: 2 },
  cueText: { color: "#fff", fontWeight: "700", fontSize: theme.font.base },
});
