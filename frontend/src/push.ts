// Push notifications via Expo's push service. Works in development/production builds on real
// devices; silently does nothing on web, simulators and Expo Go (which can't receive remote pushes).
import { Platform } from "react-native";
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import Constants from "expo-constants";
import { router } from "expo-router";
import { apiFetch } from "./api";
import { storage } from "./utils/storage";

const PUSH_TOKEN_KEY = "bb_push_token";

if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

function projectId(): string | undefined {
  const extra = (Constants.expoConfig?.extra || {}) as { eas?: { projectId?: string } };
  return extra.eas?.projectId || (Constants as any).easConfig?.projectId;
}

/** Ask permission (once), get this device's Expo push token and register it with the server. */
export async function registerForPush(): Promise<void> {
  if (Platform.OS === "web" || !Device.isDevice) return;
  try {
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "Bookings and messages",
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== "granted") ({ status } = await Notifications.requestPermissionsAsync());
    if (status !== "granted") return;
    const id = projectId();
    if (!id) return; // needs an EAS project id (set by `eas init`)
    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId: id });
    await apiFetch("/push-tokens", { method: "POST", body: JSON.stringify({ token, platform: Platform.OS }) });
    await storage.setItem(PUSH_TOKEN_KEY, token);
  } catch (e) {
    console.warn("push registration skipped", e);
  }
}

/** Stop pushes to this device (on sign-out). */
export async function unregisterPush(): Promise<void> {
  if (Platform.OS === "web") return;
  try {
    const token = await storage.getItem<string>(PUSH_TOKEN_KEY, "");
    if (token) {
      await apiFetch(`/push-tokens?token=${encodeURIComponent(token)}`, { method: "DELETE" });
      await storage.setItem(PUSH_TOKEN_KEY, "");
    }
  } catch {}
}

/** Where tapping a notification should take you. */
export function routeForNotification(data: Record<string, any> | undefined): string | null {
  if (!data) return null;
  if (data.booking_id) return `/booking-detail/${data.booking_id}`;
  if (data.from_user_id) return `/chat/${data.from_user_id}`;
  if (data.kind === "w9:required") return "/w9";
  if (data.kind === "verification") return "/verify-tutor";
  return null;
}

/** Open the right screen when someone taps a push. Returns an unsubscribe function. */
export function listenForNotificationTaps(): () => void {
  if (Platform.OS === "web") return () => {};
  const sub = Notifications.addNotificationResponseReceivedListener((response) => {
    const path = routeForNotification(response.notification.request.content.data as Record<string, any>);
    if (path) router.push(path as any);
  });
  return () => sub.remove();
}
