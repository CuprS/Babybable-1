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
        { icon: "dollar-sign", title: "Keep 100% of your rate", body: "You set your hourly rate and keep all of it. Families pay a small 1% platform fee on top — you never pay to use Babybabel." },
        { icon: "calendar", title: "You choose the hours", body: "Open your calendar when it suits you, and accept or decline each booking request." },
        { icon: "shield", title: "Get verified first", body: "Upload a photo ID and a recent background-check certificate. Once our team approves them (usually within 1–2 working days), families can find and book you." },
        { icon: "award", title: "Show your accreditation", body: "Add certificates and diplomas so parents can see your experience at a glance." },
      ]}
      cta={{ label: user?.role === "tutor" ? "Edit my tutor profile" : "Start my tutor profile", testID: "become-tutor-cta", onPress: () => router.push(user?.role === "tutor" ? "/edit-tutor" : { pathname: "/(auth)/signup", params: { role: "tutor" } } as any) }}
    />
  );
}
