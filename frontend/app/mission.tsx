import { useRouter } from "expo-router";
import { LandingPage } from "@/src/landing";

export default function Mission() {
  const router = useRouter();
  return (
    <LandingPage
      testID="mission-screen"
      eyebrow="Our story"
      title="Our mission"
      heroImage="https://images.unsplash.com/photo-1583468982228-19f19164aee2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"
      intro="We believe every child deserves a second language and a second family. Babybabel exists to make both feel warm, safe, and boundless — right at home."
      sections={[
        { icon: "heart", title: "Care first", body: "A tutor is a caregiver. That comes before any lesson plan, always." },
        { icon: "globe", title: "Every language", body: "From Basque to Bengali, we champion the languages the world's biggest apps forget." },
        { icon: "users", title: "Fair to educators", body: "Bilingual educators are undervalued everywhere. Not here — we pay properly and pay fast." },
        { icon: "sun", title: "Warm by design", body: "Our team fights for softness — in the product, in the tone, in the way we handle hard moments." },
      ]}
      cta={{ label: "Join Babybabel", testID: "mission-cta", onPress: () => router.push("/onboarding") }}
    />
  );
}
