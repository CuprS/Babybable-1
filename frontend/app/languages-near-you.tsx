import { useRouter } from "expo-router";
import { LandingPage } from "@/src/landing";

export default function LanguagesNearYou() {
  const router = useRouter();
  return (
    <LandingPage
      testID="languages-near-you-screen"
      eyebrow="Explore"
      title="Languages near you"
      heroImage="https://images.unsplash.com/photo-1591123120675-6f7f1aae0e5b?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"
      intro="See which languages are being taught in your neighborhood. Some are booked up fast — we'll show you the ones with tutors available this week."
      sections={[
        { icon: "map-pin", title: "Popular in your city", body: "Spanish, French, and Mandarin lead in most metros — but the long tail is what makes Babybabel special." },
        { icon: "trending-up", title: "Rising this month", body: "Arabic, Portuguese, and Japanese are seeing 2× more bookings than last quarter." },
        { icon: "coffee", title: "Language cafés", body: "Local playgroups where kids and tutors gather. Coming soon to New York, London, and São Paulo." },
      ]}
      cta={{ label: "Explore tutors", testID: "languages-cta", onPress: () => router.push("/(tabs)") }}
    />
  );
}
