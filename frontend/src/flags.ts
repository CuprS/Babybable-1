// Best-effort Unicode flag map for the languages parents typically request.
const MAP: Record<string, string> = {
  spanish: "🇪🇸", french: "🇫🇷", mandarin: "🇨🇳", chinese: "🇨🇳",
  japanese: "🇯🇵", korean: "🇰🇷", german: "🇩🇪", italian: "🇮🇹",
  portuguese: "🇧🇷", arabic: "🇦🇪", russian: "🇷🇺", turkish: "🇹🇷",
  dutch: "🇳🇱", swedish: "🇸🇪", norwegian: "🇳🇴", danish: "🇩🇰",
  greek: "🇬🇷", polish: "🇵🇱", hebrew: "🇮🇱", hindi: "🇮🇳",
  bengali: "🇧🇩", tagalog: "🇵🇭", vietnamese: "🇻🇳", thai: "🇹🇭",
  english: "🇬🇧", ukrainian: "🇺🇦", czech: "🇨🇿", romanian: "🇷🇴",
  finnish: "🇫🇮", indonesian: "🇮🇩", malay: "🇲🇾", swahili: "🇰🇪",
  yoruba: "🇳🇬", zulu: "🇿🇦", basque: "🇪🇸", catalan: "🇪🇸",
};
export function flagFor(lang: string): string {
  return MAP[lang.trim().toLowerCase()] || "🌐";
}
