import { interpolate, Easing } from "remotion";

/**
 * Snap-scroll position calculator.
 *
 * The scroll timeline works like this:
 *   - Card 0 is held for `holdFrames`
 *   - Then a smooth transition of `transitionFrames` moves to card 1
 *   - Card 1 is held for `holdFrames`
 *   - ... and so on
 *
 * Returns a fractional card index (e.g. 0.0 → 0.99 → 1.0 → 1.0 → 1.0 → 1.99 → 2.0)
 */
export function snapScrollPosition(
  frame: number,
  holdFrames: number,
  transitionFrames: number,
  totalCards: number
): number {
  if (totalCards <= 1) return 0;

  const cycleLength = holdFrames + transitionFrames;
  const totalScrollFrames = (totalCards - 1) * cycleLength + holdFrames;

  // Clamp frame to valid range
  const f = Math.max(0, Math.min(frame, totalScrollFrames - 1));

  // Determine which cycle we're in
  const cycleIndex = Math.floor(f / cycleLength);
  const frameInCycle = f - cycleIndex * cycleLength;

  if (cycleIndex >= totalCards - 1) {
    // We're on the last card, just hold
    return totalCards - 1;
  }

  if (frameInCycle < holdFrames) {
    // In the hold phase — stay on current card
    return cycleIndex;
  }

  // In the transition phase — smoothly interpolate to next card
  const transitionProgress = interpolate(
    frameInCycle - holdFrames,
    [0, transitionFrames],
    [0, 1],
    {
      easing: Easing.inOut(Easing.cubic),
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }
  );

  return cycleIndex + transitionProgress;
}

/**
 * Ken Burns scale effect.
 * Smoothly scales from 1.0 to 1.08 over the given duration.
 */
export function kenBurnsScale(
  frame: number,
  startFrame: number,
  duration: number
): number {
  const scale = interpolate(frame - startFrame, [0, duration], [1.0, 1.08], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.linear,
  });
  return Math.round(scale * 10000) / 10000;
}

/**
 * Fade-in helper: 0→1 over `duration` frames starting at `startFrame`.
 */
export function fadeIn(
  frame: number,
  startFrame: number,
  duration: number
): number {
  return interpolate(frame - startFrame, [0, duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
}

/**
 * Fade-out helper: 1→0 over `duration` frames starting at `startFrame`.
 */
export function fadeOut(
  frame: number,
  startFrame: number,
  duration: number
): number {
  return interpolate(frame - startFrame, [0, duration], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.in(Easing.cubic),
  });
}

/**
 * Slide-in from bottom: returns translateY value in px.
 * Goes from `distance` to 0 over `duration` frames.
 */
export function slideInFromBottom(
  frame: number,
  startFrame: number,
  duration: number,
  distance: number = 200
): number {
  const y = interpolate(frame - startFrame, [0, duration], [distance, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.back(1.4)),
  });
  return Math.round(y);
}

/**
 * Pulse animation: returns a scale value that pulses between 1.0 and maxScale.
 */
export function pulse(
  frame: number,
  frequency: number = 0.05,
  maxScale: number = 1.15
): number {
  const t = Math.sin(frame * frequency * Math.PI * 2) * 0.5 + 0.5;
  return 1.0 + t * (maxScale - 1.0);
}

/**
 * Get the active card index (integer) from a fractional scroll position.
 */
export function getActiveCardIndex(scrollPosition: number): number {
  return Math.round(scrollPosition);
}

/**
 * Continuous smooth scroll.
 * Returns a pixel offset that linearly moves from 0 to totalScrollDistance
 * over the given totalFrames. No stopping, no snapping — pure linear motion.
 */
export function continuousScroll(
  frame: number,
  totalFrames: number,
  totalScrollDistance: number
): number {
  const progress = interpolate(frame, [0, totalFrames], [0, totalScrollDistance], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.linear,
  });
  return Math.round(progress);
}
