import { LandingPage } from "@/src/landing";

export default function Privacy() {
  return (
    <LandingPage
      testID="privacy-screen"
      eyebrow="Legal"
      title="Privacy Policy"
      intro="We built Babybabel around families, so we're honest about the data we collect and how we use it. This summary explains the essentials in plain language."
      sections={[
        { icon: "user", title: "What we collect", body: "Your name, email, role (parent or tutor), messages between users, bookings, and — if you're a tutor — the photos and accreditations you upload. Nothing more." },
        { icon: "lock", title: "How we store it", body: "Passwords are hashed with bcrypt. Session tokens live encrypted on your device. Uploaded images are stored in a managed object store, not on unknown third-party servers." },
        { icon: "credit-card", title: "Payments", body: "We use Stripe to process payments. We never see or store your full card number." },
        { icon: "share-2", title: "Who we share it with", body: "Nobody outside Babybabel, except Stripe for payments and the object storage provider for images. We don't sell your data. Ever." },
        { icon: "trash-2", title: "Delete your data", body: "Email help@babybabel.co and we'll erase your account, messages, and uploads within 30 days." },
        { icon: "info", title: "Kids' data", body: "Babybabel accounts are for adults. We do not store profiles for children directly; anything about your child stays inside your booking notes and messages with your tutor." },
      ]}
    />
  );
}
