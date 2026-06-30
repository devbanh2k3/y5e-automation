import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  Audio,
  Img,
  staticFile,
  Sequence,
  interpolate,
  Easing,
} from "remotion";
import type { VideoData } from "../types/video-data";
import { INTRO_DURATION_FRAMES, OUTRO_DURATION_FRAMES } from "../types/video-data";
import { slideInFromBottom, fadeIn, kenBurnsScale } from "../utils/animations";
import { getFontStyle } from "../utils/fonts";
import { Hexagon } from "../components/Hexagon";
import { Counter } from "../components/Counter";
import { ProgressBar } from "../components/ProgressBar";
import { Branding } from "../components/Branding";

/**
 * RankingVideo composition.
 *
 * Displays cards one at a time in full-screen layout, counting down from N to 1.
 * Each card slides in from the bottom with a counter animation for metrics.
 */
export const RankingVideo: React.FC<VideoData> = (props) => {
  const frame = useCurrentFrame();
  const { width, height, durationInFrames } = useVideoConfig();

  const {
    cards,
    subtitle,
    language,
    musicPath,
    logoPath,
    holdDurationFrames = 120,
    transitionDurationFrames = 15,
  } = props;

  const fontStyle = getFontStyle(language);
  const introEnd = INTRO_DURATION_FRAMES;
  const outroStart = durationInFrames - OUTRO_DURATION_FRAMES;

  const isIntro = frame < introEnd;
  const isOutro = frame >= outroStart;
  const isMain = !isIntro && !isOutro;

  const mainFrame = Math.max(0, frame - introEnd);
  const cycleLen = holdDurationFrames + transitionDurationFrames;

  // Current card index (countdown: cards are ordered N→1 in the data)
  const currentCardIndex = Math.min(
    Math.floor(mainFrame / cycleLen),
    cards.length - 1
  );
  const frameInCard = mainFrame - currentCardIndex * cycleLen;

  // Ranking display number (countdown from total to 1)
  const rankNumber = cards.length - currentCardIndex;

  const currentCard = cards[currentCardIndex];

  // Slide-in animation for each new card
  const slideY = slideInFromBottom(frameInCard, 0, 18, 120);
  const cardOpacity = fadeIn(frameInCard, 0, 12);

  // Ken Burns on the image
  const kbScale = kenBurnsScale(mainFrame, currentCardIndex * cycleLen, holdDurationFrames);

  // Rank number scale-in
  const rankScale = interpolate(frameInCard, [0, 15], [2.5, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.back(2)),
  });
  const rankOpacity = interpolate(frameInCard, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Parse numeric value from statusText for counter animation (e.g. "IQ: 90" → 90)
  const numericMatch = currentCard?.statusText.match(/[\d,]+/);
  const metricValue = numericMatch
    ? parseInt(numericMatch[0].replace(/,/g, ""), 10)
    : 0;

  return (
    <div
      style={{
        width,
        height,
        backgroundColor: "#0a0a0a",
        overflow: "hidden",
        position: "relative",
        ...fontStyle,
      }}
    >
      {/* Background music */}
      {musicPath && <Audio src={staticFile(musicPath)} volume={0.3} loop />}

      {/* ─── INTRO ─── */}
      {isIntro && (
        <Sequence from={0} durationInFrames={introEnd}>
          <Branding logoPath={logoPath} phase="intro" />
        </Sequence>
      )}

      {/* ─── MAIN ─── */}
      {isMain && currentCard && (
        <>
          {/* Full-screen background image */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              overflow: "hidden",
            }}
          >
            <Img
              src={staticFile(currentCard.imagePath)}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                transform: `scale(${kbScale})`,
                filter: "brightness(0.35) blur(2px)",
                backfaceVisibility: "hidden",
              }}
            />
          </div>

          {/* Dark overlay */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "linear-gradient(to bottom, rgba(0,0,0,0.3) 0%, rgba(0,0,0,0.7) 100%)",
            }}
          />

          {/* Top banner */}
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              height: 72,
              backgroundColor: "rgba(229, 45, 39, 0.95)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 20,
            }}
          >
            <div
              style={{
                fontSize: 28,
                fontWeight: 900,
                color: "#ffffff",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              {subtitle}
            </div>
          </div>

          {/* Card content — slides in from bottom */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              opacity: cardOpacity,
              transform: `translateY(${slideY}px)`,
              backfaceVisibility: "hidden",
            }}
          >
            <div
              style={{
                display: "flex",
                gap: 60,
                alignItems: "center",
                maxWidth: 1600,
                padding: "0 80px",
              }}
            >
              {/* Left: rank number + image */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 24,
                  flexShrink: 0,
                }}
              >
                {/* Big rank number */}
                <div
                  style={{
                    opacity: rankOpacity,
                    transform: `scale(${Math.round(rankScale * 100) / 100})`,
                    backfaceVisibility: "hidden",
                  }}
                >
                  <Hexagon text={`#${rankNumber}`} size={100} />
                </div>

                {/* Card image */}
                <div
                  style={{
                    width: 480,
                    height: 360,
                    borderRadius: 16,
                    overflow: "hidden",
                    border: "3px solid rgba(229,45,39,0.6)",
                    boxShadow: "0 12px 40px rgba(0,0,0,0.5)",
                  }}
                >
                  <Img
                    src={staticFile(currentCard.imagePath)}
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "cover",
                      transform: `scale(${kbScale})`,
                      backfaceVisibility: "hidden",
                    }}
                  />
                </div>
              </div>

              {/* Right: text content */}
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  gap: 20,
                }}
              >
                {/* Header label */}
                <div
                  style={{
                    fontSize: 20,
                    fontWeight: 700,
                    color: "#e52d27",
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                  }}
                >
                  {currentCard.header}
                </div>

                {/* Title */}
                <div
                  style={{
                    fontSize: 48,
                    fontWeight: 900,
                    color: "#ffffff",
                    lineHeight: 1.15,
                    letterSpacing: "-0.01em",
                    textShadow: "0 2px 8px rgba(0,0,0,0.5)",
                  }}
                >
                  {currentCard.title}
                </div>

                {/* Description */}
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 500,
                    color: "rgba(255,255,255,0.8)",
                    lineHeight: 1.6,
                    maxWidth: 700,
                  }}
                >
                  {currentCard.description}
                </div>

                {/* Metric counter */}
                <div
                  style={{
                    marginTop: 12,
                    padding: "16px 28px",
                    backgroundColor: "rgba(0,0,0,0.6)",
                    borderRadius: 12,
                    borderLeft: "4px solid #e52d27",
                    alignSelf: "flex-start",
                  }}
                >
                  <Counter
                    from={0}
                    to={metricValue}
                    startFrame={currentCardIndex * cycleLen + introEnd}
                    duration={40}
                    suffix=""
                    prefix={currentCard.statusText.replace(/[\d,]+.*$/, "")}
                    fontSize={36}
                    color="#e52d27"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Progress bar */}
          <div
            style={{
              position: "absolute",
              bottom: 24,
              left: 60,
              right: 60,
              zIndex: 20,
            }}
          >
            <ProgressBar
              current={currentCardIndex + 1}
              total={cards.length}
              label={`RANK ${rankNumber}`}
            />
          </div>

          {/* Watermark */}
          <Branding logoPath={logoPath} phase="main" />
        </>
      )}

      {/* ─── OUTRO ─── */}
      {isOutro && (
        <Sequence from={outroStart} durationInFrames={OUTRO_DURATION_FRAMES}>
          <Branding logoPath={logoPath} phase="outro" />
        </Sequence>
      )}
    </div>
  );
};
