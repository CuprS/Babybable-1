import React from "react";
import { Pressable, Text, StyleSheet, View, ViewStyle, ActivityIndicator, TextInput, TextInputProps } from "react-native";
import { theme } from "./theme";

interface BtnProps {
  title: string;
  onPress: () => void;
  variant?: "primary" | "secondary" | "ghost";
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  testID?: string;
}
export function Button({ title, onPress, variant = "primary", loading, disabled, style, testID }: BtnProps) {
  const isPrimary = variant === "primary";
  const isSecondary = variant === "secondary";
  const bg = isPrimary ? theme.color.brand : isSecondary ? theme.color.surfaceSecondary : "transparent";
  const fg = isPrimary ? theme.color.onBrand : theme.color.onSurface;
  const border = variant === "ghost" ? theme.color.borderStrong : "transparent";
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={disabled || loading}
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityState={{ disabled: !!(disabled || loading), busy: !!loading }}
      style={({ pressed }) => [
        styles.btn,
        { backgroundColor: bg, borderColor: border, borderWidth: variant === "ghost" ? 1 : 0, opacity: pressed || disabled ? 0.85 : 1 },
        style,
      ]}
    >
      {loading ? <ActivityIndicator color={fg} /> : <Text style={[styles.btnText, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    minHeight: 52,
    borderRadius: theme.radius.pill,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: theme.space.xl,
  },
  btnText: {
    fontSize: theme.font.lg,
    fontWeight: "600",
  },
});

interface InputProps extends TextInputProps {
  label?: string;
  testID?: string;
}
export function Input({ label, style, testID, ...rest }: InputProps) {
  return (
    <View style={{ gap: 6 }}>
      {label ? <Text style={inputStyles.label}>{label}</Text> : null}
      <TextInput
        testID={testID}
        accessibilityLabel={label}
        placeholderTextColor={theme.color.muted}
        style={[inputStyles.input, style]}
        {...rest}
      />
    </View>
  );
}
const inputStyles = StyleSheet.create({
  label: { fontSize: theme.font.sm, color: theme.color.onSurfaceSecondary, fontWeight: "600" },
  input: {
    borderWidth: 1,
    borderColor: theme.color.border,
    backgroundColor: theme.color.surface,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.space.lg,
    paddingVertical: theme.space.md,
    fontSize: theme.font.lg,
    color: theme.color.onSurface,
  },
});

export function Divider() {
  return <View style={{ height: 1, backgroundColor: theme.color.border, marginVertical: theme.space.md }} />;
}

export function Chip({ label, selected, onPress, testID }: { label: string; selected?: boolean; onPress: () => void; testID?: string }) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      hitSlop={6}
      style={{
        minHeight: 40,
        flexShrink: 0,
        paddingHorizontal: theme.space.lg,
        borderRadius: theme.radius.pill,
        borderWidth: 1,
        borderColor: selected ? theme.color.brand : theme.color.borderStrong,
        backgroundColor: selected ? theme.color.brand : "transparent",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Text style={{ color: selected ? theme.color.onBrand : theme.color.onSurface, fontWeight: "500", fontSize: theme.font.base }}>
        {label}
      </Text>
    </Pressable>
  );
}

/** Shown next to tutors whose identity and background check an admin approved. */
export function VerifiedBadge({ large }: { large?: boolean }) {
  return (
    <View
      accessible
      accessibilityLabel="Verified: identity and background check approved"
      style={{
        flexDirection: "row", alignItems: "center", gap: 3,
        paddingHorizontal: large ? 10 : 6, paddingVertical: large ? 4 : 2,
        borderRadius: theme.radius.pill, backgroundColor: theme.color.success,
      }}
    >
      <Text style={{ color: "#fff", fontWeight: "700", fontSize: large ? theme.font.base : theme.font.sm }}>✔ Verified</Text>
    </View>
  );
}
