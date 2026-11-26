// Copies Leaflet's browser files into public/vendor/leaflet so the web map is served from our
// own site (allowed by the strict Content-Security-Policy) instead of a third-party CDN.
// Runs automatically after `yarn install` (see "postinstall" in package.json).
const fs = require("fs");
const path = require("path");

const src = path.join(__dirname, "..", "node_modules", "leaflet", "dist");
const dest = path.join(__dirname, "..", "public", "vendor", "leaflet");

if (!fs.existsSync(src)) {
  console.warn("copy-leaflet: leaflet isn't installed yet; skipping");
  process.exit(0);
}
fs.mkdirSync(path.join(dest, "images"), { recursive: true });
for (const file of ["leaflet.js", "leaflet.css"]) {
  fs.copyFileSync(path.join(src, file), path.join(dest, file));
}
for (const img of fs.readdirSync(path.join(src, "images"))) {
  fs.copyFileSync(path.join(src, "images", img), path.join(dest, "images", img));
}
console.log("copy-leaflet: copied Leaflet to public/vendor/leaflet");
