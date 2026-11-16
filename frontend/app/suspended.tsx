import { View, Text, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "@/src/theme";
import { Button } from "@/src/ui";
import { useAuth } from "@/src/auth";

export default function Suspended() {
  const router = useRouter();
  const { clearSuspended } = useAuth();
  return (
    <SafeAreaView style={styles.root} testID="suspended-screen">
      <View style={styles.wrap}>
        <View style={styles.icon}><Feather name="pause" size={28} color={theme.color.brandDark} /></View>
        <Text style={styles.title}>Your account is paused</Text>
        <Text style={styles.sub}>
          To keep families and tutors safe, accounts that several people have blocked are paused while our team takes a look.
          You can&apos;t sign in or appear in search until the review is finished.
        </Text>
        <Button title="Contact support" onPress={() => router.push("/support")} testID="suspended-support" />
        <Button title="Back to start" variant="ghost" onPress={() => { clearSuspended(); router.replace("/onboarding"); }} testID="suspended-home" />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: theme.space.xl, gap: theme.space.md },
  icon: { width: 64, height: 64, borderRadius: 32, backgroundColor: theme.color.brandSoft, alignItems: "center", justifyContent: "center" },
  title: { fontSize: theme.font["2xl"], fontWeight: "700", color: theme.color.onSurface, textAlign: "center" },
  sub: { color: theme.color.onSurfaceSecondary, textAlign: "center", lineHeight: 21, marginBottom: theme.space.md },
});
