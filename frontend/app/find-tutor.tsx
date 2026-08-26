import { useRouter } from "expo-router";
import { LandingPage } from "@/src/landing";
import { useAuth } from "@/src/auth";

export default function FindTutor() {
  const router = useRouter();
  const { user } = useAuth();
  return (
    <LandingPage
      testID="find-tutor-screen"
      eyebrow="For parents"
      title="Find a tutor"
      heroImage="https://images.unsplash.com/photo-1503454537195-1dcabb73ffb9?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"
      intro="Warm, vetted tutors who love kids and speak the language you want your child to grow up hearing. Filter by language, city, and vibe — book in minutes."
      sections={[
        { icon: "search", title: "Filter by language", body: "Spanish, French, Mandarin, Arabic, and dozens more — every language your family cares about." },
        { icon: "shield", title: "Every tutor is vetted", body: "Background checks, ID verification, and reviews from real parents." },
        { icon: "heart", title: "Care + curriculum", body: "Tutors watch, play, cook, and read — teaching a language the way children actually learn it." },
      ]}
      cta={{ label: user ? "Browse tutors" : "Create a parent account", testID: "find-tutor-cta", onPress: () => router.push(user ? "/(tabs)" : { pathname: "/(auth)/signup", params: { role: "parent" } } as any) }}
    />
  );
}
