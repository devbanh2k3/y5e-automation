import {describe, expect, it} from "vitest";
import {getHeaderStat} from "./card-semantics";

describe("getHeaderStat", () => {
  it("preserves ranking semantics", () => {
    expect(getHeaderStat("TOP 3")).toEqual({label: "RANK", value: "#3"});
  });

  it("uses type semantics for factual formats", () => {
    expect(getHeaderStat("FACT 1")).toEqual({label: "TYPE", value: "FACT 1"});
    expect(getHeaderStat("MILESTONE")).toEqual({label: "TYPE", value: "MILESTONE"});
    expect(getHeaderStat("COUNT")).toEqual({label: "TYPE", value: "COUNT"});
  });
});
