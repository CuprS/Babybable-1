// Web map page, embedded by src/livemap.tsx. The app posts the pins in a message; "View profile"
// taps go back the same way. Only messages from this same site are accepted, and everything is
// set as text (never HTML), so nothing in a tutor's name can run as code.
//
// The map sits inside scrolling pages, so it never traps the page: one finger or the mouse
// wheel scrolls the page; two fingers (phones) or a click (computers) move and zoom the map.
// Pins that overlap are grouped into a numbered bubble; tapping it zooms in.
(function () {
  "use strict";
  let touch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  let map = L.map("map", {
    zoomControl: true,
    attributionControl: true,
    scrollWheelZoom: false,
    dragging: !touch,
    tap: false,
    worldCopyJump: true,
    minZoom: 2,
  }).setView([25, 0], 2);
  // OpenStreetMap's tile policy requires visible attribution.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
  }).addTo(map);
  map.attributionControl.setPrefix(false);

  let layer = L.layerGroup().addTo(map);
  let pins = [];
  let focusZoom = 5;

  // ---- Hints: how to move the map without trapping the page ----
  let hint = document.getElementById("hint");
  let hintTimer = null;
  function showHint(text) {
    hint.textContent = text;
    hint.classList.add("on");
    clearTimeout(hintTimer);
    hintTimer = setTimeout(function () { hint.classList.remove("on"); }, 1400);
  }
  let container = map.getContainer();
  if (touch) {
    container.addEventListener("touchmove", function (e) {
      if (e.touches.length === 1) showHint("Use two fingers to move the map");
    }, { passive: true });
  } else {
    container.addEventListener("wheel", function () {
      if (!map.scrollWheelZoom.enabled()) showHint("Click the map, then scroll to zoom");
    }, { passive: true });
    map.on("click", function () { map.scrollWheelZoom.enable(); });
    container.addEventListener("mouseleave", function () { map.scrollWheelZoom.disable(); });
  }

  function post(msg) { window.parent.postMessage(msg, window.location.origin); }

  // ---- Pins and the little profile card ----
  function card(m) {
    let box = document.createElement("div");
    box.className = "card";
    let name = document.createElement("div");
    name.className = "card-name";
    name.textContent = m.label || "Tutor";
    box.appendChild(name);
    let meta = [m.location, m.price].filter(Boolean).join(" · ");
    if (meta) {
      let line = document.createElement("div");
      line.className = "card-meta";
      line.textContent = meta;
      box.appendChild(line);
    }
    let btn = document.createElement("button");
    btn.type = "button";
    btn.className = "card-btn";
    btn.textContent = "View profile";
    btn.addEventListener("click", function () { post({ type: "pin", id: String(m.id) }); });
    box.appendChild(btn);
    return box;
  }

  function pinIcon(m) {
    let el = document.createElement("div");
    el.className = "pin";
    el.textContent = (m.price ? m.price + " · " : "") + (m.label || "");
    return L.divIcon({ className: "pin-wrap", html: el, iconSize: null, iconAnchor: [0, 0] });
  }

  function clusterIcon(n) {
    let el = document.createElement("div");
    el.className = "cluster";
    el.textContent = String(n);
    el.setAttribute("aria-label", n + " tutors here — tap to zoom in");
    return L.divIcon({ className: "pin-wrap", html: el, iconSize: null, iconAnchor: [0, 0] });
  }

  // Greedy grouping by on-screen distance, redone at every zoom level.
  let GROUP_PX = 56;
  function draw() {
    layer.clearLayers();
    let groups = [];
    pins.forEach(function (m) {
      let pt = map.latLngToLayerPoint([m.latitude, m.longitude]);
      for (let i = 0; i < groups.length; i++) {
        if (groups[i].pt.distanceTo(pt) < GROUP_PX) { groups[i].items.push(m); return; }
      }
      groups.push({ pt: pt, items: [m] });
    });
    groups.forEach(function (g) {
      if (g.items.length === 1 || map.getZoom() >= map.getMaxZoom() - 2) {
        g.items.forEach(function (m) {
          L.marker([m.latitude, m.longitude], { icon: pinIcon(m), title: m.label || "", keyboard: true, riseOnHover: true })
            .bindPopup(card(m), { closeButton: true, autoPanPadding: [20, 20], offset: [0, -24] })
            .addTo(layer);
        });
        return;
      }
      let bounds = L.latLngBounds(g.items.map(function (m) { return [m.latitude, m.longitude]; }));
      L.marker(bounds.getCenter(), { icon: clusterIcon(g.items.length), keyboard: true })
        .on("click", function () {
          if (bounds.getNorthEast().equals(bounds.getSouthWest())) map.setView(bounds.getCenter(), map.getZoom() + 3);
          else map.fitBounds(bounds, { padding: [40, 40] });
        })
        .addTo(layer);
    });
  }
  map.on("zoomend", draw);

  function show(markers, zoom) {
    pins = (markers || []).filter(function (m) {
      return typeof m.latitude === "number" && typeof m.longitude === "number";
    });
    focusZoom = zoom || 5;
    if (pins.length > 1) {
      map.fitBounds(pins.map(function (m) { return [m.latitude, m.longitude]; }), { padding: [40, 40], maxZoom: focusZoom });
    } else if (pins.length === 1) {
      map.setView([pins[0].latitude, pins[0].longitude], zoom || 4);
    }
    draw();
  }

  window.addEventListener("message", function (e) {
    if (e.origin !== window.location.origin || e.source !== window.parent) return;
    let data = e.data || {};
    if (data.type === "markers") show(data.markers, data.zoom);
  });
  // Tell the app the map is ready for its pins.
  post({ type: "map-ready" });
})();
