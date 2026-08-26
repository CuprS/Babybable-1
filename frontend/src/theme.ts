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
    brand: "#ED6249",
    brandDark: "#B83A23",
    brandSoft: "#FBE0DB",
    onBrand: "#FFFFFF",
    success: "#448962",
    warning: "#D79A2A",
    error: "#CC4141",
    border: "#E8DDD1",
    borderStrong: "#C5B29F",
    muted: "#8A7A72",
  },
  space: {
    xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48,
  },
  radius: {
    sm: 6, md: 12, lg: 20, pill: 999,
  },
  font: {
    sm: 12, base: 14, lg: 16, xl: 20, "2xl": 24, "3xl": 32,
  },
} as const;
