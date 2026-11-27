// Babybabel design tokens — Airbnb-style, orange + papyrus
export const theme = {
  color: {
    surface: "#FAF8F5",
    onSurface: "#2C2421",
    surfaceSecondary: "#F2EAE0",
    onSurfaceSecondary: "#463A36",
    surfaceTertiary: "#E8DDD1",
    onSurfaceTertiary: "#5A4C46",
    surfaceInverse: "#2C2421",
    onSurfaceInverse: "#FAF8F5",
    brand: "#C8452D", // white text on it, and it on the page background, both pass WCAG AA (4.5:1)
    brandDark: "#B83A23",
    brandSoft: "#FBE0DB",
    onBrand: "#FFFFFF",
    success: "#3C7A57",
    warning: "#9C6A12",
    error: "#AF3F3F",
    border: "#E8DDD1",
    borderStrong: "#958372", // 3:1 against the page, so form fields and chips are easy to see
    muted: "#6F6059",
  },
  space: {
    xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48,
  },
  radius: {
    sm: 6, md: 12, lg: 20, pill: 999,
  },
  font: {
    sm: 13, base: 14, lg: 16, xl: 20, "2xl": 24, "3xl": 32,
  },
} as const;
