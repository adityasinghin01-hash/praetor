/**
 * Screen 07 — Try to break it.
 *
 * A real invoice, a line the visitor writes, and the actual kernel run against it. Not a
 * simulation and not a recording: `POST /v1/gauntlet/run` puts the text through the same
 * chain a delivered document goes through, and every attempt is logged.
 *
 * **The examples are the ones that work.** `dashboard/api.py` draws them from the
 * techniques FINDINGS §2 measured as *succeeding* against an ordinary extraction prompt —
 * the ones that read like ordinary business correspondence. Offering the ones that look
 * like attacks would flatter us, because those are the ones a model already resists.
 *
 * **The failure is shown as a chain, not a verdict.** Which check stopped it and how far
 * it got are the interesting part; "blocked" on its own teaches nothing and invites the
 * suspicion that nothing ran.
 *
 * This screen is open on purpose. Requiring a sign-in to attack a demo defeats its point,
 * and it touches only the synthetic corpus.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Arrive, InkButton, KeyRail, useKeys } from "../ink";
import type { GauntletDoc, GauntletExample, GauntletResult } from "../types";

export function Break({ onDone }: { onDone?: () => void }) {
  const [docs, setDocs] = useState<GauntletDoc[]>([]);
  const [examples, setExamples] = useState<GauntletExample[]>([]);
  const [at, setAt] = useState(0);
  const [text, setText] = useState("");
  const [result, setResult] = useState<GauntletResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [d, e] = await Promise.all([api.gauntletDocs(), api.gauntletExamples()]);
        setDocs(d.documents);
        setExamples(e.examples);
        setText(e.examples[0]?.text ?? "");
      } catch (err) {
        const said = err instanceof Error ? err.message : "";
        setError(said || "We could not load this. Please try again in a moment.");
      }
    })();
  }, []);

  const doc = docs[at % Math.max(docs.length, 1)];

  const run = useCallback(async () => {
    if (!doc || running || !text.trim()) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await api.gauntletRun(doc.id, text));
    } catch (err) {
      const said = err instanceof Error ? err.message : "";
      setError(said || "That did not run. Try again in a moment.");
    } finally {
      setRunning(false);
    }
  }, [doc, text, running]);

  const nextExample = useCallback(() => {
    if (!examples.length) return;
    const i = (examples.findIndex((e) => e.text === text) + 1) % examples.length;
    setText(examples[i]?.text ?? "");
    setResult(null);
  }, [examples, text]);

  useKeys({
    "1": () => void run(),
    "2": nextExample,
    "3": () => { setAt((n) => n + 1); setResult(null); },
    Escape: () => onDone?.(),
  });

  if (error && !docs.length) {
    return (
      <section className="brk">
        <p className="state">{error}</p>
      </section>
    );
  }

  if (!doc) return <p className="state">Loading…</p>;

  return (
    <section className="brk">
      <Arrive>
        <div className="brk-card">
          <p className="stopped-label">The invoice you are attacking</p>
          <p className="brk-doc">
            {doc.supplier} · {doc.amount} {doc.currency}
          </p>

          <label className="brk-field">
            <span className="stopped-label">The line you are adding to it</span>
            <textarea
              value={text}
              rows={3}
              onChange={(e) => { setText(e.target.value); setResult(null); }}
              placeholder="Write anything you think would get a payment through."
            />
          </label>

          <div className="brk-actions">
            <InkButton shortcut="1" onClick={() => void run()} disabled={running || !text.trim()}>
              {running ? "Running…" : "Run it against the real system"}
            </InkButton>
          </div>

          {error ? <p className="verdict-refused" role="alert">{error}</p> : null}

          {result ? (
            <div className="brk-result">
              <p className={`brk-verdict ${result.stopped ? "" : "is-through"}`}>
                {result.would_have_paid}
              </p>

              <ol className="brk-steps">
                {/* `passed` is the source of truth for which check caught it. The
                    response also carries `stopped_at`, but it is 0-indexed and reading
                    it as 1-indexed badged a check that PASSED as the one that stopped
                    the attack — the screen pointing at the wrong control is worse than
                    it showing no chain at all. */}
                {result.steps.map((step, i) => {
                  const failedAt = result.steps.findIndex((s) => !s.passed);
                  const stoppedHere = !step.passed;
                  const afterTheStop = failedAt !== -1 && i > failedAt;
                  return (
                    <li
                      key={step.key}
                      className={
                        stoppedHere ? "is-stop" : afterTheStop ? "is-skipped" : "is-pass"
                      }
                    >
                      <span className="brk-step-n">{i + 1}</span>
                      <span className="brk-step-name">
                        {step.name}
                        {stoppedHere ? " — stopped here" : ""}
                      </span>
                      <span className="brk-step-detail">{step.detail}</span>
                    </li>
                  );
                })}
              </ol>
            </div>
          ) : null}
        </div>
      </Arrive>

      <KeyRail
        actions={[
          { key: "1", label: "Run it", onPress: () => void run() },
          { key: "2", label: "Another line to try", onPress: nextExample },
          { key: "3", label: "Another invoice", onPress: () => { setAt((n) => n + 1); setResult(null); } },
        ]}
        escape={{ label: "Done", onPress: () => onDone?.() }}
      />
    </section>
  );
}
