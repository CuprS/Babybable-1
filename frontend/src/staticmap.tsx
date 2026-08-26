import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Image } from "expo-image";
import { Feather } from "@expo/vector-icons";
import { theme } from "./theme";

export interface MapMarker { latitude: number; longitude: number; label?: string; color?: "red" | "orange" | "blue" | "green" }

interface Props {
  latitude?: number | null;
  longitude?: number | null;
  markers?: MapMarker[];
  zoom?: number;
  height?: number;
  width?: number;
  caption?: string;
  testID?: string;
  onPress?: () => void;
}

/**
 * Static map card powered by OpenStreetMap staticmap.
 * Works everywhere (web preview, Expo Go, native builds) without needing an API key.
 * Falls back to a friendly "no location" card when coords are missing.
 */
export function StaticMap({ latitude, longitude, markers, zoom = 11, height = 200, width = 600, caption, testID, onPress }: Props) {
  const allMarkers = markers && markers.length
    ? markers
    : (latitude != null && longitude != null ? [{ latitude, longitude, color: "red" as const }] : []);

  if (allMarkers.length === 0) {
    return (
      <View style={[styles.card, { height }]} testID={testID}>
        <Feather name="map-pin" size={26} color={theme.color.muted} />
        <Text style={styles.emptyText}>Location not set yet</Text>
      </View>
    );
  }

  const center = latitude != null && longitude != null
    ? { latitude, longitude }
    : { latitude: allMarkers.reduce((s, m) => s + m.latitude, 0) / allMarkers.length,
        longitude: allMarkers.reduce((s, m) => s + m.longitude, 0) / allMarkers.length };

  const markerStr = allMarkers
    .slice(0, 25)
    .map((m) => `${m.latitude},${m.longitude},${m.color || "red"}-pushpin`)
    .join("|");
  const url = `https://staticmap.openstreetmap.de/staticmap.php?center=${center.latitude},${center.longitude}&zoom=${zoom}&size=${width}x${Math.round(height * 2)}&maptype=mapnik&markers=${markerStr}`;

  const inner = (
    <View style={[styles.mapWrap, { height }]} testID={testID}>
      <Image source={{ uri: url }} style={StyleSheet.absoluteFill as any} contentFit="cover" transition={250} />
      {caption && (
        <View style={styles.caption}>
          <Feather name="map-pin" size={14} color="#fff" />
          <Text style={styles.captionText} numberOfLines={1}>{caption}</Text>
        </View>
      )}
    </View>
  );
  return onPress ? <Pressable onPress={onPress}>{inner}</Pressable> : inner;
}

const styles = StyleSheet.create({
  card: {
    borderRadius: theme.radius.lg, backgroundColor: theme.color.surfaceSecondary,
    alignItems: "center", justifyContent: "center", gap: 6,
  },
  emptyText: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  mapWrap: {
    borderRadius: theme.radius.lg, overflow: "hidden",
    backgroundColor: theme.color.surfaceSecondary,
  },
  caption: {
    position: "absolute", left: 12, bottom: 12,
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(44,36,33,0.8)",
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill,
  },
  captionText: { color: "#fff", fontWeight: "600", fontSize: 12, maxWidth: 240 },
});
