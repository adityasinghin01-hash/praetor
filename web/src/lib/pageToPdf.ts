/**
 * Wrap a captured camera frame in a one-page PDF.
 *
 * `POST /v1/documents` accepts PDFs and nothing else — it checks the extension *and* the
 * `%PDF-` magic bytes, because "the extension is the caller's claim; this is the file's
 * own answer". Screen 02 captures a JPEG, so without this it has nowhere to send it.
 *
 * The alternative was an image branch on the server. `dashboard/asgi.py` argues against
 * that in as many words: one pipeline, so an uploaded document gets the same grounding,
 * the same origin check and the same gate as one that arrived in a bucket. A second
 * intake path is a second place for a document to skip a check.
 *
 * So the frame is wrapped, not converted. `/Filter /DCTDecode` means the JPEG is carried
 * as-is — **the pixels the camera produced are the pixels Document AI reads**, with no
 * re-encode, no quality loss and no second interpretation of the image.
 *
 * The file is assembled as bytes rather than a string because a JPEG is binary and a
 * PDF's cross-reference table is a list of byte offsets: build it as text and every
 * offset is wrong the moment a byte above 0x7F appears.
 */

const ASCII = new TextEncoder();

function ascii(text: string): Uint8Array {
  return ASCII.encode(text);
}

/** A PDF xref entry is exactly 20 bytes. Anything else and the table stops parsing. */
function xrefEntry(offset: number, generation: number, kind: "n" | "f"): string {
  return `${String(offset).padStart(10, "0")} ${String(generation).padStart(5, "0")} ${kind} \n`;
}

export interface PageToPdfOptions {
  /** JPEG bytes, exactly as the encoder produced them. */
  jpeg: Uint8Array;
  /** Pixel dimensions of that JPEG; used as the page size at 1px = 1pt. */
  width: number;
  height: number;
}

/**
 * @returns the bytes of a single-page PDF whose only content is `jpeg`, drawn to fill
 *          the page. Begins `%PDF-`, so it satisfies the server's own check.
 */
export function pageToPdf({ jpeg, width, height }: PageToPdfOptions): Uint8Array {
  if (width <= 0 || height <= 0) {
    throw new Error("a page needs a width and a height");
  }
  if (jpeg.length < 4 || jpeg[0] !== 0xff || jpeg[1] !== 0xd8) {
    // Better to refuse here than to hand the server a PDF wrapped around nothing.
    throw new Error("that is not JPEG data");
  }

  const content = `q ${width} 0 0 ${height} 0 0 cm /Im0 Do Q\n`;

  const objects: Uint8Array[] = [
    ascii("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"),
    ascii("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"),
    ascii(
      "3 0 obj\n<< /Type /Page /Parent 2 0 R " +
        `/MediaBox [0 0 ${width} ${height}] ` +
        "/Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>\nendobj\n",
    ),
    ascii(`4 0 obj\n<< /Length ${content.length} >>\nstream\n${content}endstream\nendobj\n`),
    // Object 5 is assembled below: its stream is binary and cannot go through `ascii`.
  ];

  const imageHead = ascii(
    "5 0 obj\n<< /Type /XObject /Subtype /Image " +
      `/Width ${width} /Height ${height} ` +
      "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode " +
      `/Length ${jpeg.length} >>\nstream\n`,
  );
  const imageTail = ascii("\nendstream\nendobj\n");

  // `%\xE2\xE3\xCF\xD3` on line two is the conventional marker that says "this file is
  // binary" — it stops a naive transport from treating it as text and mangling newlines.
  const header = new Uint8Array([
    ...ascii("%PDF-1.4\n"),
    0x25, 0xe2, 0xe3, 0xcf, 0xd3, 0x0a,
  ]);

  const chunks: Uint8Array[] = [header, ...objects, imageHead, jpeg, imageTail];

  // Offsets are counted while the file is assembled; objects 1..4 start at the head of
  // their own chunk, and object 5 starts where `imageHead` does.
  const offsets: number[] = [];
  let at = header.length;
  for (const object of objects) {
    offsets.push(at);
    at += object.length;
  }
  offsets.push(at); // object 5
  const startXref = at + imageHead.length + jpeg.length + imageTail.length;

  let table = `xref\n0 ${offsets.length + 1}\n${xrefEntry(0, 65535, "f")}`;
  for (const offset of offsets) table += xrefEntry(offset, 0, "n");
  table +=
    `trailer\n<< /Size ${offsets.length + 1} /Root 1 0 R >>\n` +
    `startxref\n${startXref}\n%%EOF\n`;

  chunks.push(ascii(table));

  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const pdf = new Uint8Array(total);
  let cursor = 0;
  for (const chunk of chunks) {
    pdf.set(chunk, cursor);
    cursor += chunk.length;
  }
  return pdf;
}

/**
 * The filename the server sees. It takes the stem as the document id, so this is what a
 * captured page ends up called in the queue — worth being deliberate about rather than
 * letting it be `blob`.
 */
export function captureFilename(now: Date = new Date()): string {
  const stamp = now.toISOString().replace(/[:.]/g, "-").replace("Z", "");
  return `scan-${stamp}.pdf`;
}
