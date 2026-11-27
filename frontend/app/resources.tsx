import { Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { LinearGradient } from "expo-linear-gradient";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { MenuButton } from "@/src/drawer";
import { SiteFooter } from "@/src/footer";
import { RESOURCES, Resource } from "@/src/resources";
import { theme } from "@/src/theme";

/** Only ever open plain https links, so a typo in the list can't run code or open an app. */
function safeUrl(url: string): URL | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" ? u : null;
  } catch {
    return null;
  }
}

function openLink(url: string) {
  if (Platform.OS === "web" && typeof window !== "undefined") {
    // New tab, and the other site can't reach back into ours.
    window.open(url, "_blank", "noopener,noreferrer");
  } else {
    Linking.openURL(url).catch(() => {});
  }
}

const siteName = (u: URL) => u.hostname.replace(/^www\./, "");
// react-native-web adds `hovered` to Pressable's style callback.
type PressState = { pressed: boolean; hovered?: boolean };

/** The highlighted link at the top: its group heading is the big headline. */
function FeaturedCard({ r, u }: { r: Resource; u: URL }) {
  return (
    <Pressable
      onPress={() => openLink(u.href)}
      accessibilityRole="link"
      accessibilityLabel={`${r.group} ${r.title}, opens ${siteName(u)} in a new window`}
      testID={`resource-${siteName(u)}`}
      style={(s) => [styles.featuredWrap, ((s as PressState).hovered || s.pressed) && styles.lift]}
    >
      <LinearGradient colors={[theme.color.brand, theme.color.brandDark]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.featured}>
        <View style={styles.featuredIcon}>
          <Feather name={(r.icon || "star") as any} size={30} color={theme.color.brand} />
        </View>
        <View style={styles.pill}><Text style={styles.pillText}>Featured</Text></View>
        <Text style={styles.featuredHeading} accessibilityRole="header">{r.group}</Text>
        <Text style={styles.featuredText}>{r.description}</Text>
        <View style={styles.visitBtn}>
          <Text style={styles.visitText}>Visit {r.title}</Text>
          <Feather name="external-link" size={18} color={theme.color.brandDark} />
        </View>
        <Text style={styles.featuredSite}>{siteName(u)}</Text>
      </LinearGradient>
    </Pressable>
  );
}

function ResourceCard({ r, u, wide }: { r: Resource; u: URL; wide: boolean }) {
  return (
    <Pressable
      onPress={() => openLink(u.href)}
      accessibilityRole="link"
      accessibilityLabel={`${r.title}, opens ${siteName(u)} in a new window`}
      testID={`resource-${siteName(u)}`}
      style={(s) => [styles.card, wide && styles.cardWide, ((s as PressState).hovered || s.pressed) && [styles.lift, styles.cardHover]]}
    >
      <View style={styles.cardTop}>
        <Text style={styles.cardTitle}>{r.title}</Text>
        <View style={styles.arrow}><Feather name="arrow-up-right" size={18} color={theme.color.brandDark} /></View>
      </View>
      <Text style={styles.cardBody}>{r.description}</Text>
      <Text style={styles.cardSite}>{siteName(u)}</Text>
    </Pressable>
  );
}

export default function Resources() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const wide = width >= 720;

  const links = RESOURCES.map((r) => ({ r, u: safeUrl(r.url) })).filter((x): x is { r: Resource; u: URL } => !!x.u);
  const featured = links.filter((x) => x.r.featured);
  const rest = links.filter((x) => !x.r.featured);
  const groups = Array.from(new Set(rest.map((x) => x.r.group)));

  return (
    <View style={styles.root} testID="resources-screen">
      <SafeAreaView edges={["top"]} style={styles.headerBar}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} hitSlop={12} accessibilityRole="button" accessibilityLabel="Go back" testID="landing-back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle} numberOfLines={1}>Resources</Text>
        <MenuButton tint={theme.color.onSurface} />
      </SafeAreaView>

      <ScrollView contentContainerStyle={{ flexGrow: 1 }}>
        <View style={styles.banner}>
          <View style={styles.inner}>
            <View style={styles.bannerRow}>
              <View style={{ flex: 1, gap: theme.space.sm }}>
                <Text style={styles.eyebrow}>Helpful links</Text>
                <Text style={styles.title}>Resources</Text>
                <Text style={styles.intro}>
                  Hand-picked websites for families and tutors. Each link opens the other website in a new window.
                </Text>
              </View>
              {wide ? (
                <View style={styles.bannerArt} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
                  <Feather name="book-open" size={56} color={theme.color.brand} />
                </View>
              ) : null}
            </View>
          </View>
        </View>

        <View style={[styles.inner, styles.body]}>
          {featured.map(({ r, u }) => <FeaturedCard key={r.url} r={r} u={u} />)}

          {groups.map((g) => {
            const items = rest.filter((x) => x.r.group === g);
            const icon = items.find((x) => x.r.icon)?.r.icon || "link";
            return (
              <View key={g} style={{ gap: theme.space.md }}>
                <View style={styles.groupHead}>
                  <View style={styles.groupIcon}><Feather name={icon as any} size={20} color={theme.color.brandDark} /></View>
                  <Text style={styles.groupTitle} accessibilityRole="header">{g}</Text>
                </View>
                <View style={[styles.grid, wide && styles.gridWide]}>
                  {items.map(({ r, u }) => <ResourceCard key={r.url} r={r} u={u} wide={wide} />)}
                </View>
              </View>
            );
          })}

          <View style={styles.note} testID="resources-disclaimer">
            <Feather name="info" size={18} color={theme.color.onSurfaceSecondary} />
            <Text style={styles.noteText}>
              Babybabel isn&apos;t affiliated with these websites and isn&apos;t responsible for what they say or do.
              Check each site&apos;s own privacy policy before you share anything with it.
            </Text>
          </View>
        </View>
        <SiteFooter />
      </ScrollView>
    </View>
  );
}

const shadow = { shadowColor: "#2C2421", shadowOpacity: 0.08, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 2 };

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  headerBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.lg, paddingVertical: theme.space.sm, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth, backgroundColor: theme.color.surface },
  headerTitle: { flex: 1, textAlign: "center", fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface, marginHorizontal: theme.space.md },
  inner: { width: "100%", maxWidth: 880, alignSelf: "center", paddingHorizontal: theme.space.xl },

  banner: { backgroundColor: theme.color.surfaceSecondary, paddingVertical: theme.space["2xl"] },
  bannerRow: { flexDirection: "row", alignItems: "center", gap: theme.space.xl },
  bannerArt: { width: 120, height: 120, borderRadius: 60, backgroundColor: theme.color.brandSoft, alignItems: "center", justifyContent: "center" },
  eyebrow: { color: theme.color.brandDark, fontWeight: "700", letterSpacing: 1, textTransform: "uppercase", fontSize: theme.font.sm },
  title: { fontSize: 36, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5 },
  intro: { fontSize: 17, color: theme.color.onSurfaceSecondary, lineHeight: 26, maxWidth: 560 },

  body: { paddingVertical: theme.space["2xl"], gap: theme.space["2xl"] },
  lift: { transform: [{ translateY: -2 }] },

  featuredWrap: { borderRadius: theme.radius.lg, ...shadow, shadowOpacity: 0.18 },
  featured: { borderRadius: theme.radius.lg, padding: theme.space.xl, gap: theme.space.md, overflow: "hidden" },
  featuredIcon: { width: 56, height: 56, borderRadius: 28, backgroundColor: "#fff", alignItems: "center", justifyContent: "center" },
  pill: { alignSelf: "flex-start", backgroundColor: "rgba(255,255,255,0.22)", borderRadius: theme.radius.pill, paddingHorizontal: theme.space.md, paddingVertical: 4 },
  pillText: { color: "#fff", fontWeight: "700", fontSize: theme.font.sm, letterSpacing: 0.5, textTransform: "uppercase" },
  featuredHeading: { color: "#fff", fontSize: 30, fontWeight: "800", lineHeight: 36, letterSpacing: -0.5 },
  featuredText: { color: "rgba(255,255,255,0.95)", fontSize: 18, lineHeight: 27, maxWidth: 640 },
  visitBtn: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: theme.space.sm, backgroundColor: "#fff", borderRadius: theme.radius.pill, paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, marginTop: theme.space.xs },
  visitText: { color: theme.color.brandDark, fontWeight: "700", fontSize: 17 },
  featuredSite: { color: "rgba(255,255,255,0.8)", fontSize: theme.font.base },

  groupHead: { flexDirection: "row", alignItems: "center", gap: theme.space.md },
  groupIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.brandSoft, alignItems: "center", justifyContent: "center" },
  groupTitle: { flex: 1, fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  grid: { gap: theme.space.md },
  gridWide: { flexDirection: "row", flexWrap: "wrap" },

  card: { padding: theme.space.lg, borderRadius: theme.radius.lg, gap: theme.space.sm, backgroundColor: "#fff", borderWidth: 1, borderColor: theme.color.border, ...shadow },
  cardWide: { flexBasis: "48%", flexGrow: 1 },
  cardHover: { borderColor: theme.color.brand },
  cardTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: theme.space.md },
  cardTitle: { flex: 1, fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  arrow: { width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.brandSoft, alignItems: "center", justifyContent: "center" },
  cardBody: { fontSize: 17, lineHeight: 25, color: theme.color.onSurfaceSecondary },
  cardSite: { fontSize: theme.font.base, color: theme.color.muted, fontWeight: "600" },

  note: { flexDirection: "row", gap: theme.space.sm, padding: theme.space.lg, borderRadius: theme.radius.md, backgroundColor: theme.color.surfaceSecondary },
  noteText: { flex: 1, fontSize: theme.font.base, lineHeight: 21, color: theme.color.onSurfaceSecondary },
});
