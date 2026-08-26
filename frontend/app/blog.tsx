import { View, Text, StyleSheet, ScrollView, Pressable, Platform, Linking } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/theme";
import { MenuButton } from "@/src/drawer";

const POSTS = [
  {
    id: "raising-bilingual",
    tag: "Guides",
    title: "Raising a bilingual toddler: five tiny rituals that actually work",
    excerpt: "The Sunday-morning breakfast in Spanish. The bedtime story in French. Small, warm loops.",
    image: "https://images.unsplash.com/photo-1503454537195-1dcabb73ffb9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
    read: "6 min read",
  },
  {
    id: "why-mandarin-now",
    tag: "Trends",
    title: "Why families are choosing Mandarin — but starting with songs, not sentences",
    excerpt: "The single biggest predictor of language fluency at age 8 has nothing to do with grammar.",
    image: "https://images.unsplash.com/photo-1544005313-94ddf0286df2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
    read: "4 min read",
  },
  {
    id: "meet-marie",
    tag: "Tutor spotlight",
    title: "Meet Marie: 12 years of French, 2 dogs, and 0 patience for boring flashcards",
    excerpt: "'The best lessons are the ones where the kids forget it's a lesson at all.'",
    image: "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?crop=entropy&cs=srgb&fm=jpg&q=85&w=800",
    read: "3 min read",
  },
  {
    id: "small-languages",
    tag: "Mission",
    title: "The 'small' languages deserve big tutors",
    excerpt: "Why Basque, Yoruba, and Tagalog belong on the same shelf as Spanish and French.",
    image: "https://images.unsplash.com/photo-1591123120675-6f7f1aae0e5b?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200",
    read: "5 min read",
  },
];

export default function Blog() {
  const router = useRouter();
  return (
    <View style={{ flex: 1, backgroundColor: theme.color.surface }} testID="blog-screen">
      <SafeAreaView edges={["top"]} style={styles.headerBar}>
        <Pressable onPress={() => router.back()} hitSlop={12}><Feather name="arrow-left" size={22} color={theme.color.onSurface} /></Pressable>
        <Text style={styles.headerTitle}>Blog</Text>
        <MenuButton tint={theme.color.onSurface} />
      </SafeAreaView>
      <ScrollView contentContainerStyle={{ padding: theme.space.xl, paddingBottom: theme.space["3xl"] }}>
        <Text style={styles.eyebrow}>Stories · guides · tutor voices</Text>
        <Text style={styles.title}>The Babybabel Journal</Text>
        <View style={{ gap: theme.space.xl, marginTop: theme.space.xl }}>
          {POSTS.map((p) => (
            <Pressable key={p.id} style={styles.card} testID={`blog-post-${p.id}`}>
              <Image source={{ uri: p.image }} style={styles.img} contentFit="cover" />
              <View style={{ padding: theme.space.md }}>
                <Text style={styles.tag}>{p.tag}</Text>
                <Text style={styles.cardTitle}>{p.title}</Text>
                <Text style={styles.excerpt}>{p.excerpt}</Text>
                <Text style={styles.read}>{p.read}</Text>
              </View>
            </Pressable>
          ))}
        </View>
        <View style={styles.footer}>
          {Platform.OS === "web" && (
            <Pressable onPress={() => Linking.openURL("https://expo.dev/")} style={styles.download} testID="blog-download">
              <Feather name="download" size={16} color={theme.color.brand} />
              <Text style={styles.downloadText}>Download the app</Text>
            </Pressable>
          )}
          <Pressable onPress={() => router.push("/privacy")}><Text style={styles.privacy}>Privacy Policy</Text></Pressable>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  headerBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.lg, paddingVertical: theme.space.sm, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { flex: 1, textAlign: "center", fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  eyebrow: { color: theme.color.brand, fontWeight: "700", letterSpacing: 1, textTransform: "uppercase", fontSize: 11 },
  title: { fontSize: 32, fontWeight: "700", color: theme.color.onSurface, letterSpacing: -0.5, marginTop: theme.space.xs },
  card: { borderRadius: theme.radius.lg, overflow: "hidden", backgroundColor: theme.color.surfaceSecondary },
  img: { width: "100%", aspectRatio: 16 / 9 },
  tag: { color: theme.color.brand, fontWeight: "700", fontSize: 11, letterSpacing: 1, textTransform: "uppercase" },
  cardTitle: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.xs, lineHeight: 26 },
  excerpt: { color: theme.color.onSurfaceSecondary, marginTop: theme.space.sm, lineHeight: 20 },
  read: { color: theme.color.muted, marginTop: theme.space.md, fontSize: 12 },
  footer: { paddingTop: theme.space.xl, marginTop: theme.space.xl, borderTopColor: theme.color.border, borderTopWidth: StyleSheet.hairlineWidth, gap: theme.space.md },
  download: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, backgroundColor: theme.color.brandSoft, paddingHorizontal: theme.space.md, paddingVertical: theme.space.sm, borderRadius: theme.radius.pill, alignSelf: "flex-start" },
  downloadText: { color: theme.color.brandDark, fontWeight: "700" },
  privacy: { color: theme.color.onSurfaceSecondary, fontWeight: "600", textDecorationLine: "underline" },
});
