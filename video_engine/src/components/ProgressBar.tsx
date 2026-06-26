import React from "react";

interface ProgressBarProps {
  current: number;
  total: number;
  color?: string;
  height?: number;
  label?: string;
}

/**
 * Horizontal progress bar with filled portion and text label.
 */
export const ProgressBar: React.FC<ProgressBarProps> = ({
  current,
  total,
  color = "#e52d27",
  height = 6,
  label,
}) => {
  const progress = Math.min(1, Math.max(0, current / total));
  const displayLabel = label ?? `${current} / ${total}`;

  return (
    <div
      style={{
        width: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 6,
      }}
    >
      {/* Track */}
      <div
        style={{
          width: "100%",
          height,
          backgroundColor: "rgba(255, 255, 255, 0.15)",
          borderRadius: height / 2,
          overflow: "hidden",
          position: "relative",
        }}
      >
        {/* Fill */}
        <div
          style={{
            width: `${Math.round(progress * 100)}%`,
            height: "100%",
            backgroundColor: color,
            borderRadius: height / 2,
            transition: "width 0.3s ease",
            boxShadow: `0 0 8px ${color}66`,
          }}
        />
      </div>
      {/* Label */}
      <div
        style={{
          fontSize: 16,
          fontWeight: 700,
          color: "rgba(255, 255, 255, 0.7)",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
        }}
      >
        {displayLabel}
      </div>
    </div>
  );
};
