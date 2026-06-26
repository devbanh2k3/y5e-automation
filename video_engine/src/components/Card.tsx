import React from "react";
import { Img, staticFile, useCurrentFrame } from "remotion";
import type { CardData } from "../types/video-data";
import { Hexagon } from "./Hexagon";
import { kenBurnsScale } from "../utils/animations";

interface CardProps extends CardData {
  isActive: boolean;
  language?: "vi" | "ja" | "en";
  /** Global frame for Ken Burns */
  globalFrame?: number;
  /** When this card became active (for Ken Burns start) */
  activeStartFrame?: number;
}

export const CARD_WIDTH = 600;
export const CARD_HEIGHT = 1080;

/**
 * Timeline card component sized for 1920×1080.
 *
 * Layout (top to bottom):
 *   1. Hexagon header badge (red)
 *   2. Image with Ken Burns zoom (500px)
 *   3. Title (white background, bold, 28px)
 *   4. Description (dark background, flex remaining)
 *   5. Status bar (black background, red text)
 *
 * Full height 1080px, no border, no border-radius, no scale transform.
 */
export const Card: React.FC<CardProps> = ({
  header,
  title,
  description,
  imagePath,
  statusText,
  isActive,
  globalFrame = 0,
  activeStartFrame = 0,
}) => {
  const frame = useCurrentFrame();
  const effectiveFrame = globalFrame || frame;

  // Ken Burns: slow zoom while card is displayed
  const kbScale = kenBurnsScale(effectiveFrame, activeStartFrame, 180);

  return (
    <div
      style={{
        width: CARD_WIDTH,
        height: CARD_HEIGHT,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "#1a1a1a",
        flexShrink: 0,
        backfaceVisibility: "hidden",
        WebkitFontSmoothing: "antialiased",
      }}
    >
      {/* 1. Header Banner — timeline marker */}
      <div
        style={{
          height: 120,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(180deg, #e52d27 0%, #b91d18 100%)",
          position: "relative",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 36,
            fontWeight: 900,
            color: "#ffffff",
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            textShadow: "0 2px 8px rgba(0,0,0,0.4)",
          }}
        >
          {header}
        </div>
      </div>

      {/* 2. Image with Ken Burns */}
      <div
        style={{
          height: 500,
          overflow: "hidden",
          position: "relative",
          backgroundColor: "#111",
          flexShrink: 0,
        }}
      >
        <Img
          src={staticFile(imagePath)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${kbScale})`,
            backfaceVisibility: "hidden",
          }}
        />
        {/* Subtle gradient overlay at bottom of image */}
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 60,
            background:
              "linear-gradient(transparent, rgba(0,0,0,0.6))",
          }}
        />
      </div>

      {/* 3. Title */}
      <div
        style={{
          padding: "16px 20px 12px",
          backgroundColor: "#ffffff",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 28,
            fontWeight: 900,
            color: "#111111",
            lineHeight: 1.2,
            letterSpacing: "-0.01em",
            WebkitFontSmoothing: "antialiased",
          }}
        >
          {title}
        </div>
      </div>

      {/* 4. Description */}
      <div
        style={{
          flex: 1,
          padding: "12px 20px",
          backgroundColor: "#222222",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            fontSize: 22,
            fontWeight: 500,
            color: "rgba(255,255,255,0.9)",
            lineHeight: 1.55,
            WebkitFontSmoothing: "antialiased",
          }}
        >
          {description}
        </div>
      </div>

      {/* 5. Status bar — metric/data */}
      <div
        style={{
          height: 80,
          backgroundColor: "#000000",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 20px",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 24,
            fontWeight: 900,
            color: "#e52d27",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            WebkitFontSmoothing: "antialiased",
          }}
        >
          {statusText}
        </div>
      </div>
    </div>
  );
};
