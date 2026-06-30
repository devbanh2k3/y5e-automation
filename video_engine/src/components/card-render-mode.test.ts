import {describe, expect, it} from "vitest";
import {resolveCardMedia} from "./Card";

describe("resolveCardMedia", () => {
  it("uses snapshot and pre-baked background when supplied", () => {
    expect(
      resolveCardMedia({
        imagePath: "images/original.webp",
        snapshotPath: "render-cache/card-1.png",
        backgroundImagePath: "render-cache/card-1-bg.webp",
      }),
    ).toEqual({
      foreground: "render-cache/card-1.png",
      background: "render-cache/card-1-bg.webp",
      snapshot: "render-cache/card-1.png",
      needsCssBlur: false,
    });
  });

  it("keeps the current dynamic card fallback", () => {
    expect(resolveCardMedia({imagePath: "images/original.webp"})).toEqual({
      foreground: "images/original.webp",
      background: "images/original.webp",
      snapshot: undefined,
      needsCssBlur: true,
    });
  });
});
