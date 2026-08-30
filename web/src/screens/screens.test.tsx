/**
 * The guarantees that outlived the queue.
 *
 * `Queue.tsx` was deleted with this phase — it was the data dump the rebuild exists to
 * replace, and its eighteen tests covered two different things at once. Half were about
 * *that* screen's navigation: `j`/`k` down a list, `/` to a search box, Enter to open a
 * row. None of those controls exist any more; the app is `1` `2` `3` and `Esc`, one card
 * at a time, and porting those tests would have been pinning a design nobody is building.
 *
 * The other half were not about the queue at all. Severity must never be carried by
 * colour alone. No sentence about a finding may be composed in the browser. The
 * machine's vocabulary must not reach a person. The caret must not be stolen on load, or
 * while she is typing. The phone number must say where it came from. An error must not
 * show a status code. Those are promises about the product, and they are re-made here
 * against the screens that ship.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Verdict } from "./Verdict";
import { Today } from "./Today";
import { Job } from "./Job";
import { Did } from "./Did";
import { Stopped } from "./Stopped";
import { Break } from "./Break";
import type { QueueResponse, QueueRow } from "../types";

function row(over: Partial<QueueRow> = {}): QueueRow {
  return {
    id: "V000_004",
    supplier: "Meridian Supply Co.",
    amount: "48,200.00",
    currency: "EUR",
    what_is_wrong: "New bank account. You have never paid this supplier here before.",
    what_to_do: "Call the supplier on the number in your own records.",
    severity: "stop",
    also: [],
    call: {
      name: "Anja Bakker",
      phone: "+31 20 555 1234",
      source: "buyer records",
      warning: "This is the number in your own records, not the one on the invoice.",
    },
    invoices_seen_before: 9,
    outcome: "escalated",
    outcome_label: "Waiting for someone to look",
    system_said: "This needs a person to decide.",
    decided_by: null,
    decided_at: null,
    amount_sort: 48200,
    evidence: [
      {
        kind: "account",
        field: "Bank account",
        on_invoice: "LT12 1000 0111 0100 1000",
        in_records: ["NL91 ABNA 0417 1643 00"],
        note: "You have 9 earlier invoices from this supplier, and none of them used this account.",
        seen_before: 9,
      },
    ],
    draft: null,
    canned_notes: [
      "I called them on the number in our records and they confirmed it.",
      "I could not reach them. Trying again tomorrow.",
      "Emailed them to confirm. Waiting for a reply.",
    ],
    ...over,
  };
}

function response(rows: QueueRow[]): QueueResponse {
  return {
    headline: `You have ${rows.length} invoices to look at today. The system handled the other 303.`,
    waiting: rows.length,
    handled: 303,
    total: 350,
    throughput: "86% of invoices went through without anyone touching them.",
    rows,
    page: {
      page: 1,
      per_page: 25,
      pages: 1,
      total_rows: rows.length,
      has_next: false,
      has_previous: false,
    },
  };
}

function answer(body: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() => answer(response([row()])));
  vi.stubGlobal("fetch", fetchMock);
  // The queue watches for changes over SSE. Nothing in these tests is about that.
  vi.stubGlobal("EventSource", undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function renderVerdict() {
  const view = render(<Verdict />);
  await waitFor(() => expect(screen.getByText(/New bank account/)).toBeInTheDocument());
  return view;
}

describe("severity", () => {
  it("is never carried by colour alone", async () => {
    // Roughly one man in twelve has some colour vision deficiency. A control that only
    // works for the other eleven is not a control.
    await renderVerdict();
    expect(screen.getByText(/Do not pay yet/)).toBeInTheDocument();
  });
});

describe("the words on screen", () => {
  it("renders the server's sentences and composes none of its own", async () => {
    await renderVerdict();
    expect(
      screen.getByText("New bank account. You have never paid this supplier here before."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Call the supplier on the number in your own records."),
    ).toBeInTheDocument();
  });

  it("shows no code words anywhere on screen", async () => {
    await renderVerdict();
    const text = (document.body.textContent ?? "").toLowerCase();
    // Whole words, never substrings -- mirroring dashboard/language.py::code_words_in.
    // "Northgate Components Ltd" is a real supplier and must not trip a check for
    // "gate"; a rule that cannot tell those apart gets switched off within a week.
    // tests/test_frontend.py fails if this list drifts from language.FORBIDDEN.
    for (const word of ["tainted", "taint", "span_id", "doc_hash", "resolver",
                        "adjudicate", "adjudication", "gate", "provenance", "injection",
                        "payload", "prompt", "llm", "tenant_id", "escalate", "escalated",
                        "privileged", "canary", "grounded", "heuristic", "classifier"]) {
      expect(text).not.toMatch(new RegExp(`\\b${word}\\b`));
    }
  });

  it("shows the phone number and says it is not from the invoice", async () => {
    // The most common way invoice fraud gets past a careful person is that they ring the
    // number printed on the invoice.
    await renderVerdict();
    expect(screen.getByText(/\+31 20 555 1234/)).toBeInTheDocument();
    expect(
      screen.getByText(/not the one on the invoice/),
    ).toBeInTheDocument();
  });
});

describe("the comparison", () => {
  it("shows what the invoice says beside what her records say", async () => {
    await renderVerdict();
    expect(screen.getByText("LT12 1000 0111 0100 1000")).toBeInTheDocument();
    expect(screen.getByText("NL91 ABNA 0417 1643 00")).toBeInTheDocument();
    expect(screen.getByText(/none of them used this account/)).toBeInTheDocument();
  });
});

describe("the keyboard", () => {
  it("does not steal the caret on load", async () => {
    // Grabbing focus drags a screen reader past the heading it was about to read.
    await renderVerdict();
    expect(document.activeElement).toBe(document.body);
  });

  it("does not steal keys while she is typing", async () => {
    // A digit typed into a field must reach the field, not file a decision.
    render(<Today />);
    await screen.findByText("Scan a page");

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    await userEvent.keyboard("1");

    expect(input.value).toBe("1");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/v1/decisions")))
      .toBe(false);
    input.remove();
  });

  it("records a decision when she presses a key", async () => {
    await renderVerdict();
    await userEvent.keyboard("1");
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/v1/decisions")))
        .toBe(true));
  });
});

describe("failure", () => {
  it("explains itself without showing a status code", async () => {
    // A number is not something anyone should have to look up to know what happened.
    fetchMock.mockImplementation(() => answer({ detail: "" }, false, 500));
    render(<Verdict />);
    const problem = await screen.findByText(/could not load your queue/i);
    expect(problem.textContent).not.toMatch(/\b500\b/);
  });

  it("puts the invoice back when the server refuses the decision", async () => {
    // 409 means somebody already decided this. The guard working is not an error to
    // swallow: she has to see that her keypress did not take.
    await renderVerdict();
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/v1/decisions")
        ? answer({ detail: "V000_004 was already approved by someone else" }, false, 409)
        : answer(response([row()])));

    await userEvent.keyboard("1");
    expect(await screen.findByRole("alert")).toHaveTextContent(/already approved/);
  });
});

describe("accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = await renderVerdict();
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },  // jsdom cannot compute colour
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });

  it("names the action beside every key rather than the key alone", async () => {
    // A key cap with no word next to it teaches nothing.
    await renderVerdict();
    const rail = document.querySelector(".ink-rail");
    expect(rail).toBeTruthy();
    expect(within(rail as HTMLElement).getByText("Confirmed")).toBeInTheDocument();
    expect(within(rail as HTMLElement).getByText("Fraud")).toBeInTheDocument();
  });
});

describe("every screen", () => {
  /**
   * The queue's axe test only ever covered the queue. Six screens were added after it
   * and none of them were checked, which is how a keyboard trap or an unnamed control
   * ships: not by anyone deciding to skip the check, but by the check never growing.
   *
   * Colour contrast is disabled here because jsdom cannot compute it. It is checked
   * separately in a real browser, where ink on paper passes AA on every screen.
   */
  function routed(url: string) {
    if (url.includes("/v1/cleared")) {
      return answer({
        cleared: 304, total: 350, judged: 18,
        headline: "304 invoices were paid without you having to look.",
        judged_note: "18 of those raised something.",
        spot_check_note: "Open any of them.",
        sample: [{ id: "V000_001", supplier: "Kestrel Materials Ltd",
                   amount: "1,204.00", currency: "EUR",
                   system_said: "We checked this one and it was fine." }],
      });
    }
    if (url.includes("/v1/stopped")) {
      return answer({
        headline: "We stopped 5 payments to accounts that were not the supplier's.",
        exposure: "EUR 1.00", exposure_by_currency: { EUR: 1 },
        exposure_note: "It is what was at risk, not a loss that happened.",
        payments_stopped: 5, ai_overruled: 2,
        ai_overruled_note: "Times the system was overruled.",
        controls: [{ what: "New bank account.", times: 5 }],
        decisions: [],
      });
    }
    if (url.includes("/v1/gauntlet/documents")) {
      return answer({ documents: [{ id: "V000_003", supplier: "Kestrel Materials Ltd",
                                    amount: "2,614.65", currency: "GBP" }] });
    }
    if (url.includes("/v1/gauntlet/examples")) {
      return answer({ examples: [{ label: "A remittance notice", text: "Please note our updated details." }] });
    }
    return answer(response([row()]));
  }

  it.each([
    ["screen 01, Today", () => <Today />, "Scan a page"],
    ["screen 03, Verdict", () => <Verdict />, "New bank account. You have never paid this supplier here before."],
    ["screen 04, A job", () => <Job />, "Already paid"],
    ["screen 05, See what it did", () => <Did />, /paid without you having to look/],
    ["screen 06, What we stopped", () => <Stopped />, /We stopped 5 payments/],
    ["screen 07, Try to break it", () => <Break />, /The invoice you are attacking/],
  ])("has no axe violations: %s", async (_name, mount, settled) => {
    fetchMock.mockImplementation((url: string) => routed(String(url)));
    const { container } = render(mount());
    await screen.findByText(settled as string | RegExp);

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

describe("a session that has ended", () => {
  it("does not offer a retry that cannot work", async () => {
    // 401 is not a blip. The request was fine and the session was not, so pressing the
    // same button again fails identically — offering it strands the person on a screen
    // whose only control is broken.
    fetchMock.mockImplementation(() => answer({ error: "not signed in" }, false, 401));
    render(<Verdict />);
    expect(await screen.findByText(/session has ended/i)).toBeInTheDocument();
    expect(screen.queryByText("Try again")).not.toBeInTheDocument();
    expect(screen.getByText("Sign in")).toBeInTheDocument();
  });

  it("still offers a retry for a failure that might pass next time", async () => {
    fetchMock.mockImplementation(() => answer({ detail: "" }, false, 500));
    render(<Verdict />);
    expect(await screen.findByText(/could not load your queue/i)).toBeInTheDocument();
    expect(screen.getByText("Try again")).toBeInTheDocument();
  });
});

describe("an impatient keypress", () => {
  it("files one decision however many times the key is hit", async () => {
    // A state flag cannot latch inside a single tick: `setBusy(true)` does not apply
    // until the next render, so every press in the same tick reads it as false. Six
    // requests went out for one invoice; the server refused five, and the screen then
    // told her the decision she had just made was "already approved" and put the
    // invoice back. The latch is a ref for exactly this reason.
    await renderVerdict();
    const calls = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).includes("/v1/decisions")).length;

    await userEvent.keyboard("111111");
    await waitFor(() => expect(calls()).toBeGreaterThan(0));
    expect(calls()).toBe(1);
  });
});
