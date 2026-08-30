/**
 * The six states, as a decision table.
 *
 * These orderings are the screen's whole behaviour and every one of them is a judgement
 * that could reasonably have gone the other way — so they are pinned here rather than
 * living only in the order of some `if`s.
 *
 * The most important assertion is the last one: the camera must never claim a page is
 * not an invoice. Only the pipeline knows that, and a screen that says it early is a
 * screen that tells Priya something untrue about a document nobody has read yet.
 */
import { describe, expect, it } from "vitest";
import { readFrame } from "./Scan";
import type { Look } from "./Scan";

const sharp: Look = { sharpness: 60, coverage: 0.5, touchesEdge: false, flatness: 0 };

describe("what the camera decides", () => {
  it("says nothing is there before it says anything is wrong", () => {
    // An empty frame is not a blurry frame. "Looking" has to win, or the screen nags
    // about focus while pointed at a desk.
    expect(readFrame({ ...sharp, coverage: 0.05, sharpness: 0 })).toBe("looking");
  });

  it("ranks a display above focus, because focus cannot fix it", () => {
    expect(readFrame({ ...sharp, flatness: 1, sharpness: 5 })).toBe("display");
  });

  it("asks for stillness before it complains about framing", () => {
    // Both can be true at once. Sharpening is the smaller ask, so it comes first.
    expect(readFrame({ ...sharp, sharpness: 10, touchesEdge: true })).toBe("blurry");
  });

  it("notices a page running off the edge once it is sharp", () => {
    expect(readFrame({ ...sharp, touchesEdge: true })).toBe("cut-off");
  });

  it("takes the page when it is present, sharp and whole", () => {
    expect(readFrame(sharp)).toBe("got-it");
  });

  it("never decides a page is not an invoice", () => {
    // That answer belongs to ingest/pipeline.py and arrives with the response.
    const everyShape: Look[] = [];
    for (const coverage of [0, 0.11, 0.12, 0.9]) {
      for (const sharpness of [0, 25, 26, 400]) {
        for (const touchesEdge of [true, false]) {
          for (const flatness of [0, 1]) {
            everyShape.push({ coverage, sharpness, touchesEdge, flatness });
          }
        }
      }
    }
    for (const look of everyShape) {
      expect(readFrame(look)).not.toBe("not-an-invoice");
    }
  });
});
