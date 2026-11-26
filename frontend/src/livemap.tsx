import React, { useEffect, useMemo, useRef } from "react";
import { View, StyleSheet, Platform } from "react-native";
import { WebView } from "react-native-webview";
import { theme } from "./theme";

export interface LiveMapMarker {
  id: string;
  latitude: number;
  longitude: number;
  label: string;
  price?: string;
}

interface Props {
  markers: LiveMapMarker[];
  height?: number;
  onPinPress?: (id: string) => void;
  testID?: string;
  /** Closest zoom used to frame the pins (e.g. 11 for one city). Defaults to a wide view. */
  zoom?: number;
  title?: string;
}

/**
 * Fully interactive (scroll/zoom) map using Leaflet + OpenStreetMap tiles.
 * On native (iOS/Android) → renders via react-native-webview.
 * On web → renders the same HTML in a plain <iframe> so it works in the Metro preview too.
 * Works everywhere without an API key. Emits marker taps back to RN via postMessage.
 */
export function LiveMap({ markers, height = 220, onPinPress, testID, zoom, title = "Map" }: Props) {
  // Phone apps render the map from an HTML string in a WebView. The website instead embeds
  // /map.html from our own site (no inline scripts, so a strict Content-Security-Policy applies).
  const html = useMemo(() => (Platform.OS === "web" ? "" : buildHtml(markers, zoom)), [markers, zoom]);
  const frame = useRef<HTMLIFrameElement | null>(null);

  const sendMarkers = React.useCallback(() => {
    const win = frame.current?.contentWindow;
    if (win) win.postMessage({ type: "markers", markers, zoom }, window.location.origin);
  }, [markers, zoom]);

  useEffect(() => {
    if (Platform.OS !== "web" || typeof window === "undefined") return;
    const handler = (e: MessageEvent) => {
      // Only our own map frame may talk to us.
      if (e.origin !== window.location.origin || e.source !== frame.current?.contentWindow) return;
      const data = e.data || {};
      if (data.type === "map-ready") sendMarkers();
      else if (data.type === "pin" && data.id) onPinPress?.(String(data.id));
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [onPinPress, sendMarkers]);

  // New pins after the map has loaded.
  useEffect(() => { if (Platform.OS === "web") sendMarkers(); }, [sendMarkers]);

  if (Platform.OS === "web") {
    return (
      <View style={[styles.wrap, { height }]} testID={testID}>
        {/* @ts-ignore — iframe is a valid web element in react-native-web */}
        <iframe
          ref={frame}
          src="/map.html"
          style={{ width: "100%", height: "100%", border: "0" }}
          title={title}
          loading="lazy"
        />
      </View>
    );
  }

  return (
    <View style={[styles.wrap, { height }]} testID={testID}>
      <WebView
        source={{ html }}
        style={styles.web}
        originWhitelist={["*"]}
        javaScriptEnabled
        domStorageEnabled
        scrollEnabled={false}
        showsHorizontalScrollIndicator={false}
        showsVerticalScrollIndicator={false}
        androidLayerType="hardware"
        onMessage={(e) => {
          try {
            const data = JSON.parse(e.nativeEvent.data);
            if (data?.type === "pin" && data?.id) onPinPress?.(String(data.id));
          } catch {}
        }}
      />
    </View>
  );
}

function buildHtml(markers: LiveMapMarker[], focusZoom?: number): string {
  const safe = markers
    .filter((m) => Number.isFinite(m.latitude) && Number.isFinite(m.longitude))
    .map((m) => ({
      id: String(m.id).replace(/["'\\<>]/g, ""),
      lat: m.latitude,
      lng: m.longitude,
      label: String(m.label || "").replace(/["'\\<>]/g, ""),
      price: m.price ? String(m.price).replace(/["'\\<>]/g, "") : "",
    }));
  const initial = safe.length
    ? { lat: safe[0].lat, lng: safe[0].lng }
    : { lat: 20, lng: 0 };
  const zoom = safe.length > 1 ? 2 : 4;
  const brand = theme.color.brand;
  return `<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  html, body, #map { margin: 0; padding: 0; height: 100%; width: 100%; }
  body { background: ${theme.color.surfaceSecondary}; }
  .pin {
    background: ${brand};
    color: #fff;
    border-radius: 999px;
    padding: 6px 10px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 12px;
    font-weight: 700;
    box-shadow: 0 2px 6px rgba(0,0,0,0.25);
    white-space: nowrap;
    border: 2px solid #fff;
    cursor: pointer;
  }
  .pin::after {
    content: "";
    position: absolute;
    bottom: -6px;
    left: 50%;
    margin-left: -5px;
    border-width: 6px 5px 0 5px;
    border-style: solid;
    border-color: ${brand} transparent transparent transparent;
  }
</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  function postPin(id) {
    var payload = JSON.stringify({ type: 'pin', id: id });
    if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
      window.ReactNativeWebView.postMessage(payload);
    } else if (window.parent) {
      window.parent.postMessage(payload, '*');
    }
  }
  // OpenStreetMap's tile policy requires visible attribution.
  var map = L.map('map', { zoomControl: true, attributionControl: true })
    .setView([${initial.lat}, ${initial.lng}], ${zoom});
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
  }).addTo(map);
  map.attributionControl.setPrefix(false);
  var pins = ${JSON.stringify(safe)};
  var bounds = [];
  pins.forEach(function(p){
    var icon = L.divIcon({
      className: '',
      html: '<div class="pin">' + (p.price ? p.price + ' · ' : '') + p.label + '</div>',
      iconSize: null,
      iconAnchor: [40, 30]
    });
    var m = L.marker([p.lat, p.lng], { icon: icon }).addTo(map);
    m.on('click', function(){ postPin(p.id); });
    bounds.push([p.lat, p.lng]);
  });
  if (bounds.length > 1) {
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: ${focusZoom ?? 5} });
  } else if (bounds.length === 1) {
    map.setView(bounds[0], ${focusZoom ?? 4});
  }
</script>
</body></html>`;
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: theme.radius.lg,
    overflow: "hidden",
    backgroundColor: theme.color.surfaceSecondary,
  },
  web: { flex: 1, backgroundColor: theme.color.surfaceSecondary },
});
