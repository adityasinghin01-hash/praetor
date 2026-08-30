/**
 * Screen 05 — See what it did.
 *
 * Priya's problem 12 is "prove I did my job". The data has always answered it; no screen
 * ever showed the answer, because the work she did not have to do leaves no trace. This
 * screen is that trace.
 *
 * **Two numbers that count different things**, and the copy has to keep them apart or it
 * is just a bigger number for its own sake. `cleared` is everything that never reached a
 * person — the same arithmetic as the queue headline, the same figure FINDINGS reports as
 * autonomy. `judged` is the subset that raised something and was let through anyway. The
 * spot check comes from the second, because "show me one you let through" is a question
 * about decisions that could have gone the other way.
 *
 * The wall is `DriftWall` with paper instead of photographs. Its tiles are `<img>`
 * elements, so each sheet is drawn as an inline SVG and handed over as a data URI —
 * that keeps the vendored component untouched while nothing in colour reaches the screen.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import Counter from "../components/Counter";
import DriftWall from "../components/DriftWall";
import { api } from "../api";
import { Arrive, InkButton, KeyRail, useKeys, describeFailure } from "../ink";
import type { Failure } from "../ink";
import type { ClearedResponse } from "../types";

/**
 * One sheet of paper, as a data URI.
 *
 * Bars, not characters — the same rule the illustration prompts follow, for the same
 * reason: at this size any real text would be noise pretending to be information.
 */
function sheet(seed: number): string {
  const bars: string[] = [];
  const rows = 3 + (seed % 3);
  for (let i = 0; i < rows; i++) {
    const width = 30 + ((seed * (i + 7)) % 46);
    bars.push(`<rect x="14" y="${26 + i * 13}" width="${width}" height="3" fill="#0B0B0B"/>`);
  }
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 141">` +
    `<rect width="100" height="141" fill="#EFEEE8"/>` +
    `<rect x="1" y="1" width="98" height="139" fill="none" stroke="#0B0B0B" stroke-width="2"/>` +
    bars.join("") +
    `<rect x="14" y="104" width="58" height="24" fill="none" stroke="#0B0B0B" stroke-width="3"/>` +
    `<rect x="20" y="112" width="30" height="3" fill="#0B0B0B"/>` +
    `</svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function Did({ onDone }: { onDone?: () => void }) {
  const [data, setData] = useState<ClearedResponse | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [at, setAt] = useState(0);

  const load = useCallback(async () => {
    try {
      setData(await api.cleared());
      setFailure(null);
    } catch (e) {
      setFailure(describeFailure(e, "We could not load this. Please try again in a moment."));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const tiles = useMemo(
    () => Array.from({ length: 18 }, (_, i) => ({ image: sheet(i + 1), title: "" })),
    [],
  );

  const spot = data?.sample.length ? data.sample[at % data.sample.length] : null;

  useKeys({
    "1": () => setAt((n) => n + 1),
    Escape: () => onDone?.(),
  });

  if (failure) {
    return (
      <section className="did">
        <p className="state" role="alert">{failure.message}</p>
        {/* A retry is offered only where retrying could change the outcome. */}
        {failure.canRetry
          ? <InkButton onClick={() => void load()}>Try again</InkButton>
          : <a className="ink-btn cursor-target" href="/login"><span>Sign in</span></a>}
      </section>
    );
  }

  if (!data) return <p className="state">Loading…</p>;

  return (
    <section className="did">
      <Arrive>
        <div className="did-wall">
          {/* Decorative: the number and the sentence beside it carry the meaning.
              `inert` as well as aria-hidden — DriftWall makes every tile a focusable
              role="button", and a keyboard user must not tab through eighteen of them
              on the way to the spot check. */}
          <div className="did-wall-inner" aria-hidden="true" inert>
            <DriftWall
              items={tiles}
              columns={6}
              tileWidth={78}
              tileHeight={110}
              gap={16}
              speed={26}
              radius={0}
              grayscale
              // dim IS opacity in this component (--dw-dim), not an amount of dimming;
              // fade drives a mask edge. Full ink, with a soft edge at the frame.
              dim={1}
              fade={0.3}
              // Each tile ships a near-black overlay (#060010) as its resting state.
              // These are sheets of paper; nothing is laid over them.
              overlayColor="transparent"
              pauseOnHover
            />
          </div>

          <div className="did-figure">
            <Counter
              value={data.cleared}
              fontSize={72}
              textColor="#0B0B0B"
              fontWeight={800}
              gap={2}
              borderRadius={0}
              horizontalPadding={4}
              gradientHeight={0}
              gradientFrom="transparent"
              containerStyle={{ fontFamily: "var(--font-display)" }}
            />
            <p className="did-headline">{data.headline}</p>
          </div>
        </div>

        <div className="did-check">
          <p className="did-judged">{data.judged_note}</p>

          {spot ? (
            <article className="did-spot">
              <p className="did-spot-label">Spot check</p>
              <p className="did-spot-supplier">
                {spot.supplier} · {spot.amount} {spot.currency}
              </p>
              <p className="did-spot-said">{spot.system_said}</p>
              <p className="did-spot-note">{data.spot_check_note}</p>
            </article>
          ) : (
            <p className="did-spot-note">{data.spot_check_note}</p>
          )}
        </div>
      </Arrive>

      <KeyRail
        actions={[
          {
            key: "1",
            label: data.sample.length > 1 ? "Show me another" : "Show me one",
            onPress: () => setAt((n) => n + 1),
          },
        ]}
        escape={{ label: "Done", onPress: () => onDone?.() }}
      />
    </section>
  );
}
