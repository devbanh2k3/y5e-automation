import { loadFont as loadBeVietnamPro } from "@remotion/google-fonts/BeVietnamPro";
import { loadFont as loadNotoSansJP } from "@remotion/google-fonts/NotoSansJP";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";

// Load Vietnamese font
const beVietnamPro = loadBeVietnamPro("normal", {
  weights: ["500", "700", "900"],
  subsets: ["vietnamese", "latin"],
});

// Load Japanese font (Noto Sans JP only has 'latin' subset in @remotion/google-fonts)
const notoSansJP = loadNotoSansJP("normal", {
  weights: ["700", "900"],
  subsets: ["latin"],
});

// Load English font
const inter = loadInter("normal", {
  weights: ["500", "700", "900"],
  subsets: ["latin"],
});

const FONT_MAP: Record<"vi" | "ja" | "en", { fontFamily: string }> = {
  vi: beVietnamPro,
  ja: notoSansJP,
  en: inter,
};

/**
 * Get the CSS font-family string for the given language.
 */
export function getFontFamily(language: "vi" | "ja" | "en"): string {
  return FONT_MAP[language].fontFamily;
}

/**
 * Get a full font-style object ready for use in React style props.
 */
export function getFontStyle(language: "vi" | "ja" | "en") {
  return {
    fontFamily: getFontFamily(language),
    WebkitFontSmoothing: "antialiased" as const,
    MozOsxFontSmoothing: "grayscale" as const,
  };
}
