/**
 * Screen 06 — What we stopped.
 *
 * The only screen here written for her manager rather than for her. It answers one
 * question — did the controls do anything — and it has to answer it without overclaiming,
 * because a number that flatters the system is worth less than one that survives being
 * checked.
 *
 * **Money is never summed across currencies.** `dashboard/api.py` keeps the exposure per
 * currency and this renders one line per currency from that structured field, adding
 * nothing together. Adding EUR to GBP is wrong in a way nobody notices until a finance
 * person reads it, and then every other figure on the page is in doubt — which is also
 * why the server's pre-joined string is not used: HTML collapses its separator and the
 * two figures run together into something that reads as one.
 *
 * **It says "at risk", not "saved".** No confirmed incident exists in this data, so the
 * wording must not imply one. `tests/test_api.py` holds the server to that and this
 * screen only passes it through.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Arrive, InkButton, KeyRail, useKeys, describeFailure } from "../ink";
import type { Failure } from "../ink";
import type { StoppedResponse } from "../types";

export function Stopped({ onDone }: { onDone?: () => void }) {
  const [data, setData] = useState<StoppedResponse | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [showing, setShowing] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.stopped());
      setFailure(null);
    } catch (e) {
      setFailure(describeFailure(e, "We could not load this. Please try again in a moment."));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useKeys({
    "1": () => setShowing((v) => !v),
    Escape: () => onDone?.(),
  });

  if (failure) {
    return (
      <section className="stopped">
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
    <section className="stopped">
      <Arrive>
        <div className="stopped-card">
          <h2 className="stopped-headline display">{data.headline}</h2>

          <div className="stopped-figures">
            <div className="figure">
              {/* One line per currency, from the structured field rather than the
                  joined string — HTML collapses the separator, and "USD 9,643.71 GBP
                  4,048.36" on one line reads as a single number, which is exactly the
                  confusion keeping them apart exists to prevent. */}
              {Object.entries(data.exposure_by_currency)
                .sort(([, a2], [, b2]) => b2 - a2)
                .map(([code, value]) => (
                  <p className="figure-n" key={code}>
                    <span className="figure-cur">{code}</span>{" "}
                    {value.toLocaleString("en-GB", {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </p>
                ))}
              <p className="figure-note">{data.exposure_note}</p>
            </div>
            <div className="figure">
              <p className="figure-n">{data.ai_overruled}</p>
              <p className="figure-note">{data.ai_overruled_note}</p>
            </div>
          </div>

          {data.controls.length ? (
            <div className="stopped-controls">
              <p className="stopped-label">What caught them</p>
              <ul>
                {data.controls.map((c) => (
                  <li key={c.what}>
                    <span className="control-times">{c.times}</span>
                    <span className="control-what">{c.what}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {showing && data.decisions.length ? (
            <div className="stopped-controls">
              <p className="stopped-label">Every decision, and who made it</p>
              <ul className="stopped-decisions">
                {data.decisions.map((d) => (
                  <li key={d.id}>
                    <span className="control-what">
                      {d.supplier} — {d.outcome_label}
                      {d.decided_by ? ` · ${d.decided_by}` : ""}
                    </span>
                    <span className="figure-note">{d.system_said}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </Arrive>

      <KeyRail
        actions={[
          {
            key: "1",
            label: showing ? "Hide the decisions" : `Show every decision (${data.decisions.length})`,
            onPress: () => setShowing((v) => !v),
          },
        ]}
        escape={{ label: "Done", onPress: () => onDone?.() }}
      />
    </section>
  );
}
