// Outside websites listed on the Resources page (/resources). Babybabel isn't affiliated with any
// of them. To add one, copy an entry and fill in the fields; links must start with https://.
// - group: the heading the link sits under. Links with the same group are shown together, in the
//   order they appear here.
// - icon: a Feather icon name for the group (see https://feathericons.com). The first link in a
//   group sets it.
// - featured: shows the link as a larger highlighted card at the top of the page.
// Keep descriptions to one or two sentences.

export interface Resource {
  title: string;
  url: string;
  description: string;
  group: string;
  icon?: string;
  featured?: boolean;
}

export const RESOURCES: Resource[] = [
  {
    group: "Easy Lessons for any child!",
    icon: "play-circle",
    featured: true,
    title: "Lingopie",
    url: "https://try.lingopie.com/",
    description:
      "Learn to love a new story in any language you want to learn. Subtitles can increase learning comprehension, and tie reading to writing.",
  },
  {
    group: "Raising bilingual children",
    icon: "heart",
    title: "HealthyChildren.org",
    url: "https://www.healthychildren.org",
    description: "Parenting advice from the American Academy of Pediatrics, including how children learn to talk.",
  },
  {
    group: "Books and stories",
    icon: "book-open",
    title: "StoryWeaver",
    url: "https://storyweaver.org.in",
    description: "Free picture books for children in hundreds of languages, to read online or print.",
  },
  {
    group: "Languages of the world",
    icon: "globe",
    title: "Omniglot",
    url: "https://www.omniglot.com",
    description: "A free guide to the world's languages and writing systems, with useful phrases in each.",
  },
];
