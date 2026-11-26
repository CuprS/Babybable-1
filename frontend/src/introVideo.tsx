// Short intro clip on the website's landing screen. It plays once when the site is opened, then
// fades away to show the photo underneath. It's skipped (photo only) in the phone apps, for
// people who ask their device for reduced motion, and on later visits to the landing screen in
// the same browser tab. If the clip can't play (slow connection, autoplay blocked), the photo shows.
import { createElement, useEffect, useState } from "react";
import { Platform, StyleSheet, View } from "react-native";

const SRC = "/intro.mp4";
const SEEN_KEY = "bb_intro_seen";
const FADE_MS = 700;
// Don't keep people waiting on a slow connection: give up if it hasn't started by then.
const START_TIMEOUT_MS = 4000;

function shouldPlay(): boolean {
  if (Platform.OS !== "web" || typeof window === "undefined") return false;
  try {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return false;
    if (window.sessionStorage.getItem(SEEN_KEY)) return false;
  } catch {
    // Storage blocked: just play it.
  }
  return true;
}

export function IntroVideo() {
  const [phase, setPhase] = useState<"playing" | "fading" | "done">(() => (shouldPlay() ? "playing" : "done"));
  const [started, setStarted] = useState(false);

  const finish = () => {
    try { window.sessionStorage.setItem(SEEN_KEY, "1"); } catch { /* ignore */ }
    setPhase((p) => (p === "playing" ? "fading" : p));
  };

  useEffect(() => {
    if (phase === "fading") {
      const t = setTimeout(() => setPhase("done"), FADE_MS);
      return () => clearTimeout(t);
    }
  }, [phase]);

  useEffect(() => {
    if (phase !== "playing" || started) return;
    const t = setTimeout(finish, START_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [phase, started]);

  if (phase === "done") return null;
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none" testID="intro-video">
      {createElement("video", {
        src: SRC,
        autoPlay: true,
        muted: true,
        playsInline: true,
        preload: "auto",
        "aria-hidden": true,
        onPlaying: () => setStarted(true),
        onEnded: finish,
        onError: finish,
        style: {
          width: "100%",
          height: "100%",
          objectFit: "cover",
          backgroundColor: "#000",
          opacity: phase === "fading" ? 0 : 1,
          transition: `opacity ${FADE_MS}ms ease`,
        },
      })}
    </View>
  );
}
