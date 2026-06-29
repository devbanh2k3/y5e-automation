import React from "react";
import { useCurrentFrame, interpolate, Easing } from "remotion";

interface BrandingProps {
  logoPath: string;
  phase: "intro" | "main" | "outro";
  frame?: number;
}

/**
 * Branding elements for different video phases.
 * - Intro/Main: no channel logo or watermark
 * - Outro: Subscribe CTA card (5 seconds)
 */
export const Branding: React.FC<BrandingProps> = ({
  logoPath,
  phase,
}) => {
  const frame = useCurrentFrame();

  if (phase === "intro") {
    return null;
  }

  if (phase === "main") {
    return null;
  }

  return <OutroCTA frame={frame} />;
};

/* ─── Outro: 150 frames (5s) subscribe CTA ─── */
function OutroCTA({ frame }: { frame: number }) {
  const cardOpacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const cardScale = interpolate(frame, [0, 25], [0.8, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.back(1.3)),
  });

  const buttonOpacity = interpolate(frame, [30, 50], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Pulsing subscribe button
  const pulseScale =
    frame > 50
      ? 1 + Math.sin((frame - 50) * 0.12) * 0.04
      : 1;

  // Fade out at end
  const fadeOut = interpolate(frame, [130, 150], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#0a0a0a",
        opacity: fadeOut,
        zIndex: 100,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 30,
          opacity: cardOpacity,
          transform: `scale(${Math.round(cardScale * 1000) / 1000})`,
          backfaceVisibility: "hidden",
        }}
      >
        <div
          style={{
            fontSize: 52,
            fontWeight: 900,
            color: "#ffffff",
            textAlign: "center",
            letterSpacing: "-0.01em",
          }}
        >
          Thanks for watching!
        </div>

        <div
          style={{
            fontSize: 24,
            color: "rgba(255,255,255,0.6)",
            textAlign: "center",
          }}
        >
          Like & Subscribe for more content
        </div>

        {/* Subscribe button */}
        <div
          style={{
            opacity: buttonOpacity,
            transform: `scale(${Math.round(pulseScale * 1000) / 1000})`,
            backfaceVisibility: "hidden",
          }}
        >
          <div
            style={{
              backgroundColor: "#e52d27",
              color: "#ffffff",
              fontSize: 28,
              fontWeight: 900,
              padding: "18px 64px",
              borderRadius: 8,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              boxShadow: "0 4px 24px rgba(229,45,39,0.4)",
            }}
          >
            SUBSCRIBE
          </div>
        </div>
      </div>
    </div>
  );
}
