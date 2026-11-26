import { Linking, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { Link } from "expo-router";
import { theme } from "./theme";

/** Public address of the web app (EXPO_PUBLIC_WEB_URL). Shown as "Open the web app" in the phone apps. */
export const WEB_APP_URL = (process.env.EXPO_PUBLIC_WEB_URL || "").replace(/\/$/, "");

const LINKS = [
  { label: "Privacy Policy", href: "/privacy" },
  { label: "Terms of Service", href: "/terms" },
  { label: "Support", href: "/support" },
] as const;

/**
 * The legal / help links shown at the very bottom of pages and of the side menu.
 * `onNavigate` runs before following a link (the side menu uses it to close itself).
 */
export function SiteFooter({ tone = "default", onNavigate }: { tone?: "default" | "light"; onNavigate?: () => void }) {
  const fg = tone === "light" ? "rgba(255,255,255,0.85)" : theme.color.onSurfaceSecondary;
  const showWebApp = Platform.OS !== "web" && !!WEB_APP_URL;
  return (
    <View style={[styles.wrap, tone === "light" && styles.wrapLight]} accessibilityRole="none" testID="site-footer">
      <View style={styles.links}>
        {LINKS.map((l, i) => (
          <View key={l.href} style={styles.item}>
            {i > 0 && <Text style={[styles.dot, { color: fg }]} importantForAccessibility="no">·</Text>}
            <Link href={l.href} asChild>
              <Pressable onPress={onNavigate} accessibilityRole="link" hitSlop={8} testID={`footer-${l.href.slice(1)}`}>
                <Text style={[styles.link, { color: fg }]}>{l.label}</Text>
              </Pressable>
            </Link>
          </View>
        ))}
        {showWebApp && (
          <View style={styles.item}>
            <Text style={[styles.dot, { color: fg }]} importantForAccessibility="no">·</Text>
            <Pressable onPress={() => { onNavigate?.(); Linking.openURL(WEB_APP_URL); }} accessibilityRole="link" hitSlop={8} testID="footer-web-app">
              <Text style={[styles.link, { color: fg }]}>Open the web app</Text>
            </Pressable>
          </View>
        )}
      </View>
      <Text style={[styles.copy, { color: fg }]}>© {new Date().getFullYear()} Babybabel · Care in every language</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: "center", gap: theme.space.sm,
    paddingTop: theme.space.xl, paddingBottom: theme.space.xl, paddingHorizontal: theme.space.xl,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.color.border,
  },
  wrapLight: { borderTopColor: "rgba(255,255,255,0.25)", paddingBottom: 0 },
  links: { flexDirection: "row", flexWrap: "wrap", justifyContent: "center", alignItems: "center", rowGap: theme.space.xs },
  item: { flexDirection: "row", alignItems: "center" },
  dot: { marginHorizontal: theme.space.sm, fontSize: theme.font.base },
  link: { fontSize: theme.font.base, fontWeight: "600", textDecorationLine: "underline" },
  copy: { fontSize: theme.font.sm, textAlign: "center" },
});
