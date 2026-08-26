import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { LogBox, StatusBar } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { AuthProvider, useAuth } from "@/src/auth";
import { DrawerProvider } from "@/src/drawer";
import { ToastProvider } from "@/src/toast";
import { NotificationsWatcher } from "@/src/notifications";
import { PostHogProvider } from "posthog-react-native";

LogBox.ignoreAllLogs(true);
SplashScreen.preventAutoHideAsync();

function AuthGate() {
  const { user, loading } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    const publicRoutes = ["find-tutor", "become-tutor", "languages-near-you", "support", "mission", "blog", "privacy"];
    const inAuth = segments[0] === "(auth)" || segments[0] === "onboarding";
    const isPublic = publicRoutes.includes(String(segments[0] ?? ""));
    if (!user && !inAuth && !isPublic) {
      router.replace("/onboarding");
    } else if (user && inAuth) {
      router.replace("/(tabs)");
    }
  }, [user, loading, segments, router]);

  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#FAF8F5" } }} />
  );
}

export default function RootLayout() {
  const [loaded, error] = useIconFonts();

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync();
  }, [loaded, error]);

  if (!loaded && !error) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <StatusBar barStyle="dark-content" backgroundColor="#FAF8F5" />
        <PostHogProvider
          apiKey={process.env.EXPO_PUBLIC_POSTHOG_KEY || "phc_placeholder"}
          options={{
            host: process.env.EXPO_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com",
            captureAppLifecycleEvents: true,
            enableSessionReplay: false,
            disabled: !process.env.EXPO_PUBLIC_POSTHOG_KEY,
          }}
          autocapture={{ captureScreens: true, captureTouches: false }}
        >
          <AuthProvider>
            <ToastProvider>
              <DrawerProvider>
                <NotificationsWatcher />
                <AuthGate />
              </DrawerProvider>
            </ToastProvider>
          </AuthProvider>
        </PostHogProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
