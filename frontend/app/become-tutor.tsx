import { useRouter } from "expo-router";
import { LandingPage } from "@/src/landing";
import { useAuth } from "@/src/auth";

export default function BecomeTutor() {
  const router = useRouter();
  const { user } = useAuth();
  return (
    <LandingPage
      testID="become-tutor-screen"
      eyebrow="For educators"
      title="Become a tutor"
      heroImage="https://images.unsplash.com/photo-1544005313-94ddf0286df2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"
      intro="Share the language you love. Set your own rate, choose your hours, and get matched with warm families who value what you do."
      sections={[
        { icon: "dollar-sign", title: "Fair pay, fast payouts", body: "Set your hourly rate. We handle the payments — you keep 85% of every session." },
        { icon: "calendar", title: "You choose the hours", body: "Open your calendar when it works for you. No quotas, no penalties." },
        { icon: "award", title: "Show your accreditation", body: "Upload certificates and diplomas so parents can see your credentials at a glance." },
      ]}
      cta={{ label: user?.role === "tutor" ? "Edit my tutor profile" : "Start my tutor profile", testID: "become-tutor-cta", onPress: () => router.push(user?.role === "tutor" ? "/edit-tutor" : { pathname: "/(auth)/signup", params: { role: "tutor" } } as any) }}
    />
  );
}
