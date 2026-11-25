import React from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { Feather } from "@expo/vector-icons";
import { theme } from "./theme";
import { WEEKDAY_KEYS, WEEKDAY_LABELS, HOUR_SLOTS, WeeklyAvailability, WeekdayKey } from "./availability";

interface Props {
  value: WeeklyAvailability;
  onChange: (next: WeeklyAvailability) => void;
  testID?: string;
}

/**
 * Static weekly grid — days as rows, hourly slots as columns.
 * Tapping a cell toggles that hour on/off for that weekday.
 */
export function AvailabilityGrid({ value, onChange, testID }: Props) {
  const isOn = (day: WeekdayKey, slot: string) =>
    (value?.[day] || []).includes(slot);

  const toggle = (day: WeekdayKey, slot: string) => {
    const current = new Set(value?.[day] || []);
    if (current.has(slot)) current.delete(slot);
    else current.add(slot);
    const next: WeeklyAvailability = { ...value, [day]: Array.from(current).sort() };
    if (next[day].length === 0) delete next[day];
    onChange(next);
  };

  const clearDay = (day: WeekdayKey) => {
    const next: WeeklyAvailability = { ...value };
    delete next[day];
    onChange(next);
  };
  const fillDay = (day: WeekdayKey) => {
    onChange({ ...value, [day]: [...HOUR_SLOTS] });
  };

  return (
    <View style={styles.wrap} testID={testID}>
      {WEEKDAY_KEYS.map((day) => {
        const count = (value?.[day] || []).length;
        return (
          <View key={day} style={styles.dayBlock}>
            <View style={styles.dayHeader}>
              <Text style={styles.dayLabel}>{WEEKDAY_LABELS[day]}</Text>
              <Text style={styles.dayCount}>
                {count === 0 ? "Off" : `${count} hr${count === 1 ? "" : "s"}`}
              </Text>
              <View style={{ flexDirection: "row", gap: 6 }}>
                <Pressable onPress={() => fillDay(day)} style={styles.mini} testID={`avail-${day}-all`} hitSlop={6}>
                  <Text style={styles.miniText}>All</Text>
                </Pressable>
                <Pressable onPress={() => clearDay(day)} style={styles.miniGhost} testID={`avail-${day}-clear`} hitSlop={6}>
                  <Text style={styles.miniGhostText}>Clear</Text>
                </Pressable>
              </View>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingHorizontal: theme.space.sm }}>
              {HOUR_SLOTS.map((slot) => {
                const on = isOn(day, slot);
                return (
                  <Pressable
                    key={slot}
                    onPress={() => toggle(day, slot)}
                    testID={`avail-${day}-${slot}`}
                    style={[styles.cell, on && styles.cellOn]}
                  >
                    <Text style={[styles.cellText, on && styles.cellTextOn]}>{slot}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        );
      })}
      <View style={styles.legend}>
        <Feather name="info" size={14} color={theme.color.muted} />
        <Text style={styles.legendText}>Tap to toggle. Booked hours are automatically hidden from parents.</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: theme.space.md },
  dayBlock: { backgroundColor: theme.color.surfaceSecondary, borderRadius: theme.radius.md, paddingVertical: theme.space.sm },
  dayHeader: {
    flexDirection: "row", alignItems: "center", gap: theme.space.sm,
    paddingHorizontal: theme.space.md, paddingBottom: theme.space.sm,
  },
  dayLabel: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface, width: 42 },
  dayCount: { flex: 1, color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  mini: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: theme.radius.pill,
    backgroundColor: theme.color.brand,
  },
  miniText: { color: "#fff", fontWeight: "700", fontSize: 12 },
  miniGhost: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.borderStrong,
  },
  miniGhostText: { color: theme.color.onSurface, fontWeight: "700", fontSize: 12 },
  cell: {
    minWidth: 60, paddingHorizontal: 10, paddingVertical: 8, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface,
  },
  cellOn: { borderColor: theme.color.brand, backgroundColor: theme.color.brand },
  cellText: { color: theme.color.onSurface, fontWeight: "600", fontSize: theme.font.sm, textAlign: "center" },
  cellTextOn: { color: "#fff" },
  legend: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: theme.space.xs,
  },
  legendText: { color: theme.color.muted, fontSize: theme.font.sm, flex: 1 },
});
