import React from "react";
import { Img, staticFile, useCurrentFrame } from "remotion";
import "flag-icons/css/flag-icons.min.css";
import type { CardData, VideoData } from "../types/video-data";
import { kenBurnsScale } from "../utils/animations";
import { getHeaderStat } from "./card-semantics";

interface CardProps extends CardData {
  isActive: boolean;
  language?: "vi" | "ja" | "en";
  cardLayout?: NonNullable<VideoData["cardLayout"]>;
  /** Global frame for Ken Burns */
  globalFrame?: number;
  /** When this card became active (for Ken Burns start) */
  activeStartFrame?: number;
}

export const CARD_WIDTH = 600;
export const CARD_HEIGHT = 1080;

export const Card: React.FC<CardProps> = (props) => {
  const {
    cardLayout = "classic",
    globalFrame = 0,
    activeStartFrame = 0,
  } = props;
  const frame = useCurrentFrame();
  const effectiveFrame = globalFrame || frame;
  const kbScale = kenBurnsScale(effectiveFrame, activeStartFrame, 180);

  if (cardLayout === "flag_hero") {
    return <FlagHeroCard {...props} kbScale={kbScale} />;
  }
  if (cardLayout === "split_data") {
    return <SplitDataCard {...props} kbScale={kbScale} />;
  }
  return <ClassicCard {...props} kbScale={kbScale} />;
};

const cardBase: React.CSSProperties = {
  width: CARD_WIDTH,
  height: CARD_HEIGHT,
  overflow: "hidden",
  display: "flex",
  flexDirection: "column",
  backgroundColor: "#1a1a1a",
  flexShrink: 0,
  backfaceVisibility: "hidden",
  WebkitFontSmoothing: "antialiased",
};

const ClassicCard: React.FC<CardProps & { kbScale: number }> = ({
  header,
  title,
  description,
  imagePath,
  statusText,
  kbScale,
}) => (
  <div style={cardBase}>
    <Band height={120} background="linear-gradient(180deg, #e52d27 0%, #b91d18 100%)" color="#ffffff" fontSize={36}>
      {header}
    </Band>

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
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: 60,
          background: "linear-gradient(transparent, rgba(0,0,0,0.6))",
        }}
      />
    </div>

    <div style={{ padding: "16px 20px 12px", backgroundColor: "#ffffff", flexShrink: 0 }}>
      <div
        style={{
          fontSize: 28,
          fontWeight: 900,
          color: "#111111",
          lineHeight: 1.2,
        }}
      >
        {title}
      </div>
    </div>

    <div style={{ flex: 1, padding: "12px 20px", backgroundColor: "#222222", overflow: "hidden" }}>
      <div
        style={{
          fontSize: 22,
          fontWeight: 500,
          color: "rgba(255,255,255,0.9)",
          lineHeight: 1.55,
        }}
      >
        {description}
      </div>
    </div>

    <Band height={80} background="#000000" color="#e52d27" fontSize={24}>
      {statusText}
    </Band>
  </div>
);

const FlagHeroCard: React.FC<CardProps & { kbScale: number }> = (props) => {
  const metric = metricText(props);
  return (
    <div style={cardBase}>
      <div
        style={{
          height: 300,
          background: "radial-gradient(circle at 50% 20%, #333333, #080808 70%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          flexShrink: 0,
        }}
      >
        <FlagBlock countryCode={props.countryCode} width={430} />
      </div>

      <Band height={98} background="#000000" color="#ffffff" fontSize={46}>
        {props.header}
      </Band>
      <Band height={92} background="#38bdf8" color="#050505" fontSize={42}>
        {props.title}
      </Band>
      <Band height={72} background="#f5f5f5" color="#050505" fontSize={30}>
        {metric}
      </Band>

      <SafeMainImage imagePath={props.imagePath} kbScale={props.kbScale} />
    </div>
  );
};

const SplitDataCard: React.FC<CardProps & { kbScale: number }> = (props) => {
  const headerStat = getHeaderStat(props.header);
  return (
    <div style={{ ...cardBase, backgroundColor: "#080808", padding: 18, gap: 14 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.25fr", gap: 14, height: 150, flexShrink: 0 }}>
        <StatBlock label={headerStat.label} value={headerStat.value} />
        <StatBlock label={props.metricLabel || "VALUE"} value={props.metricValue || props.statusText} />
      </div>

      <div style={{ height: 190, display: "grid", gridTemplateColumns: "220px 1fr", gap: 14, flexShrink: 0 }}>
        <div style={{ backgroundColor: "#ffffff", padding: 12, display: "flex", alignItems: "center" }}>
          <FlagBlock countryCode={props.countryCode} width={196} />
        </div>
        <div
          style={{
            backgroundColor: "#38bdf8",
            color: "#050505",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            padding: "0 18px",
            overflow: "hidden",
          }}
        >
          <div style={{ fontSize: 22, fontWeight: 900, opacity: 0.75, textTransform: "uppercase" }}>
            {props.countryLabel || "GLOBAL"}
          </div>
          <div style={{ fontSize: 37, fontWeight: 950, lineHeight: 1.02, textTransform: "uppercase" }}>
            {props.title}
          </div>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>
        <SafeMainImage imagePath={props.imagePath} kbScale={props.kbScale} />
      </div>
    </div>
  );
};

const SafeMainImage: React.FC<{ imagePath: string; kbScale: number }> = ({ imagePath, kbScale }) => (
  <div
    style={{
      width: "100%",
      height: "100%",
      position: "relative",
      overflow: "hidden",
      backgroundColor: "#101010",
    }}
  >
    <Img
      src={staticFile(imagePath)}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        objectFit: "cover",
        filter: "blur(18px) brightness(0.55)",
        transform: "scale(1.08)",
      }}
    />
    <Img
      src={staticFile(imagePath)}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        objectFit: "contain",
        transform: `scale(${Math.min(kbScale, 1.06)})`,
      }}
    />
  </div>
);

const FlagBlock: React.FC<{ countryCode?: string; width: number }> = ({ countryCode, width }) => {
  const normalized = (countryCode || "").toLowerCase();
  if (!/^[a-z]{2}$/.test(normalized)) {
    return (
      <div
        style={{
          width,
          height: Math.round(width * 2 / 3),
          backgroundColor: "#2b2f36",
          color: "#ffffff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 28,
          fontWeight: 900,
        }}
      >
        FLAG
      </div>
    );
  }
  return (
    <span
      className={`fi fi-${normalized}`}
      style={{
        width,
        height: Math.round(width * 2 / 3),
        display: "block",
        boxShadow: "0 10px 26px rgba(0,0,0,0.32)",
        backgroundSize: "cover",
      }}
    />
  );
};

const StatBlock: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div
    style={{
      backgroundColor: "#ffffff",
      color: "#050505",
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      padding: "16px 18px",
      overflow: "hidden",
    }}
  >
    <div style={{ fontSize: 20, fontWeight: 900, opacity: 0.62, textTransform: "uppercase" }}>
      {label}
    </div>
    <div style={{ fontSize: 38, fontWeight: 950, lineHeight: 1.0, textTransform: "uppercase" }}>
      {value}
    </div>
  </div>
);

const Band: React.FC<{
  height: number;
  background: string;
  color: string;
  fontSize: number;
  children: React.ReactNode;
}> = ({ height, background, color, fontSize, children }) => (
  <div
    style={{
      height,
      background,
      color,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "0 22px",
      flexShrink: 0,
      textAlign: "center",
      fontSize,
      fontWeight: 950,
      lineHeight: 1.05,
      textTransform: "uppercase",
      overflow: "hidden",
    }}
  >
    {children}
  </div>
);

const metricText = (card: CardData): string => (
  card.metricLabel ? `${card.metricLabel}: ${card.metricValue || card.statusText}` : card.metricValue || card.statusText
);
