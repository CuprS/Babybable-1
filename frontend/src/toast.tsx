import React, { createContext, useContext, useState, useCallback, useRef } from "react";
import { View, Text, StyleSheet, Animated, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { theme } from "./theme";

type Kind = "success" | "error" | "info";
interface ToastAction { label: string; onPress: () => void }
interface ToastItem { id: string; kind: Kind; title: string; body?: string; action?: ToastAction }

const Ctx = createContext<{ show: (t: Omit<ToastItem, "id">) => void } | undefined>(undefined);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const show = useCallback((t: Omit<ToastItem, "id">) => {
    const id = String(Date.now() + Math.random());
    setItems((prev) => [...prev, { ...t, id }]);
    setTimeout(() => setItems((prev) => prev.filter((x) => x.id !== id)), t.action ? 5000 : 3200);
  }, []);
  const dismiss = (id: string) => setItems((prev) => prev.filter((x) => x.id !== id));
  return (
    <Ctx.Provider value={{ show }}>
      {children}
      <SafeAreaView pointerEvents="box-none" style={styles.host} edges={["top"]}>
        {items.map((t) => <ToastCard key={t.id} item={t} onDismiss={() => dismiss(t.id)} />)}
      </SafeAreaView>
    </Ctx.Provider>
  );
}

function ToastCard({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const y = useRef(new Animated.Value(-20)).current;
  const o = useRef(new Animated.Value(0)).current;
  React.useEffect(() => {
    Animated.parallel([
      Animated.timing(y, { toValue: 0, duration: 220, useNativeDriver: true }),
      Animated.timing(o, { toValue: 1, duration: 220, useNativeDriver: true }),
    ]).start();
  }, [y, o]);
  const iconName = item.kind === "success" ? "check-circle" : item.kind === "error" ? "alert-circle" : "info";
  const color = item.kind === "success" ? theme.color.success : item.kind === "error" ? theme.color.error : theme.color.brand;
  return (
    <Animated.View style={[styles.toast, { opacity: o, transform: [{ translateY: y }], borderLeftColor: color }]} testID={`toast-${item.kind}`}>
      <Feather name={iconName as any} size={20} color={color} />
      <View style={{ flex: 1 }}>
        <Text style={styles.title}>{item.title}</Text>
        {item.body ? <Text style={styles.body}>{item.body}</Text> : null}
      </View>
      {item.action && (
        <Pressable
          onPress={() => { item.action?.onPress(); onDismiss(); }}
          style={styles.actionBtn}
          testID="toast-action"
        >
          <Text style={styles.actionText}>{item.action.label}</Text>
        </Pressable>
      )}
    </Animated.View>
  );
}

export function useToast() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast outside ToastProvider");
  return v;
}

const styles = StyleSheet.create({
  host: { position: "absolute", top: 0, left: 0, right: 0, alignItems: "center", zIndex: 200 },
  toast: {
    marginTop: theme.space.sm, marginHorizontal: theme.space.md,
    flexDirection: "row", alignItems: "center", gap: theme.space.md,
    backgroundColor: theme.color.surface, borderRadius: theme.radius.md,
    paddingHorizontal: theme.space.lg, paddingVertical: theme.space.md,
    borderLeftWidth: 4, minWidth: 280, maxWidth: 420,
    shadowColor: "#000", shadowOpacity: 0.12, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 6,
  },
  title: { color: theme.color.onSurface, fontWeight: "700", fontSize: theme.font.base },
  body: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: 2 },
  actionBtn: {
    paddingHorizontal: theme.space.md, paddingVertical: 6,
    borderRadius: theme.radius.pill, backgroundColor: theme.color.brand,
  },
  actionText: { color: "#fff", fontWeight: "700", fontSize: theme.font.sm },
});
