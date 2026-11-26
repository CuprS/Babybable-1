import { LandingPage } from "@/src/landing";

// Plain-language terms that match what the app actually enforces (see backend/booking_service.py
// and routes/bookings.py). Have a lawyer review this before launch.
export default function Terms() {
  return (
    <LandingPage
      testID="terms-screen"
      eyebrow="Legal"
      title="Terms of Service"
      intro="These terms explain how Babybabel works for families and tutors. By creating an account or making a booking you agree to them. If anything is unclear, email help@babybabel.co."
      sections={[
        {
          icon: "users",
          title: "Who can use Babybabel",
          body: "Accounts are for adults (18+). Families book sessions; tutors offer them. Children never have their own accounts — a parent manages everything.",
        },
        {
          icon: "shield",
          title: "Tutor verification",
          body: "Before a tutor can be booked, they must upload a photo ID and a recent background-check certificate, and our team must approve them. Verified tutors show a ✔ Verified badge. Verification lowers risk but isn't a guarantee — parents remain responsible for their children's care.",
        },
        {
          icon: "dollar-sign",
          title: "Prices and fees",
          body: "Tutors set their own hourly rate and keep 100% of it. Families pay the tutor's rate plus a 1% Babybabel platform fee, shown before you pay. Payments are processed by Stripe.",
        },
        {
          icon: "calendar",
          title: "Booking requests",
          body: "A booking is a request until the tutor accepts it. Tutors have 24 hours to accept or decline; if they decline or don't answer, the family is refunded in full. Unpaid bookings are released after 30 minutes. Lessons a tutor offers in chat count as already accepted.",
        },
        {
          icon: "x-circle",
          title: "Cancellations and refunds",
          body: "Families who cancel at least 24 hours before the start get a full refund; later cancellations by a family aren't refunded. If the tutor cancels, the family always gets a full refund, including the platform fee.",
        },
        {
          icon: "repeat",
          title: "Rescheduling",
          body: "Either side can move a session to another free time up to 24 hours before it starts. After that, message each other to agree a change.",
        },
        {
          icon: "message-circle",
          title: "Behaviour and safety",
          body: "Be respectful. No harassment, spam, fake profiles or contact that puts a child at risk. Anyone can block and report another user; accounts reported by several people are paused while our team reviews them, and we may close accounts that break these terms.",
        },
        {
          icon: "star",
          title: "Reviews",
          body: "Only families who had a paid session can review it, once per session. Reviews must be honest and about the session.",
        },
        {
          icon: "file-text",
          title: "Tutors' taxes",
          body: "Tutors are independent and responsible for their own taxes. US tutors are asked for a W-9 after their first completed session so we can report payments as the law requires.",
        },
        {
          icon: "trash-2",
          title: "Closing your account",
          body: "You can delete your account any time from your Profile. See the Privacy Policy for what is removed and what we must keep.",
        },
        {
          icon: "info",
          title: "Changes",
          body: "We may update these terms; we'll tell you in the app before important changes take effect.",
        },
      ]}
    />
  );
}
