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
import { ReviewPromptProvider } from "@/src/reviewprompt";
import { SessionReminderProvider } from "@/src/sessionreminder";

LogBox.ignoreAllLogs(true);
SplashScreen.preventAutoHideAsync();

function AuthGate() {
  const { user, loading, suspended } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    const publicRoutes = ["find-tutor", "become-tutor", "languages-near-you", "support", "mission", "blog", "privacy", "suspended"];
    const inAuth = segments[0] === "(auth)" || segments[0] === "onboarding";
    const isPublic = publicRoutes.includes(String(segments[0] ?? ""));
    const inAdmin = segments[0] === "admin";
    if (!user && suspended && segments[0] !== "suspended" && segments[0] !== "support") {
      router.replace("/suspended");
    } else if (!user && !inAuth && !isPublic) {
      router.replace("/onboarding");
    } else if (user && inAuth) {
      router.replace(user.is_admin ? "/admin" : "/(tabs)");
    } else if (user && user.is_admin && !inAdmin && segments[0] !== undefined && !isPublic) {
      if (segments[0] === "(tabs)") router.replace("/admin");
    }
  }, [user, loading, suspended, segments, router]);

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: "#FAF8F5" },
        animation: "slide_from_right",
        animationDuration: 260,
      }}
    >
      <Stack.Screen name="tutor/[id]" options={{ animation: "slide_from_bottom", animationDuration: 320 }} />
      <Stack.Screen name="parent-profile/[id]" options={{ animation: "slide_from_bottom", animationDuration: 320 }} />
      <Stack.Screen name="booking/[tutorId]" options={{ animation: "slide_from_bottom", animationDuration: 320 }} />
      <Stack.Screen name="booking-detail/[id]" options={{ animation: "slide_from_right", animationDuration: 260 }} />
      <Stack.Screen name="payment/[id]" options={{ animation: "slide_from_bottom", animationDuration: 320 }} />
      <Stack.Screen name="chat/[userId]" options={{ animation: "slide_from_right" }} />
    </Stack>
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
        <AuthProvider>
          <ToastProvider>
            <ReviewPromptProvider>
              <SessionReminderProvider>
                <DrawerProvider>
                  <NotificationsWatcher />
                  <AuthGate />
                </DrawerProvider>
              </SessionReminderProvider>
            </ReviewPromptProvider>
          </ToastProvider>
        </AuthProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
