import { useState } from "react";
import { Queue } from "./Queue";

type Tab = "queue" | "stopped";

export function App() {
  const [tab, setTab] = useState<Tab>("queue");

  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to your queue
      </a>

      <header className="masthead">
        <h1 className="wordmark">PRAETOR</h1>
        <nav className="tabs" aria-label="Views">
          <button
            className="tab"
            aria-current={tab === "queue" ? "page" : undefined}
            onClick={() => setTab("queue")}
          >
            Your queue
          </button>
          <button
            className="tab"
            aria-current={tab === "stopped" ? "page" : undefined}
            onClick={() => setTab("stopped")}
          >
            What we stopped
          </button>
        </nav>
      </header>

      <main id="main" tabIndex={-1}>
        {tab === "queue" ? (
          <Queue />
        ) : (
          <p className="state">
            This view is being rebuilt. Use your queue in the meantime.
          </p>
        )}
      </main>
    </div>
  );
}
