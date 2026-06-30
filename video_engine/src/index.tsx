import React from "react";
import { Composition, registerRoot } from "remotion";
import type { VideoData } from "./types/video-data";
import { calculateTotalDuration } from "./types/video-data";
import { TimelineVideo } from "./compositions/TimelineVideo";
import { RankingVideo } from "./compositions/RankingVideo";
import { ComparisonVideo } from "./compositions/ComparisonVideo";
import { CardSnapshot, type CardSnapshotProps } from "./snapshot";

const FPS = 30;
const WIDTH = 1920;
const HEIGHT = 1080;
const TimelineVideoComponent = TimelineVideo as unknown as React.FC<Record<string, unknown>>;
const RankingVideoComponent = RankingVideo as unknown as React.FC<Record<string, unknown>>;
const ComparisonVideoComponent = ComparisonVideo as unknown as React.FC<Record<string, unknown>>;
const CardSnapshotComponent = CardSnapshot as unknown as React.FC<Record<string, unknown>>;

/**
 * Default props for studio preview.
 * In production, these are overridden via --props CLI flag.
 */
const defaultProps: VideoData = {
  template: "timeline",
  title: "Preview Video",
  subtitle: "TOP 10 QUỐC GIA CÓ IQ CAO NHẤT",
  language: "vi",
  cards: [
    {
      header: "RANK 5",
      title: "Nhật Bản",
      description:
        "Nhật Bản nổi tiếng với hệ thống giáo dục tiên tiến và văn hóa học tập nghiêm túc.",
      imagePath: "images/placeholder.jpg",
      statusText: "IQ TRUNG BÌNH: 106",
    },
    {
      header: "RANK 4",
      title: "Đài Loan",
      description:
        "Đài Loan có nền công nghệ phát triển mạnh và chú trọng đầu tư giáo dục.",
      imagePath: "images/placeholder.jpg",
      statusText: "IQ TRUNG BÌNH: 106",
    },
    {
      header: "RANK 3",
      title: "Hàn Quốc",
      description:
        "Hàn Quốc có hệ thống giáo dục cạnh tranh cao và đầu tư mạnh vào R&D.",
      imagePath: "images/placeholder.jpg",
      statusText: "IQ TRUNG BÌNH: 107",
    },
    {
      header: "RANK 2",
      title: "Singapore",
      description:
        "Singapore luôn đứng đầu các bảng xếp hạng giáo dục quốc tế.",
      imagePath: "images/placeholder.jpg",
      statusText: "IQ TRUNG BÌNH: 108",
    },
    {
      header: "RANK 1",
      title: "Hồng Kông",
      description:
        "Hồng Kông dẫn đầu thế giới về chỉ số IQ trung bình.",
      imagePath: "images/placeholder.jpg",
      statusText: "IQ TRUNG BÌNH: 108",
    },
  ],
  musicPath: "audio/bgm.mp3",
  sfxPaths: {
    transition: "audio/sfx-transition.mp3",
    alert: "audio/sfx-alert.mp3",
    reveal: "audio/sfx-reveal.mp3",
  },
  logoPath: "images/logo.png",
  holdDurationFrames: 120,
  transitionDurationFrames: 15,
};

const defaultSnapshotProps: CardSnapshotProps = {
  card: defaultProps.cards[0],
  cardLayout: "flag_hero",
  language: "en",
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="TimelineVideo"
        component={TimelineVideoComponent}
        durationInFrames={calculateTotalDuration(defaultProps)}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={defaultProps}
        calculateMetadata={async ({ props }) => {
          const videoProps = props as unknown as VideoData;
          return {
            durationInFrames: calculateTotalDuration(videoProps),
            fps: FPS,
            width: WIDTH,
            height: HEIGHT,
          };
        }}
      />

      <Composition
        id="RankingVideo"
        component={RankingVideoComponent}
        durationInFrames={calculateTotalDuration(defaultProps)}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{ ...defaultProps, template: "ranking" as const }}
        calculateMetadata={async ({ props }) => {
          const videoProps = props as unknown as VideoData;
          return {
            durationInFrames: calculateTotalDuration(videoProps),
            fps: FPS,
            width: WIDTH,
            height: HEIGHT,
          };
        }}
      />

      <Composition
        id="ComparisonVideo"
        component={ComparisonVideoComponent}
        durationInFrames={calculateTotalDuration(defaultProps)}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{ ...defaultProps, template: "comparison" as const }}
        calculateMetadata={async ({ props }) => {
          const videoProps = props as unknown as VideoData;
          return {
            durationInFrames: calculateTotalDuration(videoProps),
            fps: FPS,
            width: WIDTH,
            height: HEIGHT,
          };
        }}
      />

      <Composition
        id="CardSnapshot"
        component={CardSnapshotComponent}
        durationInFrames={1}
        fps={FPS}
        width={600}
        height={1080}
        defaultProps={defaultSnapshotProps}
      />

    </>
  );
};

registerRoot(RemotionRoot);
