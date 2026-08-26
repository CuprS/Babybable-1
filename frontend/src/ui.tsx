import React from "react";
import { Pressable, Text, StyleSheet, View, ViewStyle, TextStyle, ActivityIndicator, TextInput, TextInputProps } from "react-native";
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
    height: 52,
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
  return <View style={{ height: 1, backgroundColor: theme.color.divider ?? theme.color.border, marginVertical: theme.space.md }} />;
}

export function Chip({ label, selected, onPress, testID }: { label: string; selected?: boolean; onPress: () => void; testID?: string }) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      style={{
        height: 36,
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
