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
import type { VideoData, CardData } from "../types/video-data";
import { INTRO_DURATION_FRAMES, OUTRO_DURATION_FRAMES } from "../types/video-data";
import { fadeIn, kenBurnsScale } from "../utils/animations";
import { getFontStyle } from "../utils/fonts";
import { VsOverlay } from "../components/VsOverlay";
import { ProgressBar } from "../components/ProgressBar";
import { Branding } from "../components/Branding";

/**
 * ComparisonVideo composition.
 *
 * Split-screen layout: left panel vs right panel.
 * VsOverlay in center. Animated metric bars grow to show comparison.
 * Cards are consumed in pairs (0 vs 1, 2 vs 3, etc.).
 */
export const ComparisonVideo: React.FC<VideoData> = (props) => {
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

  // Group cards into pairs for comparison
  const pairs: [CardData, CardData][] = [];
  for (let i = 0; i < cards.length - 1; i += 2) {
    pairs.push([cards[i], cards[i + 1]]);
  }

  const mainFrame = Math.max(0, frame - introEnd);
  const cycleLen = holdDurationFrames + transitionDurationFrames;

  const currentPairIndex = Math.min(
    Math.floor(mainFrame / cycleLen),
    pairs.length - 1
  );
  const frameInPair = mainFrame - currentPairIndex * cycleLen;

  const [leftCard, rightCard] = pairs[currentPairIndex] ?? [
    cards[0],
    cards[1] ?? cards[0],
  ];

  // Alternating focus: first half zoom left, second half zoom right
  const halfHold = holdDurationFrames / 2;
  const isLeftFocus = frameInPair < halfHold;

  // Panel scale for focus effect
  const leftScale = isLeftFocus
    ? interpolate(frameInPair, [0, 20], [1, 1.04], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.out(Easing.cubic),
      })
    : interpolate(frameInPair, [halfHold, halfHold + 20], [1.04, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.out(Easing.cubic),
      });

  const rightScale = !isLeftFocus
    ? interpolate(frameInPair, [halfHold, halfHold + 20], [1, 1.04], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.out(Easing.cubic),
      })
    : interpolate(frameInPair, [0, 20], [1.04, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.out(Easing.cubic),
      });

  // Panel brightness for focus
  const leftBrightness = isLeftFocus ? 1.0 : 0.6;
  const rightBrightness = !isLeftFocus ? 1.0 : 0.6;

  // Slide-in for pair transitions
  const pairOpacity = fadeIn(frameInPair, 0, 12);

  // Metric bar animation
  const barProgress = interpolate(frameInPair, [15, 60], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // Parse numeric values for comparison bars
  const parseMetric = (card: CardData): number => {
    const match = card.statusText.match(/[\d,]+/);
    return match ? parseInt(match[0].replace(/,/g, ""), 10) : 50;
  };
  const leftMetric = parseMetric(leftCard);
  const rightMetric = parseMetric(rightCard);
  const maxMetric = Math.max(leftMetric, rightMetric, 1);

  // Ken Burns
  const kbScale = kenBurnsScale(mainFrame, currentPairIndex * cycleLen, holdDurationFrames);

  const panelWidth = width / 2 - 50; // leave room for VS overlay

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
      {musicPath && <Audio src={staticFile(musicPath)} volume={0.3} />}

      {/* ─── INTRO ─── */}
      {isIntro && (
        <Sequence from={0} durationInFrames={introEnd}>
          <Branding logoPath={logoPath} phase="intro" />
        </Sequence>
      )}

      {/* ─── MAIN ─── */}
      {isMain && leftCard && rightCard && (
        <>
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
              zIndex: 30,
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

          {/* Split screen container */}
          <div
            style={{
              position: "absolute",
              top: 72,
              left: 0,
              right: 0,
              bottom: 0,
              display: "flex",
              alignItems: "stretch",
              opacity: pairOpacity,
            }}
          >
            {/* Left panel */}
            <ComparisonPanel
              card={leftCard}
              side="left"
              panelWidth={panelWidth}
              scale={leftScale}
              brightness={leftBrightness}
              kbScale={kbScale}
              barProgress={barProgress}
              metricValue={leftMetric}
              maxMetric={maxMetric}
              accentColor="#2196f3"
            />

            {/* VS overlay — center */}
            <div
              style={{
                width: 100,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 25,
                flexShrink: 0,
              }}
            >
              <VsOverlay size={120} />
            </div>

            {/* Right panel */}
            <ComparisonPanel
              card={rightCard}
              side="right"
              panelWidth={panelWidth}
              scale={rightScale}
              brightness={rightBrightness}
              kbScale={kbScale}
              barProgress={barProgress}
              metricValue={rightMetric}
              maxMetric={maxMetric}
              accentColor="#e52d27"
            />
          </div>

          {/* Progress bar */}
          <div
            style={{
              position: "absolute",
              bottom: 20,
              left: 60,
              right: 60,
              zIndex: 30,
            }}
          >
            <ProgressBar
              current={currentPairIndex + 1}
              total={pairs.length}
              label={`MATCH ${currentPairIndex + 1} / ${pairs.length}`}
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

/* ─── Comparison Panel Sub-component ─── */

interface ComparisonPanelProps {
  card: CardData;
  side: "left" | "right";
  panelWidth: number;
  scale: number;
  brightness: number;
  kbScale: number;
  barProgress: number;
  metricValue: number;
  maxMetric: number;
  accentColor: string;
}

const ComparisonPanel: React.FC<ComparisonPanelProps> = ({
  card,
  side,
  panelWidth,
  scale,
  brightness,
  kbScale,
  barProgress,
  metricValue,
  maxMetric,
  accentColor,
}) => {
  const barWidthPercent = Math.round((metricValue / maxMetric) * 100 * barProgress);

  return (
    <div
      style={{
        flex: 1,
        position: "relative",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        transform: `scale(${Math.round(scale * 1000) / 1000})`,
        transformOrigin: side === "left" ? "right center" : "left center",
        backfaceVisibility: "hidden",
      }}
    >
      {/* Background image */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          overflow: "hidden",
        }}
      >
        <Img
          src={staticFile(card.imagePath)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${kbScale})`,
            filter: `brightness(${brightness})`,
            backfaceVisibility: "hidden",
          }}
        />
        {/* Gradient overlay */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.2) 50%, rgba(0,0,0,0.4) 100%)",
          }}
        />
      </div>

      {/* Content overlay */}
      <div
        style={{
          position: "relative",
          zIndex: 5,
          flex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          padding: "40px 36px",
          gap: 16,
        }}
      >
        {/* Header badge */}
        <div
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: accentColor,
            textTransform: "uppercase",
            letterSpacing: "0.12em",
          }}
        >
          {card.header}
        </div>

        {/* Title */}
        <div
          style={{
            fontSize: 36,
            fontWeight: 900,
            color: "#ffffff",
            lineHeight: 1.15,
            textShadow: "0 2px 8px rgba(0,0,0,0.7)",
          }}
        >
          {card.title}
        </div>

        {/* Description */}
        <div
          style={{
            fontSize: 18,
            fontWeight: 500,
            color: "rgba(255,255,255,0.75)",
            lineHeight: 1.5,
            maxHeight: 120,
            overflow: "hidden",
          }}
        >
          {card.description}
        </div>

        {/* Metric bar */}
        <div style={{ marginTop: 12 }}>
          <div
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: "rgba(255,255,255,0.6)",
              marginBottom: 6,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            {card.statusText}
          </div>
          <div
            style={{
              width: "100%",
              height: 12,
              backgroundColor: "rgba(255,255,255,0.1)",
              borderRadius: 6,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${barWidthPercent}%`,
                height: "100%",
                backgroundColor: accentColor,
                borderRadius: 6,
                boxShadow: `0 0 12px ${accentColor}88`,
              }}
            />
          </div>
          <div
            style={{
              fontSize: 24,
              fontWeight: 900,
              color: accentColor,
              marginTop: 8,
            }}
          >
            {Math.round(metricValue * barProgress).toLocaleString("en-US")}
          </div>
        </div>
      </div>
    </div>
  );
};
