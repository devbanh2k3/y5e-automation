import React from "react";
import { useCurrentFrame } from "remotion";
import { pulse } from "../utils/animations";

interface VsOverlayProps {
  size?: number;
}

/**
 * Animated "VS" badge for comparison compositions.
 * Diamond/circle shape with pulse animation.
 */
export const VsOverlay: React.FC<VsOverlayProps> = ({ size = 140 }) => {
  const frame = useCurrentFrame();
  const scale = pulse(frame, 0.04, 1.12);

  // Rotating glow
  const glowAngle = Math.round(frame * 3) % 360;

  return (
    <div
      style={{
        position: "relative",
        width: size,
        height: size,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transform: `scale(${Math.round(scale * 1000) / 1000})`,
        backfaceVisibility: "hidden",
        zIndex: 30,
      }}
    >
      {/* Outer glow ring */}
      <div
        style={{
          position: "absolute",
          inset: -8,
          borderRadius: "50%",
          background: `conic-gradient(from ${glowAngle}deg, #e52d27, #ff6b35, #e52d27, #b71c1c, #e52d27)`,
          opacity: 0.6,
          filter: "blur(6px)",
        }}
      />

      {/* Diamond background */}
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ position: "absolute", inset: 0 }}
      >
        <defs>
          <linearGradient id="vs-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#e52d27" />
            <stop offset="100%" stopColor="#b31217" />
          </linearGradient>
          <filter id="vs-shadow">
            <feDropShadow
              dx={0}
              dy={4}
              stdDeviation={8}
              floodColor="#000000"
              floodOpacity={0.5}
            />
          </filter>
        </defs>
        {/* Diamond (rotated square) */}
        <rect
          x={size * 0.15}
          y={size * 0.15}
          width={size * 0.7}
          height={size * 0.7}
          rx={size * 0.08}
          fill="url(#vs-grad)"
          filter="url(#vs-shadow)"
          transform={`rotate(45, ${size / 2}, ${size / 2})`}
        />
      </svg>

      {/* VS Text */}
      <div
        style={{
          position: "relative",
          zIndex: 2,
          fontSize: Math.round(size * 0.32),
          fontWeight: 900,
          color: "#ffffff",
          letterSpacing: "0.08em",
          textShadow: "0 2px 8px rgba(0,0,0,0.6)",
          WebkitFontSmoothing: "antialiased",
        }}
      >
        VS
      </div>
    </div>
  );
};
