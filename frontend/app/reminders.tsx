import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { apiFetch } from "@/src/api";
import { theme } from "@/src/theme";
import { Button, Input } from "@/src/ui";
import { useToast } from "@/src/toast";

interface Settings { email: boolean; sms: boolean; phone: string | null; phone_verified: boolean; sms_available: boolean }

/** A large, easy-to-tap on/off row. */
function ToggleRow({ icon, title, body, value, onChange, disabled, testID }: {
  icon: string; title: string; body: string; value: boolean; onChange: (v: boolean) => void; disabled?: boolean; testID?: string;
}) {
  return (
    <Pressable
      onPress={() => !disabled && onChange(!value)}
      disabled={disabled}
      style={[styles.toggle, disabled && { opacity: 0.6 }]}
      accessibilityRole="switch"
      accessibilityState={{ checked: value, disabled }}
      accessibilityLabel={title}
      testID={testID}
    >
      <View style={styles.toggleIcon}><Feather name={icon as any} size={22} color={theme.color.brandDark} /></View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={styles.toggleTitle}>{title}</Text>
        <Text style={styles.toggleBody}>{body}</Text>
      </View>
      <View style={[styles.track, value && styles.trackOn]}>
        <View style={[styles.knob, value && styles.knobOn]} />
      </View>
      <Text style={styles.stateText}>{value ? "On" : "Off"}</Text>
    </Pressable>
  );
}

export default function Reminders() {
  const router = useRouter();
  const { show } = useToast();
  const [s, setS] = useState<Settings | null>(null);
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState(false);
  const [code, setCode] = useState("");
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { apiFetch<Settings>("/auth/me/reminders").then(setS).catch(() => {}); }, []);

  const update = async (patch: Partial<Pick<Settings, "email" | "sms">>) => {
    try {
      setS(await apiFetch<Settings>("/auth/me/reminders", { method: "PUT", body: JSON.stringify(patch) }));
      show({ kind: "success", title: "Saved" });
    } catch (e: any) { show({ kind: "error", title: "Couldn't save", body: e?.message }); }
  };

  const sendCode = async () => {
    setBusy(true);
    try {
      const r = await apiFetch<{ phone: string }>("/auth/me/phone", { method: "POST", body: JSON.stringify({ phone, consent }) });
      setCodeSentTo(r.phone);
    } catch (e: any) { show({ kind: "error", title: "Couldn't send the code", body: e?.message }); }
    finally { setBusy(false); }
  };

  const confirmCode = async () => {
    setBusy(true);
    try {
      setS(await apiFetch<Settings>("/auth/me/phone/verify", { method: "POST", body: JSON.stringify({ code }) }));
      setCodeSentTo(null); setCode(""); setPhone("");
      show({ kind: "success", title: "Text reminders are on" });
    } catch (e: any) { show({ kind: "error", title: "Couldn't confirm", body: e?.message }); }
    finally { setBusy(false); }
  };

  const removePhone = async () => {
    try {
      setS(await apiFetch<Settings>("/auth/me/phone", { method: "DELETE" }));
      show({ kind: "success", title: "Phone number removed" });
    } catch (e: any) { show({ kind: "error", title: "Couldn't remove it", body: e?.message }); }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/profile"))} hitSlop={12} accessibilityRole="button" accessibilityLabel="Go back" testID="reminders-back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle} accessibilityRole="header">Session reminders</Text>
        <View style={{ width: 22 }} />
      </View>
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.intro}>
          We&apos;ll remind you the day before each session, and again about an hour before it starts.
        </Text>
        {!s ? <ActivityIndicator color={theme.color.brand} /> : (
          <>
            <ToggleRow icon="mail" title="Email reminders" body="Sent to the email address on your account."
              value={s.email} onChange={(v) => update({ email: v })} testID="reminders-email" />

            {s.phone_verified ? (
              <>
                <ToggleRow icon="smartphone" title="Text message reminders" body={`Sent to your phone ending ${s.phone?.slice(-4)}.`}
                  value={s.sms} onChange={(v) => update({ sms: v })} disabled={!s.sms_available} testID="reminders-sms" />
                <Pressable onPress={removePhone} style={styles.linkBtn} accessibilityRole="button" testID="reminders-remove-phone">
                  <Text style={styles.linkText}>Remove my phone number</Text>
                </Pressable>
              </>
            ) : !s.sms_available ? (
              <View style={styles.card} testID="reminders-sms-unavailable">
                <Feather name="smartphone" size={22} color={theme.color.onSurfaceSecondary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle}>Text message reminders</Text>
                  <Text style={styles.cardBody}>Coming soon. For now we&apos;ll remind you by email and in the app.</Text>
                </View>
              </View>
            ) : (
              <View style={styles.phoneBox} testID="reminders-phone-setup">
                <Text style={styles.cardTitle}>Get reminders by text message too</Text>
                {codeSentTo ? (
                  <>
                    <Text style={styles.cardBody}>We texted a 6-digit code to {codeSentTo}. Enter it below.</Text>
                    <Input label="Code from the text" value={code} onChangeText={setCode} keyboardType="number-pad" maxLength={6} testID="reminders-code" />
                    <Button title="Confirm my number" onPress={confirmCode} loading={busy} disabled={code.length !== 6} testID="reminders-confirm" />
                    <Pressable onPress={() => setCodeSentTo(null)} style={styles.linkBtn} accessibilityRole="button">
                      <Text style={styles.linkText}>Use a different number</Text>
                    </Pressable>
                  </>
                ) : (
                  <>
                    <Input label="Mobile phone number" value={phone} onChangeText={setPhone} keyboardType="phone-pad"
                      placeholder="(512) 555-0199" autoComplete="tel" testID="reminders-phone" />
                    <Text style={styles.small}>Outside the US and Canada? Start with your country code, like +44.</Text>
                    <Pressable onPress={() => setConsent(!consent)} style={styles.consent} accessibilityRole="checkbox"
                      accessibilityState={{ checked: consent }} testID="reminders-consent">
                      <View style={[styles.box, consent && styles.boxOn]}>{consent ? <Feather name="check" size={16} color="#fff" /> : null}</View>
                      <Text style={styles.consentText}>
                        I agree to get session reminder texts from Babybabel. About two texts per session. Message and data
                        rates may apply. Reply STOP to stop at any time.
                      </Text>
                    </Pressable>
                    <Button title="Text me a code" onPress={sendCode} loading={busy} disabled={!consent || phone.trim().length < 7} testID="reminders-send-code" />
                    <Text style={styles.small}>Your number is only used for reminders. It&apos;s never shown to tutors or families.</Text>
                  </>
                )}
              </View>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: theme.space.xl, paddingVertical: theme.space.md, borderBottomColor: theme.color.border, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  body: { padding: theme.space.xl, gap: theme.space.lg, width: "100%", maxWidth: 640, alignSelf: "center" },
  intro: { fontSize: theme.font.lg, lineHeight: 24, color: theme.color.onSurfaceSecondary },
  toggle: { flexDirection: "row", alignItems: "center", gap: theme.space.md, padding: theme.space.lg, borderRadius: theme.radius.lg, backgroundColor: theme.color.surfaceSecondary, minHeight: 72 },
  toggleIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.brandSoft, alignItems: "center", justifyContent: "center" },
  toggleTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  toggleBody: { fontSize: theme.font.base, color: theme.color.onSurfaceSecondary, lineHeight: 20 },
  track: { width: 52, height: 30, borderRadius: 15, backgroundColor: theme.color.borderStrong, padding: 3, justifyContent: "center" },
  trackOn: { backgroundColor: theme.color.success },
  knob: { width: 24, height: 24, borderRadius: 12, backgroundColor: "#fff" },
  knobOn: { alignSelf: "flex-end" },
  stateText: { width: 28, fontWeight: "700", color: theme.color.onSurface, fontSize: theme.font.base },
  card: { flexDirection: "row", gap: theme.space.md, alignItems: "center", padding: theme.space.lg, borderRadius: theme.radius.lg, borderWidth: 1, borderColor: theme.color.border },
  cardTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface },
  cardBody: { fontSize: theme.font.base, color: theme.color.onSurfaceSecondary, lineHeight: 20, marginTop: 2 },
  phoneBox: { padding: theme.space.lg, borderRadius: theme.radius.lg, borderWidth: 1, borderColor: theme.color.border, gap: theme.space.md },
  small: { fontSize: theme.font.base, color: theme.color.onSurfaceSecondary, lineHeight: 20 },
  consent: { flexDirection: "row", gap: theme.space.md, alignItems: "flex-start" },
  box: { width: 26, height: 26, borderRadius: 6, borderWidth: 2, borderColor: theme.color.borderStrong, alignItems: "center", justifyContent: "center", marginTop: 2 },
  boxOn: { backgroundColor: theme.color.brandDark, borderColor: theme.color.brandDark },
  consentText: { flex: 1, fontSize: theme.font.base, color: theme.color.onSurface, lineHeight: 21 },
  linkBtn: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  linkText: { color: theme.color.brandDark, fontWeight: "700", fontSize: theme.font.base, textDecorationLine: "underline" },
});
