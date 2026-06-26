import React from "react";
import { useCurrentFrame } from "remotion";
import { interpolate } from "remotion";

interface CounterProps {
  from: number;
  to: number;
  startFrame: number;
  duration: number;
  suffix?: string;
  prefix?: string;
  fontSize?: number;
  color?: string;
}

/**
 * Animated number counter that interpolates between two values.
 * Formats output with locale-aware thousand separators.
 */
export const Counter: React.FC<CounterProps> = ({
  from,
  to,
  startFrame,
  duration,
  suffix = "",
  prefix = "",
  fontSize = 48,
  color = "#ffffff",
}) => {
  const frame = useCurrentFrame();

  const currentValue = interpolate(
    frame - startFrame,
    [0, duration],
    [from, to],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }
  );

  const displayValue = Math.round(currentValue).toLocaleString("en-US");

  return (
    <div
      style={{
        fontSize,
        fontWeight: 900,
        color,
        fontVariantNumeric: "tabular-nums",
        letterSpacing: "-0.02em",
        WebkitFontSmoothing: "antialiased",
        backfaceVisibility: "hidden",
        textAlign: "center",
      }}
    >
      {prefix}
      {displayValue}
      {suffix}
    </div>
  );
};
