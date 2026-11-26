import { useEffect, useState } from "react";
import { Linking, View, type StyleProp, type ImageStyle, type ViewStyle } from "react-native";
import { Image, type ImageContentFit } from "expo-image";
import { apiFetch, fileUrl } from "./api";
import { theme } from "./theme";

/**
 * Private files (children's photos, accreditation documents, unsaved uploads) need the
 * sign-in to load, but images and links can't send it. The API checks access and returns a
 * link that works for this one file for ~15 minutes.
 */
export async function privateFileUrl(path?: string | null): Promise<string | undefined> {
  if (!path) return undefined;
  if (path.startsWith("http")) return path;
  const r = await apiFetch<{ url: string }>(`/files-link?path=${encodeURIComponent(path)}`);
  return fileUrl(r.url);
}

/** Open a private document (e.g. an accreditation PDF) in the browser / system viewer. */
export async function openPrivateFile(path?: string | null): Promise<void> {
  const url = await privateFileUrl(path);
  if (url) await Linking.openURL(url);
}

/** An <Image> for a file only some people may see. Shows a neutral box until the link is ready. */
export function PrivateImage({ path, style, contentFit = "cover", testID }: {
  path?: string | null;
  style?: StyleProp<ImageStyle>;
  contentFit?: ImageContentFit;
  testID?: string;
}) {
  const [uri, setUri] = useState<string | undefined>();
  useEffect(() => {
    let live = true;
    setUri(undefined);
    privateFileUrl(path).then((u) => { if (live) setUri(u); }).catch(() => {});
    return () => { live = false; };
  }, [path]);
  if (!uri) return <View style={[style as StyleProp<ViewStyle>, { backgroundColor: theme.color.surfaceSecondary }]} testID={testID} />;
  return <Image source={{ uri }} style={style} contentFit={contentFit} testID={testID} />;
}
