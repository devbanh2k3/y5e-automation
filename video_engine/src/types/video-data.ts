export interface CardData {
  /** Header label, e.g. "NGÀY 10", "RANK 15" */
  header: string;
  /** Bold title text */
  title: string;
  /** Description paragraph */
  description: string;
  /** Path to real image file (relative to public/) */
  imagePath: string;
  /** Status/metric text, e.g. "IQ TRUNG BÌNH: 90" */
  statusText: string;
}

export interface IntroCard {
  /** Main hook text */
  text: string;
  /** Sub text */
  subtext: string;
  /** Background image path */
  imagePath?: string;
}

export interface SfxPaths {
  transition: string;
  alert: string;
  reveal: string;
}

export interface VideoData {
  /** Which composition template to use */
  template: "timeline" | "ranking" | "comparison";
  /** Video title */
  title: string;
  /** Top banner text */
  subtitle: string;
  /** Language for font selection */
  language: "vi" | "ja" | "en";
  /** Array of cards to render */
  cards: CardData[];
  /** Intro hook cards (shown before scroll) */
  introCards?: IntroCard[];
  /** Background music file path (relative to public/) */
  musicPath: string;
  /** Sound effect paths */
  sfxPaths: SfxPaths;
  /** Logo image path (relative to public/) */
  logoPath: string;
  /** How many frames each card is held on-screen (default: 120 = 4s at 30fps) */
  holdDurationFrames: number;
  /** Transition animation length in frames (default: 15 = 0.5s at 30fps) */
  transitionDurationFrames: number;
}

/** Durations for intro/outro phases in frames at 30fps */
export const INTRO_DURATION_FRAMES = 90; // 3 seconds
export const OUTRO_DURATION_FRAMES = 150; // 5 seconds

/**
 * Calculate the total duration of a video in frames.
 * total = intro + (cards × (hold + transition)) + outro
 */
export function calculateTotalDuration(data: VideoData): number {
  const cardCount = data.cards.length;
  const hold = data.holdDurationFrames || 120;
  const transition = data.transitionDurationFrames || 15;
  const mainDuration = cardCount * hold + Math.max(0, cardCount - 1) * transition;
  return INTRO_DURATION_FRAMES + mainDuration + OUTRO_DURATION_FRAMES;
}
