// Web map page, embedded by src/livemap.tsx. The app posts the pins in a message; taps go back
// the same way. Only messages from this same site are accepted, and labels are set as text
// (never HTML), so nothing in a tutor's name can run as code.
(function () {
  "use strict";
  const map = L.map("map", { zoomControl: true, attributionControl: true }).setView([20, 0], 2);
  // OpenStreetMap's tile policy requires visible attribution.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
  }).addTo(map);
  map.attributionControl.setPrefix(false);

  const layer = L.layerGroup().addTo(map);

  function show(markers, focusZoom) {
    layer.clearLayers();
    const bounds = [];
    (markers || []).forEach(function (m) {
      if (typeof m.latitude !== "number" || typeof m.longitude !== "number") return;
      const el = document.createElement("div");
      el.className = "pin";
      el.textContent = (m.price ? m.price + " · " : "") + (m.label || "");
      const icon = L.divIcon({ className: "", html: el, iconSize: null, iconAnchor: [40, 30] });
      L.marker([m.latitude, m.longitude], { icon: icon, title: m.label || "" })
        .on("click", function () { window.parent.postMessage({ type: "pin", id: String(m.id) }, window.location.origin); })
        .addTo(layer);
      bounds.push([m.latitude, m.longitude]);
    });
    if (bounds.length > 1) map.fitBounds(bounds, { padding: [30, 30], maxZoom: focusZoom || 5 });
    else if (bounds.length === 1) map.setView(bounds[0], focusZoom || 4);
  }

  window.addEventListener("message", function (e) {
    if (e.origin !== window.location.origin || e.source !== window.parent) return;
    const data = e.data || {};
    if (data.type === "markers") show(data.markers, data.zoom);
  });
  // Tell the app the map is ready for its pins.
  window.parent.postMessage({ type: "map-ready" }, window.location.origin);
})();
