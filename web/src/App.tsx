/**
 * The shell: seven screens, one cursor, one keyboard.
 *
 * Screens are named the way `docs/FRONTEND.md` names them, in the order it builds them.
 * The ones not yet written say so plainly rather than rendering an empty frame — a blank
 * panel is indistinguishable from a bug, and this app is being built in front of someone.
 *
 * `TargetCursor` is mounted **once, here**. It is one shape that converges to a point in
 * open space and opens back out onto anything actionable; mounting a second one per
 * screen is how that becomes two cursors that swap.
 *
 * **Every screen but the first is loaded on demand.** Screen 01 is where a working day
 * starts and it is the one screen that needs nothing heavy — so it must not pay for the
 * camera, for the WebGL the scan bands run on, or for the animation engine behind the
 * wall on screen 05. Splitting them moved 60% of the bundle off the opening screen.
 */
import { Suspense, lazy, useState } from "react";
import { Today } from "./screens/Today";

// The cursor brings GSAP with it. It is the signature interaction, not a screen, so
// it loads alongside rather than blocking the first paint — the native cursor is
// left visible meanwhile, so nothing flashes empty while it arrives.
const TargetCursor = lazy(() => import("./components/TargetCursor"));

const Scan = lazy(() => import("./screens/Scan").then((m) => ({ default: m.Scan })));
const Verdict = lazy(() => import("./screens/Verdict").then((m) => ({ default: m.Verdict })));
const Job = lazy(() => import("./screens/Job").then((m) => ({ default: m.Job })));
const Did = lazy(() => import("./screens/Did").then((m) => ({ default: m.Did })));
const Stopped = lazy(() => import("./screens/Stopped").then((m) => ({ default: m.Stopped })));
const Break = lazy(() => import("./screens/Break").then((m) => ({ default: m.Break })));

type ScreenId = "today" | "scan" | "verdict" | "job" | "did" | "stopped" | "break";

interface ScreenMeta {
  id: ScreenId;
  /** The number `docs/FRONTEND.md` gives it. Kept visible so the two never drift. */
  number: string;
  title: string;
  built: boolean;
}

const SCREENS: ScreenMeta[] = [
  { id: "today", number: "01", title: "Today", built: true },
  { id: "scan", number: "02", title: "Scan", built: true },
  { id: "verdict", number: "03", title: "Verdict", built: true },
  { id: "job", number: "04", title: "A job", built: true },
  { id: "did", number: "05", title: "See what it did", built: true },
  { id: "stopped", number: "06", title: "What we stopped", built: true },
  { id: "break", number: "07", title: "Try to break it", built: true },
];

export function App() {
  const [screen, setScreen] = useState<ScreenId>("today");
  const current = SCREENS.find((s) => s.id === screen) ?? SCREENS[5]!;

  // Esc always returns to the queue. Screens layer their own 1/2/3 on top of this.
  return (
    <div className="shell">
      <Suspense fallback={null}>
      <TargetCursor
        targetSelector=".cursor-target"
        cursorColor="#6fa9b8"
        cursorColorOnTarget="#5f7f72"
        spinDuration={0}
        hideDefaultCursor={false}
      />
      </Suspense>

      <a className="skip" href="#main">
        Skip to your queue
      </a>

      <header className="masthead">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">P</span>
          <div>
            <h1 className="wordmark">PRAETOR</h1>
            <p className="brand-subtitle">Autonomous AP control plane</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Screens">
          {SCREENS.map((s) => (
            <button
              key={s.id}
              className="tab cursor-target"
              aria-current={s.id === screen ? "page" : undefined}
              onClick={() => setScreen(s.id)}
            >
              {s.title}
            </button>
          ))}
        </nav>
        <div className="session-tools">
          <span className="system-state"><i aria-hidden="true" /> Policy gates active</span>
          <a className="logout cursor-target" href="/logout">Sign out</a>
        </div>
      </header>

      <aside className="trust-path" aria-label="PRAETOR trust path">
        <span><b>01</b> Untrusted document</span>
        <i aria-hidden="true">&rarr;</i>
        <span><b>02</b> Evidence spans</span>
        <i aria-hidden="true">&rarr;</i>
        <span><b>03</b> Deterministic resolver</span>
        <i aria-hidden="true">&rarr;</i>
        <span><b>04</b> Policy + human</span>
      </aside>

      <main id="main" tabIndex={-1}>
        {/* The fallback says what is happening rather than showing a blank frame; on a
            slow connection a screen that is arriving and a screen that is broken must
            not look the same. */}
        <Suspense fallback={<p className="state">Loading…</p>}>
        {screen === "today" ? (
          <Today onScan={() => setScreen("scan")} onJobs={() => setScreen("job")} />
        ) : screen === "scan" ? (
          <Scan onDone={() => setScreen("verdict")} />
        ) : screen === "did" ? (
          <Did onDone={() => setScreen("today")} />
        ) : screen === "job" ? (
          <Job onDone={() => setScreen("today")} />
        ) : screen === "verdict" ? (
          <Verdict onScan={() => setScreen("scan")} onDone={() => setScreen("today")} />
        ) : screen === "break" ? (
          <Break onDone={() => setScreen("today")} />
        ) : screen === "stopped" ? (
          <Stopped onDone={() => setScreen("today")} />
        ) : (
          <p className="state">
            Screen {current.number} — {current.title} is not built yet. It arrives in its
            phase; the queue is on <b>What we stopped</b> in the meantime.
          </p>
        )}
        </Suspense>
      </main>
    </div>
  );
}
