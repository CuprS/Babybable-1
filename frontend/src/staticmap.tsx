import { Pressable, StyleSheet, Text, View } from "react-native";
import { Feather } from "@expo/vector-icons";
import { theme } from "./theme";
import { LiveMap, LiveMapMarker } from "./livemap";

// A small location map for profiles. It used to load a picture from staticmap.openstreetmap.de,
// which no longer responds; it now draws the same pins with the live OpenStreetMap map.
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

export function StaticMap({ latitude, longitude, markers, zoom = 11, height = 200, caption, testID, onPress }: Props) {
  const points: MapMarker[] = markers && markers.length
    ? markers
    : (latitude != null && longitude != null ? [{ latitude, longitude }] : []);

  if (points.length === 0) {
    return (
      <View style={[styles.card, { height }]} testID={testID}>
        <Feather name="map-pin" size={26} color={theme.color.muted} />
        <Text style={styles.emptyText}>Location not set yet</Text>
      </View>
    );
  }

  const pins: LiveMapMarker[] = points.slice(0, 25).map((m, i) => ({
    id: String(i), latitude: m.latitude, longitude: m.longitude, label: m.label || caption || "Here",
  }));

  const inner = (
    <View style={{ gap: theme.space.xs }} testID={testID}>
      <LiveMap markers={pins} height={height} zoom={zoom} title={caption ? `Map: ${caption}` : "Map"} />
      {caption ? (
        <View style={styles.caption}>
          <Feather name="map-pin" size={14} color={theme.color.brandDark} />
          <Text style={styles.captionText} numberOfLines={1}>{caption}</Text>
        </View>
      ) : null}
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
  caption: { flexDirection: "row", alignItems: "center", gap: 6 },
  captionText: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, flex: 1 },
});
