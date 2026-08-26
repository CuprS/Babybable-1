import { LandingPage } from "@/src/landing";

export default function Mission() {
  return (
    <LandingPage
      testID="mission-screen"
      eyebrow="Our story"
      title="Our mission"
      heroImage="https://images.unsplash.com/photo-1583468982228-19f19164aee2?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"
      intro="At Babybabel we are dedicated to changing childcare. We want to work with parents, educators, and language learners to provide better education to our youth, more peace of mind to parents, and more freedom to educators."
      sections={[
        {
          icon: "book-open",
          title: "Language learning is child's play",
          body: "Combining childcare and language learning is easy, and fruitful for your child. Something as simple as a translated cartoon, or a short story once a day can change their perception forever.",
        },
        {
          icon: "sun",
          title: "Fixing the poverty of the stimulus",
          body: "In the world around us today we see a poverty of the stimulus — to borrow an old and archaic term — and fixing this can be simple, cheap, and flexible to every community.",
        },
        {
          icon: "heart",
          title: "Short sessions, big impact",
          body: "Providing tutors for short sessions on the weekends helps children grow fond of learning, and shows them slices of life they would otherwise miss.",
        },
        {
          icon: "globe",
          title: "Keeping languages alive",
          body: "And providing sustained lessons can even keep languages alive and changing.",
        },
      ]}
    />
  );
}
