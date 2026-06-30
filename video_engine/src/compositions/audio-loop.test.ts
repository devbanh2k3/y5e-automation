import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {describe, expect, it} from "vitest";

const files = ["RankingVideo.tsx", "TimelineVideo.tsx", "ComparisonVideo.tsx"];

describe("background audio", () => {
  for (const file of files) {
    it(`loops music in ${file}`, () => {
      const source = readFileSync(
        fileURLToPath(new URL(file, import.meta.url)),
        "utf8",
      );
      expect(source).toMatch(
        /<Audio[\s\S]*?src=\{staticFile\(musicPath\)\}[\s\S]*?\bloop\b[\s\S]*?\/>/,
      );
    });
  }
});
