import { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as Print from "expo-print";
import { apiFetch } from "@/src/api";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { Button, Input } from "@/src/ui";
import { useToast } from "@/src/toast";
import { track } from "@/src/analytics";

interface W9 {
  id: string;
  tutor_user_id: string;
  tutor_name: string;
  tutor_email: string;
  legal_name: string;
  business_name: string;
  tax_classification: string;
  llc_tax_class: string;
  other_classification: string;
  address: string;
  city: string;
  state: string;
  zip_code: string;
  country: string;
  tin_type: "ssn" | "ein";
  tin_masked: string;
  signature_name: string;
  is_us_person: boolean;
  exempt_from_backup: boolean;
  signed_at: string;
  updated_at: string;
}

const CLASSIFICATIONS: { key: string; label: string; hint?: string }[] = [
  { key: "individual", label: "Individual / Sole proprietor" },
  { key: "c_corp", label: "C Corporation" },
  { key: "s_corp", label: "S Corporation" },
  { key: "partnership", label: "Partnership" },
  { key: "trust_estate", label: "Trust / Estate" },
  { key: "llc", label: "Limited liability company (LLC)" },
  { key: "other", label: "Other" },
];

export default function W9Screen() {
  const router = useRouter();
  const { user } = useAuth();
  const { show } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existing, setExisting] = useState<W9 | null>(null);
  const [required, setRequired] = useState(false);
  const [printing, setPrinting] = useState(false);

  // Form state
  const [legalName, setLegalName] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [classification, setClassification] = useState<string>("individual");
  const [llcClass, setLlcClass] = useState<"C" | "S" | "P" | "">("");
  const [otherClass, setOtherClass] = useState("");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");
  const [zipCode, setZipCode] = useState("");
  const [tinType, setTinType] = useState<"ssn" | "ein">("ssn");
  const [tin, setTin] = useState("");
  const [signatureName, setSignatureName] = useState("");
  const [isUsPerson, setIsUsPerson] = useState(true);
  const [exempt, setExempt] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [me, status] = await Promise.all([
          apiFetch<W9 | null>("/w9/me"),
          apiFetch<{ required: boolean; submitted: boolean; completed_session: boolean }>("/w9/me/status"),
        ]);
        if (me) {
          setExisting(me);
          hydrate(me);
        }
        setRequired(status.required);
      } catch {}
      finally { setLoading(false); }
    })();
    // Pre-fill name if we know it.
    if (user?.name && !legalName) setLegalName(user.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hydrate = (m: W9) => {
    setLegalName(m.legal_name);
    setBusinessName(m.business_name || "");
    setClassification(m.tax_classification);
    setLlcClass((m.llc_tax_class as any) || "");
    setOtherClass(m.other_classification || "");
    setAddress(m.address);
    setCity(m.city);
    setStateName(m.state);
    setZipCode(m.zip_code);
    setTinType(m.tin_type);
    setTin(""); // never populate TIN back; user re-enters if editing
    setSignatureName(m.signature_name);
    setIsUsPerson(m.is_us_person);
    setExempt(m.exempt_from_backup);
  };

  const tinLabel = tinType === "ssn" ? "Social Security Number" : "Employer ID Number";
  const tinDigits = useMemo(() => tin.replace(/\D/g, ""), [tin]);
  const tinValid = tinDigits.length === 9;

  const canSave = legalName.trim().length > 0
    && address.trim().length > 0
    && city.trim().length > 0
    && stateName.trim().length > 0
    && zipCode.trim().length > 0
    && signatureName.trim().length > 0
    && tinValid
    && (classification !== "llc" || !!llcClass)
    && (classification !== "other" || otherClass.trim().length > 0);

  const submit = async () => {
    if (!canSave) {
      show({ kind: "error", title: "Missing fields", body: "Fill everything marked with * before signing." });
      return;
    }
    setSaving(true);
    try {
      const saved = await apiFetch<W9>("/w9", {
        method: "POST",
        body: JSON.stringify({
          legal_name: legalName.trim(),
          business_name: businessName.trim(),
          tax_classification: classification,
          llc_tax_class: classification === "llc" ? llcClass : "",
          other_classification: classification === "other" ? otherClass.trim() : "",
          address: address.trim(),
          city: city.trim(),
          state: stateName.trim(),
          zip_code: zipCode.trim(),
          country: "US",
          tin_type: tinType,
          tin: tinDigits,
          signature_name: signatureName.trim(),
          is_us_person: isUsPerson,
          exempt_from_backup: exempt,
        }),
      });
      setExisting(saved);
      setTin("");
      setRequired(false);
      track("w9_submitted", { classification, tin_type: tinType });
      show({ kind: "success", title: "W-9 saved", body: "Tap Print to save a copy for your records." });
    } catch (e: any) {
      show({ kind: "error", title: "Couldn't save", body: e?.message || "Try again in a moment." });
    } finally {
      setSaving(false);
    }
  };

  const doPrint = async () => {
    if (!existing) return;
    setPrinting(true);
    try {
      const html = buildW9Html(existing);
      if (Platform.OS === "web") {
        const w = window.open("", "_blank");
        if (w) { w.document.write(html); w.document.close(); setTimeout(() => w.print(), 300); }
      } else {
        await Print.printAsync({ html });
      }
      track("w9_printed", {});
    } catch (e: any) {
      Alert.alert("Print failed", e?.message || "Try again in a moment.");
    } finally { setPrinting(false); }
  };

  if (loading) {
    return <View style={styles.center}><ActivityIndicator color={theme.color.brand} /></View>;
  }
  if (user?.role !== "tutor") {
    return <View style={styles.center}><Text>W-9 forms are for tutors only.</Text></View>;
  }

  return (
    <SafeAreaView style={styles.wrap} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="w9-back">
          <Feather name="arrow-left" size={22} color={theme.color.onSurface} />
        </Pressable>
        <Text style={styles.title}>Form W-9</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.space.lg, paddingBottom: 120, gap: theme.space.md }}>
        {required && !existing && (
          <View style={styles.nudge} testID="w9-nudge">
            <Feather name="alert-circle" size={18} color={theme.color.brandDark} />
            <View style={{ flex: 1 }}>
              <Text style={styles.nudgeTitle}>W-9 required</Text>
              <Text style={styles.nudgeSub}>You&apos;ve completed your first paid session — please file this so we can pay you.</Text>
            </View>
          </View>
        )}
        {existing && (
          <View style={styles.savedBanner} testID="w9-saved-banner">
            <Feather name="check-circle" size={18} color={theme.color.success} />
            <View style={{ flex: 1 }}>
              <Text style={styles.savedTitle}>W-9 on file</Text>
              <Text style={styles.savedSub}>
                {existing.tin_type.toUpperCase()} {existing.tin_masked} · signed {new Date(existing.signed_at).toLocaleDateString()}
              </Text>
            </View>
            <Pressable onPress={doPrint} style={styles.printBtn} disabled={printing} testID="w9-print">
              <Feather name="printer" size={16} color="#fff" />
              <Text style={styles.printText}>{printing ? "…" : "Print"}</Text>
            </Pressable>
          </View>
        )}

        <Text style={styles.blurb}>Request for Taxpayer Identification Number and Certification. Your answers stay private; only Babybabel admins can see this to issue year-end 1099s.</Text>

        <Section title="1. Legal name *" hint="As shown on your income-tax return.">
          <Input value={legalName} onChangeText={setLegalName} placeholder="e.g. Jane Q. Smith" testID="w9-legal-name" />
        </Section>
        <Section title="2. Business name (if different)" hint="DBA, trade name, or disregarded entity name.">
          <Input value={businessName} onChangeText={setBusinessName} placeholder="Optional" testID="w9-business-name" />
        </Section>

        <Section title="3. Federal tax classification *">
          <View style={styles.radioList}>
            {CLASSIFICATIONS.map((c) => (
              <Pressable
                key={c.key}
                onPress={() => setClassification(c.key)}
                style={[styles.radio, classification === c.key && styles.radioOn]}
                testID={`w9-class-${c.key}`}
              >
                <View style={[styles.radioDot, classification === c.key && styles.radioDotOn]} />
                <Text style={styles.radioLabel}>{c.label}</Text>
              </Pressable>
            ))}
          </View>
          {classification === "llc" && (
            <View style={{ flexDirection: "row", gap: theme.space.sm, marginTop: theme.space.sm }}>
              {(["C", "S", "P"] as const).map((k) => (
                <Pressable
                  key={k}
                  onPress={() => setLlcClass(k)}
                  style={[styles.pill, llcClass === k && styles.pillOn]}
                  testID={`w9-llc-${k}`}
                >
                  <Text style={[styles.pillText, llcClass === k && styles.pillTextOn]}>{k}</Text>
                </Pressable>
              ))}
              <Text style={styles.tinyHint}>C=C-corp · S=S-corp · P=Partnership</Text>
            </View>
          )}
          {classification === "other" && (
            <Input value={otherClass} onChangeText={setOtherClass} placeholder="Describe classification" testID="w9-other-desc" />
          )}
        </Section>

        <Section title="Address *" hint="Number, street, apt/suite">
          <Input value={address} onChangeText={setAddress} placeholder="123 Main St, Apt 4B" testID="w9-address" />
          <View style={{ flexDirection: "row", gap: theme.space.sm }}>
            <View style={{ flex: 2 }}><Input value={city} onChangeText={setCity} placeholder="City *" testID="w9-city" /></View>
            <View style={{ flex: 1 }}><Input value={stateName} onChangeText={setStateName} placeholder="State *" testID="w9-state" /></View>
            <View style={{ flex: 1 }}><Input value={zipCode} onChangeText={setZipCode} placeholder="ZIP *" keyboardType="number-pad" testID="w9-zip" /></View>
          </View>
        </Section>

        <Section title="Part I. Taxpayer Identification Number *">
          <View style={{ flexDirection: "row", gap: theme.space.sm, marginBottom: theme.space.sm }}>
            <Pressable onPress={() => setTinType("ssn")} style={[styles.pill, tinType === "ssn" && styles.pillOn]} testID="w9-tin-ssn">
              <Text style={[styles.pillText, tinType === "ssn" && styles.pillTextOn]}>SSN</Text>
            </Pressable>
            <Pressable onPress={() => setTinType("ein")} style={[styles.pill, tinType === "ein" && styles.pillOn]} testID="w9-tin-ein">
              <Text style={[styles.pillText, tinType === "ein" && styles.pillTextOn]}>EIN</Text>
            </Pressable>
          </View>
          <Input
            value={tin}
            onChangeText={(v) => setTin(v.replace(/[^\d-]/g, ""))}
            placeholder={tinType === "ssn" ? "e.g. 123-45-6789" : "e.g. 12-3456789"}
            keyboardType="number-pad"
            testID="w9-tin"
            label={tinLabel}
          />
          <Text style={styles.tinyHint}>{tinValid ? "Looks good." : "9 digits required."}</Text>
        </Section>

        <Section title="Part II. Certification *">
          <Pressable style={styles.checkRow} onPress={() => setIsUsPerson((v) => !v)} testID="w9-us-person">
            <Feather name={isUsPerson ? "check-square" : "square"} size={22} color={theme.color.brand} />
            <Text style={styles.checkText}>I am a US citizen or resident alien.</Text>
          </Pressable>
          <Pressable style={styles.checkRow} onPress={() => setExempt((v) => !v)} testID="w9-exempt">
            <Feather name={exempt ? "check-square" : "square"} size={22} color={theme.color.brand} />
            <Text style={styles.checkText}>I am exempt from backup withholding.</Text>
          </Pressable>
          <Input value={signatureName} onChangeText={setSignatureName} placeholder="Type your full name to sign" testID="w9-signature" label="Signature (typed) *" />
          <Text style={styles.tinyHint}>
            By tapping Save & Sign, you certify under penalties of perjury that the info above is correct.
          </Text>
        </Section>

        <View style={{ marginTop: theme.space.md }}>
          <Button
            testID="w9-save-btn"
            title={existing ? "Update & re-sign" : "Save & sign W-9"}
            onPress={submit}
            loading={saving}
          />
        </View>
        {existing && (
          <Pressable onPress={doPrint} disabled={printing} style={styles.secondaryBtn} testID="w9-print-bottom">
            <Feather name="printer" size={18} color={theme.color.brand} />
            <Text style={styles.secondaryText}>{printing ? "Preparing…" : "Print / save as PDF"}</Text>
          </Pressable>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: theme.space.sm }}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {hint ? <Text style={styles.sectionHint}>{hint}</Text> : null}
      {children}
    </View>
  );
}

function classificationLabel(k: string, llc?: string, other?: string) {
  const map: Record<string, string> = {
    individual: "Individual / Sole proprietor",
    c_corp: "C Corporation",
    s_corp: "S Corporation",
    partnership: "Partnership",
    trust_estate: "Trust / Estate",
    llc: `LLC (${llc || "?"})`,
    other: `Other (${other || ""})`,
    sole_proprietor: "Sole proprietor",
  };
  return map[k] || k;
}

function buildW9Html(w: W9): string {
  const esc = (v: string) => String(v || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] || c));
  const cls = esc(classificationLabel(w.tax_classification, w.llc_tax_class, w.other_classification));
  const date = new Date(w.signed_at).toLocaleDateString();
  return `<!doctype html>
<html><head><meta charset="utf-8" />
<title>Form W-9 — ${esc(w.legal_name)}</title>
<style>
  @page { margin: 24mm 18mm; }
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; color: #1f1a17; font-size: 12px; }
  h1 { font-size: 20px; letter-spacing: -0.3px; margin: 0 0 4px; }
  h2 { font-size: 13px; margin: 24px 0 6px; text-transform: uppercase; letter-spacing: 0.6px; color: #E4572E; }
  .sub { color: #6b6260; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  td { border: 1px solid #d8d1cd; padding: 8px 10px; vertical-align: top; }
  td.label { background: #f8f3ee; width: 34%; font-weight: 700; color: #5a3a2a; }
  .sig { margin-top: 26px; border-top: 1px solid #d8d1cd; padding-top: 10px; }
  .brand { color: #E4572E; font-weight: 700; }
  .footer { margin-top: 30px; font-size: 10px; color: #8a807c; }
</style>
</head><body>
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <h1>Form W-9 <span style="font-size:12px;color:#6b6260;">(Rev. Babybabel)</span></h1>
      <div class="sub">Request for Taxpayer Identification Number and Certification</div>
    </div>
    <div style="text-align:right">
      <div class="brand">Babybabel</div>
      <div style="color:#6b6260">Language childcare marketplace</div>
    </div>
  </div>
  <h2>Identifying information</h2>
  <table>
    <tr><td class="label">1. Name (as shown on your tax return)</td><td>${esc(w.legal_name)}</td></tr>
    <tr><td class="label">2. Business name / DBA</td><td>${esc(w.business_name) || "—"}</td></tr>
    <tr><td class="label">3. Federal tax classification</td><td>${cls}</td></tr>
    <tr><td class="label">4. Exempt from backup withholding?</td><td>${w.exempt_from_backup ? "Yes" : "No"}</td></tr>
    <tr><td class="label">5. Address</td><td>${esc(w.address)}</td></tr>
    <tr><td class="label">6. City, State, ZIP</td><td>${esc(w.city)}, ${esc(w.state)} ${esc(w.zip_code)}</td></tr>
    <tr><td class="label">7. Country</td><td>${esc(w.country || "US")}</td></tr>
  </table>
  <h2>Part I — Taxpayer Identification Number</h2>
  <table>
    <tr><td class="label">Type</td><td>${w.tin_type.toUpperCase()}</td></tr>
    <tr><td class="label">TIN</td><td>${esc(w.tin_masked)}</td></tr>
  </table>
  <h2>Part II — Certification</h2>
  <p>Under penalties of perjury, I certify that:</p>
  <ol>
    <li>The number shown on this form is my correct taxpayer identification number.</li>
    <li>I am not subject to backup withholding${w.exempt_from_backup ? "" : " unless notified otherwise by the IRS"}.</li>
    <li>${w.is_us_person ? "I am a U.S. citizen or other U.S. person." : "I am NOT a U.S. person (see instructions)."}</li>
  </ol>
  <div class="sig">
    <div>Signature: <strong>${esc(w.signature_name)}</strong></div>
    <div>Signed on ${esc(date)} · Submitted by ${esc(w.tutor_name)} (${esc(w.tutor_email)})</div>
  </div>
  <div class="footer">
    Generated by Babybabel · Not a substitute for IRS Form W-9. Consult a tax professional if in doubt.
  </div>
</body></html>`;
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: theme.space.xl },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: theme.space.lg, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  title: { fontSize: theme.font.xl, fontWeight: "700", color: theme.color.onSurface },
  blurb: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm },
  nudge: {
    flexDirection: "row", alignItems: "center", gap: theme.space.sm,
    padding: theme.space.md, borderRadius: theme.radius.md,
    backgroundColor: theme.color.brandSoft, borderWidth: 1, borderColor: theme.color.brand,
  },
  nudgeTitle: { color: theme.color.brandDark, fontWeight: "700" },
  nudgeSub: { color: theme.color.brandDark, opacity: 0.9, fontSize: theme.font.sm, marginTop: 2 },
  savedBanner: {
    flexDirection: "row", alignItems: "center", gap: theme.space.sm,
    padding: theme.space.md, borderRadius: theme.radius.md,
    backgroundColor: theme.color.surfaceSecondary,
  },
  savedTitle: { color: theme.color.onSurface, fontWeight: "700" },
  savedSub: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: 2 },
  printBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: theme.space.md, paddingVertical: 8,
    borderRadius: theme.radius.pill, backgroundColor: theme.color.brand,
  },
  printText: { color: "#fff", fontWeight: "700" },
  sectionTitle: { fontSize: theme.font.lg, fontWeight: "700", color: theme.color.onSurface, marginTop: theme.space.md },
  sectionHint: { color: theme.color.onSurfaceSecondary, fontSize: theme.font.sm, marginTop: -4 },
  radioList: { gap: 6 },
  radio: {
    flexDirection: "row", alignItems: "center", gap: theme.space.sm,
    paddingVertical: 10, paddingHorizontal: 12,
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
    backgroundColor: theme.color.surface,
  },
  radioOn: { borderColor: theme.color.brand, backgroundColor: theme.color.brandSoft },
  radioDot: { width: 14, height: 14, borderRadius: 7, borderWidth: 2, borderColor: theme.color.borderStrong },
  radioDotOn: { borderColor: theme.color.brand, backgroundColor: theme.color.brand },
  radioLabel: { color: theme.color.onSurface, fontWeight: "600" },
  pill: {
    paddingHorizontal: theme.space.md, paddingVertical: 8, borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.borderStrong, backgroundColor: theme.color.surface,
  },
  pillOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  pillText: { color: theme.color.onSurface, fontWeight: "700" },
  pillTextOn: { color: "#fff" },
  tinyHint: { color: theme.color.muted, fontSize: 11, marginTop: 2 },
  checkRow: { flexDirection: "row", alignItems: "center", gap: theme.space.sm, paddingVertical: 6 },
  checkText: { color: theme.color.onSurface, flex: 1, fontSize: theme.font.base },
  secondaryBtn: {
    marginTop: theme.space.sm,
    height: 52, borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.brand,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.color.surface,
  },
  secondaryText: { color: theme.color.brand, fontWeight: "700", fontSize: theme.font.lg },
});
