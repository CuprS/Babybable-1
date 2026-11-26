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
      intro="Warm, verified tutors who love kids and speak the language you want your child to grow up hearing. Filter by language and distance, then book in minutes."
      sections={[
        { icon: "search", title: "Filter by language", body: "Any language a tutor teaches — from Spanish and Mandarin to the ones bigger apps forget." },
        { icon: "shield", title: "Every tutor is verified", body: "Our team reviews each tutor's photo ID and background check before they can be booked, and only families who had a session can leave a review." },
        { icon: "credit-card", title: "Clear prices", body: "You pay the tutor's hourly rate plus a 1% platform fee, shown before you pay. Cancel at least 24 hours ahead for a full refund." },
        { icon: "heart", title: "Care + curriculum", body: "Tutors watch, play, cook, and read — teaching a language the way children actually learn it." },
      ]}
      cta={{ label: user ? "Browse tutors" : "Create a parent account", testID: "find-tutor-cta", onPress: () => router.push(user ? "/(tabs)" : { pathname: "/(auth)/signup", params: { role: "parent" } } as any) }}
    />
  );
}
