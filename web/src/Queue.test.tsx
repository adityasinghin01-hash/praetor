/**
 * The queue, tested for the things that decide whether Priya can actually work it.
 *
 * Not "does it render" -- that fails loudly anyway. These pin the properties that fail
 * quietly: severity carried by more than colour, a keyboard path through the whole
 * queue, a dialog that gives the caret back, and no sentence composed here that should
 * have come from `dashboard/language.py`.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Queue } from "./Queue";
import type { QueueResponse, QueueRow } from "./types";

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
    call: { name: "Anja Bakker", phone: "+31 20 555 1234", source: "buyer records" },
    invoices_seen_before: 9,
    outcome: "escalated",
    outcome_label: "Waiting for someone to look",
    system_said: "This needs a person to decide.",
    decided_by: null,
    decided_at: null,
    amount_sort: 48200,
    ...over,
  };
}

function response(rows: QueueRow[], pages = 1): QueueResponse {
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
      pages,
      total_rows: rows.length,
      has_next: pages > 1,
      has_previous: false,
    },
  };
}

const ROWS = [
  row(),
  row({ id: "V001_002", supplier: "Northgate Components Ltd", severity: "check",
        what_is_wrong: "Much bigger than this supplier's normal invoice.",
        what_to_do: "Check there is a purchase order that covers this amount.",
        amount: "12,000.00", currency: "GBP" }),
  row({ id: "V002_007", supplier: "Kestrel Handel GmbH", severity: "check",
        what_is_wrong: "The tax rate is not the one this supplier normally charges.",
        what_to_do: "Check whether an exemption applies.",
        amount: "900.00", currency: "USD" }),
];

beforeEach(() => {
  vi.stubGlobal("EventSource", undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).startsWith("/v1/notes")) {
        return new Response(JSON.stringify({ notes: [] }), { status: 200 });
      }
      return new Response(JSON.stringify(response(ROWS)), { status: 200 });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

async function renderQueue() {
  render(<Queue />);
  await waitFor(() => expect(screen.getByRole("list", { name: /waiting/i })).toBeInTheDocument());
}

describe("severity", () => {
  it("is never carried by colour alone", async () => {
    await renderQueue();
    const items = screen.getAllByRole("listitem");
    // Roughly one man in twelve has some colour vision deficiency. Each row states its
    // urgency in words, so the information survives without the colour.
    expect(within(items[0]!).getByText("Do not pay yet")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Needs a look")).toBeInTheDocument();
  });

  it("keeps the worst first, in the order the server sent", async () => {
    await renderQueue();
    const suppliers = screen.getAllByRole("listitem").map(
      (li) => within(li).getByRole("button").textContent ?? "",
    );
    expect(suppliers[0]).toContain("Meridian Supply Co.");
    expect(suppliers[1]).toContain("Northgate Components Ltd");
  });
});

describe("the words on screen", () => {
  it("renders the server's sentences and composes none of its own", async () => {
    await renderQueue();
    // These strings are written in dashboard/language.py. If the frontend ever starts
    // paraphrasing, this is where it shows up.
    expect(
      screen.getByText("New bank account. You have never paid this supplier here before."),
    ).toBeInTheDocument();
    expect(screen.getByText(/The system handled the other 303/)).toBeInTheDocument();
  });

  it("shows no code words anywhere on screen", async () => {
    await renderQueue();
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
});

describe("the keyboard", () => {
  it("does not steal the caret on load", async () => {
    await renderQueue();
    // Grabbing focus on load drags a screen reader past the heading it was about to
    // read. Nothing moves unless she moved it.
    expect(document.body).toHaveFocus();
  });

  it("moves down and up the queue with j and k", async () => {
    await renderQueue();
    const buttons = screen.getAllByRole("button", { name: /Supply|Components|Handel/ });
    await userEvent.keyboard("j");
    expect(buttons[1]).toHaveFocus();
    await userEvent.keyboard("j");
    expect(buttons[2]).toHaveFocus();
    await userEvent.keyboard("k");
    expect(buttons[1]).toHaveFocus();
  });

  it("stops at the ends instead of wrapping", async () => {
    await renderQueue();
    const buttons = screen.getAllByRole("button", { name: /Supply|Components|Handel/ });
    await userEvent.keyboard("kkk");
    expect(buttons[0]).toHaveFocus();
    await userEvent.keyboard("jjjjjj");
    expect(buttons[2]).toHaveFocus();
  });

  it("jumps to the search box on /", async () => {
    await renderQueue();
    await userEvent.keyboard("/");
    expect(screen.getByRole("searchbox")).toHaveFocus();
  });

  it("does not steal keys while she is typing", async () => {
    await renderQueue();
    const search = screen.getByRole("searchbox");
    await userEvent.click(search);
    await userEvent.type(search, "jk");
    expect(search).toHaveValue("jk");
  });

  it("opens with Enter and closes with Escape", async () => {
    await renderQueue();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("the dialog", () => {
  it("gives the caret back to the row that opened it", async () => {
    await renderQueue();
    const buttons = screen.getAllByRole("button", { name: /Supply|Components|Handel/ });
    await userEvent.keyboard("j");           // move to the second row
    await userEvent.keyboard("{Enter}");
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    // Without this, working a queue by keyboard means starting from the top every time.
    await waitFor(() => expect(buttons[1]).toHaveFocus());
  });

  it("shows the phone number and says it is not from the invoice", async () => {
    await renderQueue();
    await userEvent.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("+31 20 555 1234")).toBeInTheDocument();
    expect(within(dialog).getByText(/not from the\s+invoice/i)).toBeInTheDocument();
  });

  it("keeps the caret inside while it is open", async () => {
    await renderQueue();
    await userEvent.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog");
    for (let i = 0; i < 12; i++) {
      await userEvent.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });
});

describe("search", () => {
  it("filters what is already on screen and fetches nothing", async () => {
    await renderQueue();
    const before = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.type(screen.getByRole("searchbox"), "Northgate");
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(before);
  });

  it("says so plainly when nothing matches", async () => {
    await renderQueue();
    await userEvent.type(screen.getByRole("searchbox"), "zzzzz");
    expect(await screen.findByText(/Nothing here matches/)).toBeInTheDocument();
  });
});

describe("failure", () => {
  it("explains itself without showing a status code", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ error: "not signed in" }), { status: 401 })));
    render(<Queue />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("not signed in");
    expect(alert.textContent).not.toMatch(/\b401\b/);
  });
});

describe("accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = render(<Queue />);
    await waitFor(() => expect(screen.getByRole("list", { name: /waiting/i })).toBeInTheDocument());
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },  // jsdom cannot compute colour
    });
    const problems = results.violations.map((v) => `${v.id}: ${v.help}`);
    expect(problems).toEqual([]);
  });

  it("labels the queue and announces how many are shown", async () => {
    await renderQueue();
    expect(screen.getByRole("list", { name: "Invoices waiting for you" })).toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toMatch(/3 invoices shown/);
  });
});
