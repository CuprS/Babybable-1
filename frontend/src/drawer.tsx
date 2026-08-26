import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, Animated, Dimensions, Platform, ScrollView, Linking } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "./theme";

const { width: SCREEN_W } = Dimensions.get("window");
const DRAWER_W = Math.min(SCREEN_W * 0.82, 360);

interface DrawerCtx {
  open: () => void;
  close: () => void;
  isOpen: boolean;
}

const Ctx = createContext<DrawerCtx | undefined>(undefined);

const MENU = [
  { label: "Find a tutor", icon: "search", route: "/find-tutor" },
  { label: "Become a tutor", icon: "book-open", route: "/become-tutor" },
  { label: "Languages near you", icon: "map-pin", route: "/languages-near-you" },
  { label: "Support", icon: "life-buoy", route: "/support" },
  { label: "Mission", icon: "heart", route: "/mission" },
  { label: "Blog", icon: "edit-3", route: "/blog" },
] as const;

export function DrawerProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const translate = useRef(new Animated.Value(-DRAWER_W)).current;
  const overlay = useRef(new Animated.Value(0)).current;
  const router = useRouter();

  const open = useCallback(() => setOpen(true), []);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    Animated.parallel([
      Animated.timing(translate, { toValue: isOpen ? 0 : -DRAWER_W, duration: 220, useNativeDriver: true }),
      Animated.timing(overlay, { toValue: isOpen ? 1 : 0, duration: 220, useNativeDriver: true }),
    ]).start();
  }, [isOpen, translate, overlay]);

  const go = (route: string) => {
    close();
    setTimeout(() => router.push(route as any), 120);
  };

  return (
    <Ctx.Provider value={{ open, close, isOpen }}>
      <View style={{ flex: 1 }}>{children}</View>
      {isOpen && (
        <Animated.View style={[StyleSheet.absoluteFill, styles.overlay, { opacity: overlay }]} pointerEvents="auto">
          <Pressable style={StyleSheet.absoluteFill} onPress={close} testID="drawer-overlay" />
        </Animated.View>
      )}
      <Animated.View
        style={[styles.drawer, { transform: [{ translateX: translate }] }]}
        pointerEvents={isOpen ? "auto" : "none"}
        testID="side-drawer"
      >
        <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
          <View style={styles.header}>
            <Text style={styles.logo}>babybabel</Text>
            <Pressable onPress={close} testID="drawer-close" hitSlop={12}>
              <Feather name="x" size={22} color={theme.color.onSurface} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ paddingVertical: theme.space.md }}>
            {MENU.map((m) => (
              <Pressable
                key={m.route}
                onPress={() => go(m.route)}
                style={({ pressed }) => [styles.item, pressed && { backgroundColor: theme.color.surfaceSecondary }]}
                testID={`drawer-${m.route.replace("/", "")}`}
              >
                <Feather name={m.icon as any} size={20} color={theme.color.onSurface} />
                <Text style={styles.itemText}>{m.label}</Text>
                <Feather name="chevron-right" size={18} color={theme.color.muted} />
              </Pressable>
            ))}
          </ScrollView>
          <View style={styles.footer}>
            {Platform.OS === "web" && (
              <Pressable
                onPress={() => Linking.openURL("https://expo.dev/")}
                style={styles.download}
                testID="drawer-download-app"
              >
                <Feather name="download" size={18} color={theme.color.brand} />
                <Text style={styles.downloadText}>Download the app</Text>
              </Pressable>
            )}
            <Pressable onPress={() => go("/privacy")} testID="drawer-privacy">
              <Text style={styles.privacy}>Privacy Policy</Text>
            </Pressable>
            <Text style={styles.tag}>© Babybabel · Care in every language</Text>
          </View>
        </SafeAreaView>
      </Animated.View>
    </Ctx.Provider>
  );
}

export function useDrawer() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useDrawer outside DrawerProvider");
  return v;
}

export function MenuButton({ tint = "#fff", testID = "menu-button" }: { tint?: string; testID?: string }) {
  const { open } = useDrawer();
  return (
    <Pressable onPress={open} style={menuStyles.btn} testID={testID} hitSlop={12}>
      <Feather name="menu" size={22} color={tint} />
    </Pressable>
  );
}

const menuStyles = StyleSheet.create({
  btn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
});

const styles = StyleSheet.create({
  overlay: { backgroundColor: "rgba(44,36,33,0.5)", zIndex: 100 },
  drawer: {
    position: "absolute", top: 0, bottom: 0, left: 0, width: DRAWER_W,
    backgroundColor: theme.color.surface, zIndex: 101,
    shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 20, shadowOffset: { width: 4, height: 0 }, elevation: 12,
  },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  logo: { fontSize: 22, fontWeight: "700", color: theme.color.brand, letterSpacing: -0.5 },
  item: { flexDirection: "row", alignItems: "center", gap: theme.space.md, paddingHorizontal: theme.space.xl, paddingVertical: theme.space.lg },
  itemText: { flex: 1, fontSize: theme.font.lg, color: theme.color.onSurface, fontWeight: "500" },
  footer: { borderTopColor: theme.color.border, borderTopWidth: StyleSheet.hairlineWidth, padding: theme.space.xl, gap: theme.space.md },
  download: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, backgroundColor: theme.color.brandSoft, paddingHorizontal: theme.space.md, paddingVertical: theme.space.sm, borderRadius: theme.radius.pill, alignSelf: "flex-start" },
  downloadText: { color: theme.color.brandDark, fontWeight: "700" },
  privacy: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.base, fontWeight: "600", textDecorationLine: "underline" },
  tag: { color: theme.color.muted, fontSize: 11 },
});
