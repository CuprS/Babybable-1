import { Platform } from "react-native";
import { fetch as expoFetch } from "expo/fetch";

/** POST a local file (image/doc) as multipart "file". Works on web and real devices. */
export async function uploadForm(url: string, uri: string, name: string, type: string, headers: Record<string, string> = {}) {
  const form = new FormData();
  if (Platform.OS === "web") {
    const blob = await (await fetch(uri)).blob();
    form.append("file", new File([blob], name, { type: blob.type || type }));
  } else {
    const blob = await (await expoFetch(uri)).blob();
    form.append("file", blob as any, name);
  }
  // Never set Content-Type: the runtime adds the multipart boundary.
  return fetch(url, { method: "POST", body: form, headers });
}
