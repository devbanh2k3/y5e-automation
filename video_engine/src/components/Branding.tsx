import React from "react";
import { useCurrentFrame, interpolate, Easing, Img, staticFile } from "remotion";

interface BrandingProps {
  logoPath: string;
  phase: "intro" | "main" | "outro";
  frame?: number;
}

/**
 * Branding elements for different video phases.
 * - Intro: 3-second logo animation (scale up + fade in)
 * - Main: Small logo watermark bottom-right (10% opacity)
 * - Outro: Subscribe CTA card (5 seconds)
 */
export const Branding: React.FC<BrandingProps> = ({
  logoPath,
  phase,
}) => {
  const frame = useCurrentFrame();

  if (phase === "intro") {
    return <IntroLogo logoPath={logoPath} frame={frame} />;
  }

  if (phase === "main") {
    return <WatermarkLogo logoPath={logoPath} />;
  }

  return <OutroCTA logoPath={logoPath} frame={frame} />;
};

/* ─── Intro: 90 frames (3s) logo reveal ─── */
function IntroLogo({ logoPath, frame }: { logoPath: string; frame: number }) {
  const opacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const scale = interpolate(frame, [0, 25], [0.6, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.back(1.6)),
  });

  // Fade out near the end of intro
  const fadeOut = interpolate(frame, [70, 90], [1, 0], {
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
        opacity: opacity * fadeOut,
        zIndex: 100,
      }}
    >
      <div
        style={{
          transform: `scale(${Math.round(scale * 1000) / 1000})`,
          backfaceVisibility: "hidden",
        }}
      >
        <Img
          src={staticFile(logoPath)}
          style={{
            width: 240,
            height: 240,
            objectFit: "contain",
          }}
        />
      </div>
      <div
        style={{
          marginTop: 30,
          fontSize: 28,
          fontWeight: 700,
          color: "rgba(255,255,255,0.7)",
          letterSpacing: "0.15em",
          textTransform: "uppercase",
          opacity: interpolate(frame, [15, 35], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        PRESENTS
      </div>
    </div>
  );
}

/* ─── Main: watermark ─── */
function WatermarkLogo({ logoPath }: { logoPath: string }) {
  return (
    <div
      style={{
        position: "absolute",
        bottom: 30,
        right: 30,
        opacity: 0.1,
        zIndex: 10,
      }}
    >
      <Img
        src={staticFile(logoPath)}
        style={{
          width: 80,
          height: 80,
          objectFit: "contain",
        }}
      />
    </div>
  );
}

/* ─── Outro: 150 frames (5s) subscribe CTA ─── */
function OutroCTA({ logoPath, frame }: { logoPath: string; frame: number }) {
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
        <Img
          src={staticFile(logoPath)}
          style={{ width: 120, height: 120, objectFit: "contain" }}
        />

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
