/**
 * Screen 02 — Scan.
 *
 * The camera opens immediately and there is no shutter button: when the page is readable
 * the screen takes it. That is the whole idea of this screen, and it is why the build
 * order puts it first.
 *
 * **What the camera can and cannot know.** Four of the six states are decided here, from
 * the video: whether a page-shaped region is present, whether it is sharp enough, whether
 * it runs off the edge of the frame, and whether it is good enough to take. Two are not:
 *
 *   - *"that is not an invoice"* is a pipeline outcome. It arrives with the response and
 *     is never guessed at locally — a screen that says it before the server has looked is
 *     a screen that lies.
 *   - *"that is a screen, not paper"* is the weakest of the six and is treated as such.
 *     A monitor photographed by a phone is bright, flat and low-texture compared with
 *     paper, which is what `looksLikeADisplay` tests. It is a hint, not detection, and it
 *     only ever delays a capture — it never rejects on its own.
 *
 * Analysis runs on a downscaled grey copy at a few frames a second. A full-resolution
 * per-frame pass would heat a phone for no gain: none of these measures need the detail.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Scanner from "../components/Scanner";
import { KeyRail, useKeys, useReducedMotion } from "../ink";
import { api, ApiError } from "../api";
import { captureFilename, pageToPdf } from "../lib/pageToPdf";
import type { CaptureResult } from "../types";

/** The six states, in the order `docs/FRONTEND.md` lists them. */
type State =
  | "looking"
  | "display"
  | "blurry"
  | "cut-off"
  | "got-it"
  | "reading"
  | "not-an-invoice"
  | "done"
  | "no-camera"
  | "camera-blocked";

const SAYS: Record<State, { glyph: string; text: string; tone: "quiet" | "warn" | "stop" | "good" }> = {
  looking: { glyph: "◯", text: "looking for a page…", tone: "quiet" },
  display: { glyph: "✕", text: "that is a screen, not paper", tone: "stop" },
  blurry: { glyph: "△", text: "too blurry — hold still", tone: "warn" },
  "cut-off": { glyph: "△", text: "a corner is cut off", tone: "warn" },
  "got-it": { glyph: "●", text: "got it — reading", tone: "good" },
  reading: { glyph: "●", text: "reading…", tone: "good" },
  "not-an-invoice": { glyph: "✕", text: "that is not an invoice", tone: "stop" },
  done: { glyph: "●", text: "read — next page", tone: "good" },
  "no-camera": { glyph: "✕", text: "no camera available on this device", tone: "stop" },
  // Distinct from the above on purpose. Telling someone their device has no camera when
  // they have just denied permission sends them looking for a fault that is not there.
  "camera-blocked": {
    glyph: "✕",
    text: "camera access is blocked — allow it in your browser, or use Upload on Today",
    tone: "stop",
  },
};

/** Downscale used for every measurement below. Small on purpose. */
const W = 96;
const H = 128;

export interface Look {
  sharpness: number;   // variance of the Laplacian; higher is sharper
  coverage: number;    // fraction of the frame the bright region fills
  touchesEdge: boolean;
  flatness: number;    // low texture across a bright field suggests a lit display
}

function measure(pixels: Uint8ClampedArray): Look {
  const grey = new Float32Array(W * H);
  for (let i = 0, p = 0; i < grey.length; i++, p += 4) {
    grey[i] = 0.299 * pixels[p]! + 0.587 * pixels[p + 1]! + 0.114 * pixels[p + 2]!;
  }

  let sum = 0;
  for (let i = 0; i < grey.length; i++) sum += grey[i]!;
  const mean = sum / grey.length;

  // A page is the bright part of the frame. Halfway between the mean and white is a
  // crude threshold and a stable one — it does not chase the exposure around.
  const threshold = mean + (255 - mean) * 0.35;
  let minX = W, minY = H, maxX = -1, maxY = -1, bright = 0;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (grey[y * W + x]! < threshold) continue;
      bright++;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }

  // Laplacian, and the mean absolute response over the bright region only — measuring
  // sharpness across the whole frame would score the background's clutter as focus.
  let lapSum = 0, lapSq = 0, lapN = 0;
  for (let y = 1; y < H - 1; y++) {
    for (let x = 1; x < W - 1; x++) {
      const i = y * W + x;
      if (grey[i]! < threshold) continue;
      const lap =
        4 * grey[i]! - grey[i - 1]! - grey[i + 1]! - grey[i - W]! - grey[i + W]!;
      lapSum += lap;
      lapSq += lap * lap;
      lapN++;
    }
  }
  const lapMean = lapN ? lapSum / lapN : 0;
  const sharpness = lapN ? lapSq / lapN - lapMean * lapMean : 0;

  return {
    sharpness,
    coverage: bright / (W * H),
    touchesEdge: maxX >= W - 2 || minX <= 1 || maxY >= H - 2 || minY <= 1,
    // Bright and textureless at once. Paper carries print; a lit screen photographed
    // from a distance mostly does not, at this scale.
    flatness: mean > 165 && sharpness < 18 ? 1 : 0,
  };
}

export function readFrame(look: Look): State {
  if (look.coverage < 0.12) return "looking";
  if (look.flatness === 1) return "display";
  if (look.sharpness < 26) return "blurry";
  if (look.touchesEdge) return "cut-off";
  return "got-it";
}

export function Scan({ onDone }: { onDone?: () => void }) {
  const stillness = useReducedMotion();
  const videoRef = useRef<HTMLVideoElement>(null);
  const workRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const goodFrames = useRef(0);
  const busy = useRef(false);

  const [state, setState] = useState<State>("looking");
  const [result, setResult] = useState<CaptureResult | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const capture = useCallback(async () => {
    const video = videoRef.current;
    if (!video || busy.current) return;
    busy.current = true;
    setState("reading");

    try {
      // Full resolution for the capture itself — the analysis was downscaled, the
      // document that gets read is not.
      const full = document.createElement("canvas");
      full.width = video.videoWidth;
      full.height = video.videoHeight;
      full.getContext("2d")?.drawImage(video, 0, 0);

      const blob = await new Promise<Blob | null>((resolve) =>
        full.toBlob(resolve, "image/jpeg", 0.92),
      );
      if (!blob) throw new Error("the camera frame could not be encoded");

      const pdf = pageToPdf({
        jpeg: new Uint8Array(await blob.arrayBuffer()),
        width: full.width,
        height: full.height,
      });

      const outcome = await api.sendPage(pdf, captureFilename());
      setResult(outcome);
      // The pipeline's answer, not a guess made here.
      setState(outcome.error ? "not-an-invoice" : "done");
    } catch (error) {
      setProblem(
        error instanceof ApiError && error.message
          ? error.message
          : "that page could not be sent. Hold it up again.",
      );
      setState("looking");
    } finally {
      goodFrames.current = 0;
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let timer = 0;

    async function open() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment", width: { ideal: 1920 } },
          audio: false,
        });
        if (!alive) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play().catch(() => {});
        }
        tick();
      } catch (err) {
        if (!alive) return;
        // NotAllowedError is a person saying no; NotFoundError is a device that has none.
        // SecurityError is the same refusal arriving from a policy rather than a prompt.
        const name = err instanceof Error ? err.name : "";
        setState(name === "NotAllowedError" || name === "SecurityError"
          ? "camera-blocked"
          : "no-camera");
      }
    }

    function tick() {
      if (!alive) return;
      const video = videoRef.current;
      const work = workRef.current;
      const ctx = work?.getContext("2d", { willReadFrequently: true });

      if (video && work && ctx && video.videoWidth > 0 && !busy.current) {
        ctx.drawImage(video, 0, 0, W, H);
        const next = readFrame(measure(ctx.getImageData(0, 0, W, H).data));
        setState((current) => (current === "done" ? current : next));

        // Two good frames in a row, so a single lucky frame during a hand movement
        // cannot fire the capture.
        goodFrames.current = next === "got-it" ? goodFrames.current + 1 : 0;
        if (goodFrames.current >= 2) void capture();
      }
      timer = window.setTimeout(tick, 160);
    }

    void open();
    return () => {
      alive = false;
      window.clearTimeout(timer);
      stop();
    };
  }, [capture, stop]);

  useKeys({
    "3": () => {
      setResult(null);
      setProblem(null);
      setState("looking");
    },
    Escape: () => {
      stop();
      onDone?.();
    },
  });

  const says = SAYS[state];

  return (
    <section className="scan-screen">
      <div className="scan-stage">
        <video ref={videoRef} className="scan-video" playsInline muted />

        {/* The bands sweep *over* the feed, not behind it. Behind, the video covers them
            completely and the searching animation is never seen at all. Multiply blend
            means the ink lines darken the page the camera is looking at, which is what
            ink does. Glow off: this direction has no light, only ink. */}
        {/* The bands are a shader, so the stylesheet cannot quiet them. Someone who has
            asked for less movement gets the camera and the six states without a sweep
            crossing the page they are trying to hold still. */}
        <div className="scan-bands" aria-hidden="true">
          {stillness ? null : <Scanner
            color1="#EFEEE8"
            color2="#EFEEE8"
            color3="#0B0B0B"
            colorSpread={0}
            glow={0}
            grain={false}
            scanline={false}
            vignette={0}
            softness={0.5}
            bandDensity={11}
            lineSharpness={5.5}
            brightness={1}
            contrast={1.2}
          />}
        </div>
        <canvas ref={workRef} width={W} height={H} className="sr-only" aria-hidden="true" />

        <p className={`scan-read tone-${says.tone}`} role="status">
          <span className="g" aria-hidden="true">{says.glyph}</span>
          <span>{problem ?? says.text}</span>
          {result && state === "done" ? (
            <span className="scan-doc">{result.doc_id}</span>
          ) : null}
        </p>
      </div>

      <KeyRail
        actions={[{ key: "3", label: "Next page", onPress: () => setState("looking") }]}
        escape={{ label: "Done", onPress: () => { stop(); onDone?.(); } }}
      />
    </section>
  );
}
