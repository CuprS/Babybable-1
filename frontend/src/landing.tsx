import React from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Platform, Linking } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { theme } from "./theme";
import { MenuButton } from "./drawer";
import { Button } from "./ui";

interface Props {
  title: string;
  eyebrow?: string;
  heroImage?: string;
  intro: string;
  sections?: { title: string; body: string; icon?: string }[];
  cta?: { label: string; onPress: () => void; testID?: string };
  testID?: string;
}

export function LandingPage({ title, eyebrow, heroImage, intro, sections = [], cta, testID }: Props) {
  const router = useRouter();
  return (
    <View style={{ flex: 1, backgroundColor: theme.color.surface }} testID={testID}>
      <SafeAreaView edges={["top"]} style={styles.headerBar}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="landing-back" accessibilityRole="button" accessibilityLabel="Go back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle} numberOfLines={1}>{title}</Text>
        <MenuButton tint={theme.color.onSurface} />
      </SafeAreaView>
      <ScrollView contentContainerStyle={{ paddingBottom: theme.space["3xl"] }}>
        {heroImage && (
          <View style={styles.heroWrap}>
            <Image source={{ uri: heroImage }} style={styles.hero} contentFit="cover" />
            <LinearGradient colors={["rgba(0,0,0,0)", "rgba(0,0,0,0.55)"]} style={StyleSheet.absoluteFill} />
            <View style={styles.heroOverlay}>
              {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
              <Text style={styles.heroTitle}>{title}</Text>
            </View>
          </View>
        )}
        <View style={{ padding: theme.space.xl, gap: theme.space.lg }}>
          {!heroImage && eyebrow ? <Text style={styles.eyebrowDark}>{eyebrow}</Text> : null}
          {!heroImage ? <Text style={styles.title}>{title}</Text> : null}
          <Text style={styles.intro}>{intro}</Text>
          {sections.map((s, i) => (
            <View key={i} style={styles.section}>
              <View style={styles.sectionHeader}>
                {s.icon ? <Feather name={s.icon as any} size={18} color={theme.color.brand} /> : null}
                <Text style={styles.sectionTitle}>{s.title}</Text>
              </View>
              <Text style={styles.sectionBody}>{s.body}</Text>
            </View>
          ))}
          {cta && (
            <View style={{ marginTop: theme.space.md }}>
              <Button title={cta.label} onPress={cta.onPress} testID={cta.testID} />
            </View>
          )}
        </View>
        <View style={styles.footer}>
          {Platform.OS === "web" && (
            <Pressable onPress={() => Linking.openURL("https://expo.dev/")} style={styles.download} testID="landing-download">
              <Feather name="download" size={16} color={theme.color.brand} />
              <Text style={styles.downloadText}>Download the app</Text>
            </Pressable>
          )}
          <Pressable onPress={() => router.push("/privacy")} testID="landing-privacy">
            <Text style={styles.privacy}>Privacy Policy</Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  headerBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.lg, paddingVertical: theme.space.sm, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { flex: 1, textAlign: "center", fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface, marginHorizontal: theme.space.md },
  heroWrap: { width: "100%", aspectRatio: 16 / 10, backgroundColor: theme.color.surfaceSecondary },
  hero: { width: "100%", height: "100%" },
  heroOverlay: { position: "absolute", bottom: 0, left: 0, right: 0, padding: theme.space.xl },
  eyebrow: { color: "rgba(255,255,255,0.85)", fontWeight: "700", letterSpacing: 1, textTransform: "uppercase", fontSize: 12 },
  eyebrowDark: { color: theme.color.brand, fontWeight: "700", letterSpacing: 1, textTransform: "uppercase", fontSize: 12 },
  heroTitle: { color: "#fff", fontSize: 32, fontWeight: "700", letterSpacing: -0.5, marginTop: theme.space.xs },
  title: { fontSize: 32, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5 },
  intro: { fontSize: theme.font.lg, color: theme.color.onSurfaceSecondary, lineHeight: 24 },
  section: { padding: theme.space.lg, backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.lg, gap: theme.space.xs },
  sectionHeader: { flexDirection: "row", alignItems: "center", gap: theme.space.sm },
  sectionTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  sectionBody: { color: theme.color.onSurfaceSecondary, lineHeight: 22 },
  footer: { paddingHorizontal: theme.space.xl, paddingTop: theme.space.xl, borderTopColor: theme.color.border, borderTopWidth: StyleSheet.hairlineWidth, gap: theme.space.md },
  download: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, backgroundColor: theme.color.brandSoft, paddingHorizontal: theme.space.md, paddingVertical: theme.space.sm, borderRadius: theme.radius.pill, alignSelf: "flex-start" },
  downloadText: { color: theme.color.brandDark, fontWeight: "700" },
  privacy: { color: theme.color.onSurfaceSecondary, fontWeight: "600", textDecorationLine: "underline" },
});
