// Page-wide styles for the website. The web build is a single-page app ("output": "single" in
// app.json), so app/+html.tsx isn't used; these are added once when the app starts instead.
import { Platform } from "react-native";

const CSS = `
/* A clear outline on whatever has keyboard focus (WCAG 2.4.7). Mouse clicks don't show it. */
:focus-visible { outline: 3px solid #B83A23 !important; outline-offset: 2px !important; }
/* People who ask their device for less motion get (almost) none. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; }
}
`;

export function installWebStyles(): void {
  if (Platform.OS !== "web" || typeof document === "undefined" || document.getElementById("bb-global-styles")) return;
  document.documentElement.lang = "en";
  const style = document.createElement("style");
  style.id = "bb-global-styles";
  style.textContent = CSS;
  document.head.appendChild(style);
}
