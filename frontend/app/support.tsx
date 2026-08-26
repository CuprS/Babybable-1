import { Linking } from "react-native";
import { LandingPage } from "@/src/landing";

export default function Support() {
  return (
    <LandingPage
      testID="support-screen"
      eyebrow="We're here"
      title="Support"
      intro="Real humans, warm answers. Whether it's a booking hiccup or a big question about your child's learning journey, we've got you."
      sections={[
        { icon: "mail", title: "Email us", body: "help@babybabel.co · We reply within 4 hours, most days sooner." },
        { icon: "message-circle", title: "Live chat", body: "Tap the message icon on any tutor's profile or open your Messages tab." },
        { icon: "book", title: "Help center", body: "Guides on booking, payments, cancellations, and how to prepare for your first session." },
        { icon: "shield", title: "Trust & safety", body: "Report a problem 24/7. All tutors are background-checked; we take safety personally." },
      ]}
      cta={{ label: "Email support", testID: "support-cta", onPress: () => Linking.openURL("mailto:help@babybabel.co") }}
    />
  );
}
