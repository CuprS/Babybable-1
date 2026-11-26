import { Image, Pressable, StyleSheet, Text, View } from "react-native";
import { Link } from "expo-router";
import { theme } from "./theme";

/**
 * The Babybabel logo + wordmark. Tapping either goes to the home screen ("/"), which sends
 * signed-out visitors to the welcome page and signed-in people to their dashboard / Explore.
 * Replace assets/images/babybabel-icon.png (transparent PNG, ~512×512) to change the logo.
 */
export function BrandLink({
  tone = "brand",
  size = 28,
  onPress,
  testID = "brand-home-link",
}: {
  /** "light" = white text for dark backgrounds; "brand" = orange text for light backgrounds. */
  tone?: "light" | "brand";
  size?: number;
  /** Runs before navigating, e.g. to close the side menu. */
  onPress?: () => void;
  testID?: string;
}) {
  return (
    <Link href="/" asChild>
      <Pressable
        onPress={onPress}
        style={styles.link}
        accessibilityRole="link"
        accessibilityLabel="Babybabel home"
        hitSlop={8}
        testID={testID}
      >
        {/* Layout lives on this inner view: Link's asChild doesn't pass function styles through on web. */}
        <View style={styles.row}>
          <Image source={require("../assets/images/babybabel-icon.png")} style={{ width: size, height: size }} />
          <Text style={[styles.word, { fontSize: Math.round(size * 0.8), color: tone === "light" ? "#fff" : theme.color.brand }]}>
            Babybabel
          </Text>
        </View>
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  link: { alignSelf: "flex-start", backgroundColor: "transparent" },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  word: { fontWeight: "700", letterSpacing: -0.5 },
});
