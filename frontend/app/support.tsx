import { Linking } from "react-native";
import { LandingPage } from "@/src/landing";

export default function Support() {
  return (
    <LandingPage
      testID="support-screen"
      eyebrow="We're here"
      title="Support"
      intro="Real humans, warm answers. Whether it's a booking hiccup or a question about your child's learning, write to us."
      sections={[
        { icon: "mail", title: "Email us", body: "help@babybabel.co — tell us what happened and, if it's about a booking, which one." },
        { icon: "message-circle", title: "Talk to your tutor or family", body: "Open your Messages tab, or tap Message on a tutor's profile." },
        { icon: "calendar", title: "Bookings, cancellations and refunds", body: "Open the booking in your Bookings tab to move or cancel it. Families get a full refund when they cancel at least 24 hours ahead, or whenever the tutor cancels." },
        { icon: "shield", title: "Trust & safety", body: "Every tutor's photo ID and background check is reviewed by our team before they can be booked. If something isn't right, use Block & report on the profile or chat, or email us." },
      ]}
      cta={{ label: "Email support", testID: "support-cta", onPress: () => Linking.openURL("mailto:help@babybabel.co") }}
    />
  );
}
