import React from "react";
import { useCurrentFrame, interpolate, Easing } from "remotion";

interface SubtitlesProps {
  text: string;
  visible: boolean;
  fontSize?: number;
}

/**
 * Section text overlay at the bottom of the screen.
 * Semi-transparent black background with fade in/out animation.
 */
export const Subtitles: React.FC<SubtitlesProps> = ({
  text,
  visible,
  fontSize = 36,
}) => {
  const frame = useCurrentFrame();
  const fadeDuration = 8; // frames for fade animation

  const opacity = visible
    ? interpolate(frame % 150, [0, fadeDuration], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.out(Easing.cubic),
      })
    : 0;

  if (!visible || opacity <= 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        bottom: 60,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        opacity,
        zIndex: 50,
      }}
    >
      <div
        style={{
          backgroundColor: "rgba(0, 0, 0, 0.75)",
          backdropFilter: "blur(8px)",
          borderRadius: 12,
          padding: "16px 40px",
          maxWidth: 1600,
        }}
      >
        <div
          style={{
            fontSize,
            fontWeight: 700,
            color: "#ffffff",
            textAlign: "center",
            lineHeight: 1.4,
            WebkitFontSmoothing: "antialiased",
            textShadow: "0 2px 4px rgba(0,0,0,0.5)",
          }}
        >
          {text}
        </div>
      </div>
    </div>
  );
};
