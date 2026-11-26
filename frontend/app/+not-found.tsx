import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack, useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { theme } from "@/src/theme";
import { Button } from "@/src/ui";
import { BrandLink } from "@/src/brand";
import { SiteFooter } from "@/src/footer";

/** Shown for any address that doesn't match a page (instead of the developer error screen). */
export default function NotFound() {
  const router = useRouter();
  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]} testID="not-found-screen">
      <Stack.Screen options={{ title: "Page not found" }} />
      <View style={styles.header}><BrandLink /></View>
      <View style={styles.body}>
        <Feather name="compass" size={44} color={theme.color.brand} />
        <Text style={styles.title} accessibilityRole="header">We couldn&apos;t find that page</Text>
        <Text style={styles.text}>The link may be old or mistyped. Let&apos;s get you back on track.</Text>
        <Button title="Go to the home screen" onPress={() => router.replace("/")} testID="not-found-home" style={{ alignSelf: "stretch" }} />
        <Button title="Contact support" variant="ghost" onPress={() => router.push("/support")} style={{ alignSelf: "stretch" }} />
      </View>
      <SiteFooter />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md },
  body: { flex: 1, alignItems: "center", justifyContent: "center", gap: theme.space.md, paddingHorizontal: theme.space.xl, maxWidth: 480, width: "100%", alignSelf: "center" },
  title: { fontSize: 26, fontWeight: "700", color: theme.color.onSurface, textAlign: "center" },
  text: { fontSize: theme.font.lg, color: theme.color.onSurfaceSecondary, textAlign: "center", lineHeight: 24, marginBottom: theme.space.md },
});
