import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, Animated, Dimensions, ScrollView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { theme } from "./theme";
import { useAuth } from "./auth";
import { BrandLink } from "./brand";
import { SiteFooter } from "./footer";

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
  { label: "Resources", icon: "bookmark", route: "/resources" },
] as const;

const TUTOR_MENU = [
  { label: "Write for the blog", icon: "feather", route: "/blog/compose" },
  { label: "My articles", icon: "file-text", route: "/blog/me" },
] as const;

export function DrawerProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const translate = useRef(new Animated.Value(-DRAWER_W)).current;
  const overlay = useRef(new Animated.Value(0)).current;
  const router = useRouter();
  const { user } = useAuth();
  const items = user?.role === "tutor" ? [...MENU, ...TUTOR_MENU] : MENU;

  // The menu's contents only exist while it's open (or sliding), so keyboard and screen-reader
  // users never land on links hidden off the side of the screen.
  const [shown, setShown] = useState(false);
  const closeBtn = useRef<View>(null);

  const open = useCallback(() => { setShown(true); setOpen(true); }, []);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    Animated.parallel([
      Animated.timing(translate, { toValue: isOpen ? 0 : -DRAWER_W, duration: 220, useNativeDriver: true }),
      Animated.timing(overlay, { toValue: isOpen ? 1 : 0, duration: 220, useNativeDriver: true }),
    ]).start(({ finished }) => { if (finished && !isOpen) setShown(false); });
  }, [isOpen, translate, overlay]);

  // Website: move keyboard focus into the menu when it opens, and let Escape close it.
  useEffect(() => {
    if (Platform.OS !== "web" || !isOpen) return;
    const t = setTimeout(() => (closeBtn.current as unknown as HTMLElement | null)?.focus?.(), 50);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => { clearTimeout(t); window.removeEventListener("keydown", onKey); };
  }, [isOpen]);

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
        accessibilityViewIsModal={isOpen}
        aria-label="Menu"
      >
        {shown && (
        <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
          <View style={styles.header}>
            <BrandLink tone="brand" size={28} onPress={close} testID="drawer-brand-home" />
            <Pressable ref={closeBtn} onPress={close} testID="drawer-close" hitSlop={12} accessibilityRole="button" accessibilityLabel="Close menu">
              <Feather name="x" size={24} color={theme.color.onSurface} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ paddingVertical: theme.space.md }}>
            {items.map((m) => (
              <Pressable
                key={m.route}
                onPress={() => go(m.route)}
                style={({ pressed }) => [styles.item, pressed && { backgroundColor: theme.color.surfaceSecondary }]}
                testID={`drawer-${m.route.slice(1).replace(/\//g, "-")}`}
                accessibilityRole="link"
              >
                <Feather name={m.icon as any} size={20} color={theme.color.onSurface} />
                <Text style={styles.itemText}>{m.label}</Text>
                <Feather name="chevron-right" size={18} color={theme.color.muted} />
              </Pressable>
            ))}
          </ScrollView>
          <SiteFooter onNavigate={close} />
        </SafeAreaView>
        )}
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
    <Pressable onPress={open} style={menuStyles.btn} testID={testID} hitSlop={12}
      accessibilityRole="button" accessibilityLabel="Open menu">
      <Feather name="menu" size={24} color={tint} />
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
  item: { flexDirection: "row", alignItems: "center", gap: theme.space.md, paddingHorizontal: theme.space.xl, paddingVertical: theme.space.lg },
  itemText: { flex: 1, fontSize: theme.font.lg, color: theme.color.onSurface, fontWeight: "500" },
});
