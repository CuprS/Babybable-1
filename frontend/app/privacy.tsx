import { LandingPage } from "@/src/landing";

// Describes what the code actually stores. Keep it in sync when data handling changes, and have
// it reviewed (GDPR / CCPA / COPPA as applicable) before launch.
export default function Privacy() {
  return (
    <LandingPage
      testID="privacy-screen"
      eyebrow="Legal"
      title="Privacy Policy"
      intro="We keep as little about you as we can, only use it to run Babybabel, and never sell it. Here's exactly what we store and why."
      sections={[
        {
          icon: "user",
          title: "Your account",
          body: "Name, email, whether you're a family or a tutor, your time zone, and an optional profile photo. Passwords are stored only as a one-way hash, so nobody — including us — can read them.",
        },
        {
          icon: "home",
          title: "Families",
          body: "Your city (to show nearby tutors), the languages you're interested in, and your children's first names and ages. Children's photos are optional and only you can see them. Tutors see your city, never your exact location.",
        },
        {
          icon: "award",
          title: "Tutors",
          body: "Your public profile: bio, languages, rate, availability, cities and any certificates you choose to show. Your photo ID and background-check certificate are seen only by the Babybabel team, to verify you. US tutors' W-9 tax details are encrypted and only used for tax reporting.",
        },
        {
          icon: "calendar",
          title: "Bookings and messages",
          body: "Session details, messages between you and the people you book with, and reviews. Messages are only visible to the two people in the conversation, and to our safety team if one of you reports it. Before a family and tutor have a booking, messages that share a phone number, email, address or outside payment method are labelled and checked by our safety team, to stop scams and keep children safe.",
        },
        {
          icon: "bell",
          title: "Reminders",
          body: "We email you before each session; you can turn this off in Profile. If you choose text reminders, we keep your mobile number only for that, never show it to anyone, and delete it when you remove it or close your account.",
        },
        {
          icon: "credit-card",
          title: "Payments",
          body: "Stripe processes all payments. We never see or store your card number — only the amount and whether the payment succeeded.",
        },
        {
          icon: "share-2",
          title: "Who else handles your data",
          body: "Only the services we need to run the app: our hosting and file storage, Stripe for payments, our email provider for codes, reminders and alerts, Twilio for text reminders if you turn them on, and Expo for push notifications. We don't sell data and don't use advertising trackers.",
        },
        {
          icon: "clock",
          title: "What we delete automatically",
          body: "Notifications after 90 days; anonymous usage statistics (which never record who you are) after 90 days; photos and files you've replaced or no longer use within a day; sign-in codes as soon as they expire; reminder records after 30 days; reviewed safety checks on messages after a year.",
        },
        {
          icon: "trash-2",
          title: "Deleting your account",
          body: "Delete your account any time in Profile. Your profile, messages, photos and documents are removed and upcoming sessions are cancelled. We keep records of past paid sessions without your name, for accounting, and US tutors' W-9 forms for 4 years because the law requires it.",
        },
        {
          icon: "mail",
          title: "Questions or requests",
          body: "To see, correct or export your data, or with any privacy question, email help@babybabel.co.",
        },
      ]}
    />
  );
}
