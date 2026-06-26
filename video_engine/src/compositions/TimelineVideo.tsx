import React from "react";
import { useCurrentFrame, useVideoConfig, Audio, Img, staticFile, Sequence, interpolate, Easing } from "remotion";
import type { VideoData } from "../types/video-data";
import { OUTRO_DURATION_FRAMES } from "../types/video-data";
import { continuousScroll } from "../utils/animations";
import { getFontStyle } from "../utils/fonts";
import { Card, CARD_WIDTH } from "../components/Card";
import { Branding } from "../components/Branding";

/**
 * TimelineVideo composition.
 *
 * Structure:
 *   [Hook: first 3 cards slide up centered] → [Morph: slide left + scroll continues from card 4] → [Main: scroll] → [Outro]
 *
 * - Hook: First 3 cards slide up from bottom, staggered, centered on screen
 * - Morph: 3 cards smoothly slide from center to left (scroll position), scroll starts
 * - Main: Continuous scroll — picks up from card 4 onwards (cards 1-3 scroll off left)
 */

const HOOK_CARDS = 3;
const HOOK_STAGGER = 45;       // 1.5s between each card appearing
const HOOK_SLIDE_IN = 60;      // 2s slide up animation (slow & smooth)
const HOOK_HOLD = 180;         // 6s hold after all visible
const MORPH_FRAMES = 30;       // 1s morph to scroll
// Total hook: 2×45 + 60 + 180 + 30 = 360 frames = 12s

export const TimelineVideo: React.FC<VideoData> = (props) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames } = useVideoConfig();

  const {
    cards,
    language,
    musicPath,
    logoPath,
  } = props;

  const fontStyle = getFontStyle(language);
  const CARD_GAP = 30;
  const CARD_SLOT_WIDTH = CARD_WIDTH + CARD_GAP;

  // Phase timing
  const hookCardCount = Math.min(HOOK_CARDS, cards.length);
  const hookAnimEnd = (hookCardCount - 1) * HOOK_STAGGER + HOOK_SLIDE_IN;
  const hookEnd = hookAnimEnd + HOOK_HOLD;
  const morphEnd = hookEnd + MORPH_FRAMES;
  const outroStart = durationInFrames - OUTRO_DURATION_FRAMES;

  // Phase detection
  const isHook = frame < hookEnd;
  const isMorph = frame >= hookEnd && frame < morphEnd;
  const isOutro = frame >= outroStart;
  const isMain = frame >= morphEnd && !isOutro;

  // Hook cards: centered position
  const hookTotalWidth = hookCardCount * CARD_WIDTH + (hookCardCount - 1) * CARD_GAP;
  const hookCenterX = (width - hookTotalWidth) / 2;

  // Scroll: starts from where hook cards are, then scrolls left
  // At scroll start (morphEnd), first 3 cards should be visible at left edge
  // Then scroll moves them off-screen left while revealing cards 4, 5, 6...
  const mainFrame = Math.max(0, frame - morphEnd);
  const mainDuration = outroStart - morphEnd;

  // Total scroll = enough to scroll all cards through
  // Start position: cards at x=0 (left edge). End: last card visible.
  const totalContentWidth = cards.length * CARD_SLOT_WIDTH;
  const totalScrollDistance = Math.max(0, totalContentWidth - width + CARD_GAP);

  const scrollOffset = continuousScroll(mainFrame, mainDuration, totalScrollDistance);

  // Morph progress: 0 (hook centered) → 1 (scroll left-aligned)
  const morphProgress = isMorph
    ? interpolate(frame, [hookEnd, morphEnd], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.inOut(Easing.ease),
      })
    : isMain ? 1 : 0;

  // During morph, each hook card slides from center position to scroll position (left edge)
  // After morph, scroll continues
  const getCardX = (index: number): number => {
    const scrollPos = index * CARD_SLOT_WIDTH - scrollOffset;
    if (isHook) {
      // Centered
      return hookCenterX + index * CARD_SLOT_WIDTH;
    }
    if (isMorph) {
      // Interpolate from centered to left-aligned (scroll start)
      const fromX = hookCenterX + index * CARD_SLOT_WIDTH;
      const toX = index * CARD_SLOT_WIDTH; // scroll position at offset 0
      return fromX + (toX - fromX) * morphProgress;
    }
    // Main: scroll position
    return scrollPos;
  };

  return (
    <div
      style={{
        width,
        height,
        backgroundColor: "#0d0d0d",
        overflow: "hidden",
        position: "relative",
        ...fontStyle,
      }}
    >
      {/* Background music */}
      {musicPath && (
        <Audio src={staticFile(musicPath)} volume={0.3} />
      )}

      {/* Dark gradient background */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "radial-gradient(ellipse at 50% 30%, #1a1a2e 0%, #0d0d0d 70%)",
        }}
      />

      {/* ─── ALL CARDS: unified rendering ─── */}
      {!isOutro && (
        <div style={{ position: "absolute", inset: 0 }}>
          {cards.map((card, index) => {
            // During hook: only show first 3 cards with slide-up
            if (isHook && index >= hookCardCount) return null;

            const cardX = getCardX(index);

            // Skip cards that are off-screen (optimization)
            if ((isMorph || isMain) && (cardX > width + CARD_WIDTH || cardX < -CARD_WIDTH)) {
              return null;
            }

            // Hook slide-up animation (only for first 3 cards during hook/morph)
            let slideY = 0;
            let cardOpacity = 1;

            if (isHook && index < hookCardCount) {
              const cardStart = index * HOOK_STAGGER;
              const localFrame = Math.max(0, frame - cardStart);

              slideY = interpolate(
                localFrame,
                [0, HOOK_SLIDE_IN],
                [height * 0.5, 0],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
              );

              cardOpacity = interpolate(
                localFrame,
                [0, HOOK_SLIDE_IN * 0.5],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
              );
            }

            // Cards beyond first 3 fade in during morph
            if (isMorph && index >= hookCardCount) {
              cardOpacity = morphProgress;
            }

            return (
              <div
                key={index}
                style={{
                  position: "absolute",
                  left: Math.round(cardX),
                  top: 0,
                  width: CARD_WIDTH,
                  height: 1080,
                  opacity: cardOpacity,
                  transform: slideY !== 0 ? `translateY(${Math.round(slideY)}px)` : "translateY(0px)",
                  willChange: "transform, opacity",
                  backfaceVisibility: "hidden",
                }}
              >
                <Card
                  {...card}
                  isActive={false}
                  globalFrame={frame}
                  activeStartFrame={0}
                />
              </div>
            );
          })}
        </div>
      )}

      {/* Branding watermark — main phase only */}
      {isMain && <Branding logoPath={logoPath} phase="main" />}

      {/* ─── OUTRO PHASE ─── */}
      {isOutro && (
        <Sequence from={outroStart} durationInFrames={OUTRO_DURATION_FRAMES}>
          <Branding logoPath={logoPath} phase="outro" />
        </Sequence>
      )}
    </div>
  );
};
