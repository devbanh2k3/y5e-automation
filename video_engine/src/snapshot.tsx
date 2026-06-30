import React from "react";
import type {CardData, VideoData} from "./types/video-data";
import {Card} from "./components/Card";

export interface CardSnapshotProps {
  card: CardData;
  cardLayout?: NonNullable<VideoData["cardLayout"]>;
  language?: VideoData["language"];
}

export const CardSnapshot: React.FC<CardSnapshotProps> = ({
  card,
  cardLayout = "flag_hero",
  language = "en",
}) => (
  <Card
    {...card}
    snapshotPath={undefined}
    isActive
    cardLayout={cardLayout}
    language={language}
    globalFrame={90}
    activeStartFrame={0}
  />
);
