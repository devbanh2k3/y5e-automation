import React from "react";

interface HexagonProps {
  text: string;
  size?: number;
}

/**
 * SVG hexagon badge with centered text.
 * Red fill (#e52d27) with white bold text.
 */
export const Hexagon: React.FC<HexagonProps> = ({ text, size = 64 }) => {
  const halfW = size / 2;
  const halfH = (size * 0.866) / 2; // height = size * sqrt(3)/2
  const viewW = size;
  const viewH = size * 0.866;

  // Pointy-top hexagon points
  const points = [
    `${halfW},0`,
    `${viewW},${halfH * 0.5}`,
    `${viewW},${halfH * 1.5}`,
    `${halfW},${viewH}`,
    `0,${halfH * 1.5}`,
    `0,${halfH * 0.5}`,
  ].join(" ");

  return (
    <svg
      width={size}
      height={Math.round(viewH)}
      viewBox={`0 0 ${viewW} ${viewH}`}
      style={{ overflow: "visible", flexShrink: 0 }}
    >
      <polygon
        points={points}
        fill="#e52d27"
        stroke="#b71c1c"
        strokeWidth={1.5}
      />
      <foreignObject x={0} y={0} width={viewW} height={viewH}>
        <div
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#ffffff",
            fontWeight: 900,
            fontSize: Math.round(size * 0.22),
            textAlign: "center",
            lineHeight: 1.1,
            padding: "0 4px",
            boxSizing: "border-box",
            textTransform: "uppercase",
            letterSpacing: "0.02em",
          }}
        >
          {text}
        </div>
      </foreignObject>
    </svg>
  );
};
