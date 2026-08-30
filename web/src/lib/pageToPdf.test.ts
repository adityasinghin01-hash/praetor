/**
 * The wrapper has to satisfy a server that does not trust it.
 *
 * `dashboard/asgi.py` checks two things independently: the filename ends `.pdf`, and the
 * payload itself begins `%PDF-`. Both are asserted here, against the real function,
 * because a frontend that produces a file the endpoint rejects fails at the one moment
 * that matters — with a page held up to a camera.
 *
 * The offset assertions are the load-bearing ones. A PDF's cross-reference table is a
 * list of byte positions, and the JPEG in the middle of this file is binary: if anything
 * in `pageToPdf` ever measures characters instead of bytes, every offset after the image
 * silently points at the wrong place and readers fail in ways that look like corruption.
 */
import { describe, expect, it } from "vitest";
import { captureFilename, pageToPdf } from "./pageToPdf";

/** A JPEG that is only just a JPEG: the two markers, and a byte above 0x7F between. */
function fakeJpeg(): Uint8Array {
  return new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0xc3, 0xa9, 0xff, 0xd9]);
}

function bytesOf(pdf: Uint8Array, from: number, length: number): string {
  return new TextDecoder("latin1").decode(pdf.subarray(from, from + length));
}

describe("pageToPdf", () => {
  const jpeg = fakeJpeg();
  const pdf = pageToPdf({ jpeg, width: 1224, height: 1584 });
  const text = new TextDecoder("latin1").decode(pdf);

  it("begins with the magic bytes the server checks for", () => {
    // dashboard/asgi.py: `if not payload.startswith(b"%PDF-")`
    expect(bytesOf(pdf, 0, 5)).toBe("%PDF-");
  });

  it("names the file so the server's own extension check passes", () => {
    // dashboard/asgi.py: `if not (file.filename or "").lower().endswith(".pdf")`
    expect(captureFilename(new Date("2026-08-30T09:15:00Z")).endsWith(".pdf")).toBe(true);
  });

  it("carries the JPEG through unmodified", () => {
    // DCTDecode means no re-encode: the bytes the camera produced must appear verbatim,
    // or Document AI is reading a different image than the one that was captured.
    let found = -1;
    outer: for (let i = 0; i <= pdf.length - jpeg.length; i++) {
      for (let j = 0; j < jpeg.length; j++) {
        if (pdf[i + j] !== jpeg[j]) continue outer;
      }
      found = i;
      break;
    }
    expect(found).toBeGreaterThan(-1);
  });

  it("declares the image as DCTDecode at the captured size", () => {
    expect(text).toContain("/Filter /DCTDecode");
    expect(text).toContain("/Width 1224 /Height 1584");
    expect(text).toContain("/MediaBox [0 0 1224 1584]");
  });

  it("points every xref offset at the object it claims", () => {
    const startXref = Number(/startxref\n(\d+)/.exec(text)?.[1]);
    expect(Number.isFinite(startXref)).toBe(true);
    expect(bytesOf(pdf, startXref, 4)).toBe("xref");

    // Entries are fixed-width: 20 bytes each, after "xref\n0 6\n" and the free entry.
    const tableAt = startXref + "xref\n0 6\n".length;
    for (let object = 1; object <= 5; object++) {
      const entry = bytesOf(pdf, tableAt + object * 20, 20);
      const offset = Number(entry.slice(0, 10));
      expect(bytesOf(pdf, offset, `${object} 0 obj`.length)).toBe(`${object} 0 obj`);
    }
  });

  it("refuses anything that is not a JPEG rather than wrapping it", () => {
    const notJpeg = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    expect(() => pageToPdf({ jpeg: notJpeg, width: 10, height: 10 })).toThrow(/not JPEG/);
    expect(() => pageToPdf({ jpeg, width: 0, height: 10 })).toThrow(/width and a height/);
  });
});
