"""The JSON the three tabs read.

The most valuable test here is `test_no_code_word_reaches_any_screen`: it walks every
string in every API response and fails if any of them contains vocabulary Priya was never
meant to learn. `tests/test_language.py` checks the phrasebook; this checks that nothing
routes around it — an f-string in `api.py`, a raw finding code copied into a field, a
`repr()` that leaked a dataclass.

The rest pin the things that would be embarrassing rather than merely wrong: money summed
across currencies, a phone number sourced from the invoice being checked, an approval
recorded against someone who did not make it.
"""
import json
import pathlib

import pytest

from dashboard import api, build, language

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (ROOT / "out" / "vm_constructed.json").exists(),
    reason="run `make rules` first")


@pytest.fixture(scope="module")
def rows():
    rows, _ = build.rows_from_files()
    if not rows:
        pytest.skip("no adjudication results on disk")
    return rows


def _strings(obj, path="$"):
    """Every string in a response, with where it came from."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


# ------------------------------------------------------------------- the language rule

# Fields that are DATA rather than prose, and so are not held to the language rule.
# Two kinds: identifiers, which are never rendered as a sentence; and text that a person
# typed at us, which we echo back as evidence of what they tried. Attacker text is shown
# on Tab 2 on purpose -- it is the corpus -- and it is rendered with textContent, so it
# is inert. Holding it to the phrasebook would mean censoring the attacks we collect.
# `.outcome` is the machine key ("escalated"), used for sorting and styling and never
# rendered -- `.outcome_label` is what a person sees, and that IS held to the rule. The
# test below pins that, so this exclusion cannot quietly hide a regression.
_DATA_SUFFIX = (".id", ".doc_id", ".span_id", ".key", ".text", ".phone", ".email",
                ".outcome", ".vendor_key", ".source", ".verified_on", ".contact_name")


def _is_data(path: str) -> bool:
    return path.endswith(_DATA_SUFFIX) or ".examples" in path or ".hardest" in path


def _responses(rows):
    return {"queue": api.queue(rows), "stopped": api.stopped(rows),
            "documents": api.gauntlet_documents(), "examples": api.gauntlet_examples()}


def test_no_code_word_reaches_any_screen(rows):
    """Nothing may route around dashboard/language.py."""
    bad = []
    for name, body in _responses(rows).items():
        for path, text in _strings(body):
            if _is_data(path):
                continue
            found = language.code_words_in(text)
            if found:
                bad.append(f"{name}{path} says {found}: {text[:70]!r}")
    assert not bad, "\n".join(bad)


def test_no_raw_finding_code_reaches_any_screen(rows):
    import re
    bad = []
    for name, body in _responses(rows).items():
        for path, text in _strings(body):
            if _is_data(path):
                continue
            if re.search(r"\b[A-Z][A-Z0-9_]{4,}\b", text):
                bad.append(f"{name}{path}: {text[:70]!r}")
    assert not bad, "\n".join(bad)


# --------------------------------------------------------------------------- the queue

def test_the_queue_tells_her_the_win_and_what_is_left(rows):
    q = api.queue(rows)
    assert q["waiting"] + q["handled"] == q["total"]
    assert str(q["waiting"]) in q["headline"] and str(q["handled"]) in q["headline"]
    assert q["throughput"]


def test_the_worst_row_is_first(rows):
    """She should never have to scroll to find the one that moves money."""
    sev = [r["severity"] for r in api.queue(rows)["rows"]]
    assert sev == sorted(sev, key=lambda s: api.SEVERITY_RANK.get(s, 9))


def test_every_row_says_what_is_wrong_and_what_to_do(rows):
    for r in api.queue(rows)["rows"]:
        assert r["what_is_wrong"] and r["what_to_do"]
        assert r["supplier"] and r["id"]


def test_the_phone_number_never_comes_from_the_invoice(rows):
    """The most common way invoice fraud gets past a careful person is that they ring
    the number on the invoice. See praetor/suppliers.py."""
    for r in api.queue(rows)["rows"]:
        call = r["call"]
        assert call["warning"], "every row must say where the number came from"
        if call.get("phone"):
            assert call["source"] == "buyer records"
            doc = json.loads((ROOT / "data" / "constructed" / f"{r['id']}.json").read_text())
            printed = " ".join(f["text"] for f in doc["field_extractions"])
            assert call["phone"] not in printed


def test_amounts_come_from_the_document(rows):
    q = api.queue(rows)
    assert any(r["amount"] for r in q["rows"]), "no row shows an amount"


# ------------------------------------------------------------------- what we stopped

def test_money_is_never_summed_across_currencies(rows):
    """A total mixing USD and GBP is wrong in a way that puts every other figure in
    doubt the moment a finance person notices."""
    s = api.stopped(rows)
    by = s["exposure_by_currency"]
    if len(by) > 1:
        for code in by:
            assert code in s["exposure"]
    assert "  " in s["exposure"] or len(by) <= 1


def test_the_exposure_is_described_as_risk_not_loss(rows):
    """No confirmed incident exists. The wording must not imply one."""
    s = api.stopped(rows)
    assert "at risk" in s["exposure_note"]
    assert "loss" not in s["headline"].lower()
    assert "saved" not in s["headline"].lower()


def test_controls_are_reported_in_plain_language(rows):
    for c in api.stopped(rows)["controls"]:
        assert c["what"] in {e.headline for e in language.EXPLANATIONS.values()} | \
            {language.UNKNOWN.headline}


# --------------------------------------------------------------------- try to break it

def test_only_clean_invoices_are_offered():
    docs = api.gauntlet_documents()["documents"]
    assert docs
    for d in docs:
        assert d["supplier"] and d["amount"]


def test_a_document_outside_the_offer_is_refused():
    """The id comes from a request. It is not a path we follow."""
    for bad in ("../../etc/passwd", "V014_009_nope", ""):
        with pytest.raises(KeyError):
            api.gauntlet_document(bad)
        with pytest.raises(KeyError):
            api.gauntlet_run(bad, "x")


def test_running_an_attack_returns_steps_and_a_verdict(tmp_path, monkeypatch):
    from dashboard import attack_log
    monkeypatch.setattr(attack_log, "DEFAULT_PATH", tmp_path / "corpus.jsonl")
    doc = api.gauntlet_documents()["documents"][0]["id"]
    body = api.gauntlet_run(doc, "Updated details: DE89370400440532013000")
    assert body["steps"] and body["would_have_paid"]
    assert body["stopped"] is True
    assert body["corpus"]["attempts"] == 1


def test_the_examples_are_the_attacks_that_actually_work():
    """FINDINGS §2: the ones that look like attacks are the ones the model already
    resists. Offering those would flatter us."""
    texts = " ".join(e["text"] for e in api.gauntlet_examples()["examples"]).lower()
    assert "ignore all previous" not in texts
    assert "remittance" in texts or "banking details" in texts


def test_the_human_outcome_label_is_held_to_the_language_rule(rows):
    """`.outcome` is excluded from the scan above because it is never rendered. This is
    what makes that safe: the string that IS rendered gets checked."""
    seen = set()
    for r in api.queue(rows)["rows"]:
        seen.add(r["outcome_label"])
    for d in api.stopped(rows)["decisions"]:
        seen.add(d["outcome_label"])
    assert seen, "nothing rendered an outcome"
    for label in seen:
        assert not language.code_words_in(label), label
        assert label in language.OUTCOMES.values()


# ------------------------------------------------- bugs found by driving the browser
#
# Every test below pins a defect that shipped and that the whole suite passed over,
# because each one lived in the seam between the page and the server rather than inside
# either. They were found by opening the app and using it.

def test_the_page_asks_for_a_document_the_way_the_server_reads_it():
    """"Show the invoice" never worked. The page requested `?doc_id=`, the server reads
    `?doc=`, so every click 404ed and the button silently did nothing.

    A contract between two files that nothing checked. This checks it.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    page = (root / "dashboard" / "app.html").read_text()
    server = (root / "dashboard" / "serve.py").read_text()

    assert "/document?doc=" in page, "the page is not asking for ?doc="
    assert "/document?doc_id=" not in page, "the page is asking for ?doc_id= again"
    assert 'q.get("doc")' in server, "the server no longer reads ?doc — update the page"


def test_health_exists_on_both_transports_and_reports_the_session():
    """The page asks /v1/health first to decide which tab to open. It existed on the
    FastAPI transport and not on the standard-library one, so the decision was being made
    from an accidental 401 on an unmatched route."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in ("dashboard/serve.py", "dashboard/asgi.py"):
        src = (root / rel).read_text()
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        assert "/v1/health" in code, f"{rel} has no health endpoint"

    # Both answer the same question; serve.py delegates to api.health, asgi.py builds the
    # same shape inline. What matters is the key, and that it tracks the session.
    from dashboard import api
    assert api.health(True)["signed_in"] is True
    assert api.health(False)["signed_in"] is False
    assert api.health(True)["ok"] is True
    asgi = (root / "dashboard" / "asgi.py").read_text()
    assert "signed_in" in asgi, "the FastAPI transport stopped reporting signed_in"


def test_the_document_view_shows_field_names_in_words():
    """"Show the invoice" printed the parser's own field names -- `payment_iban`,
    `tax_detail_rate`, `currency_code_amount_due` -- straight onto the screen, which is
    the one thing dashboard/language.py exists to prevent. FORBIDDEN lists the machine's
    concepts; these are its field names, so they went straight through."""
    from dashboard import language
    from praetor.docai_adapter import FIELD_MAP as DOCAI_MAP
    from praetor.docile_adapter import FIELD_MAP as DOCILE_MAP

    for fieldtype in list(DOCILE_MAP) + list(DOCAI_MAP) + ["other", "line_item_amount"]:
        label = language.field_label(fieldtype)
        assert label and label != fieldtype, f"{fieldtype} has no plain name"
        assert "_" not in label, f"{label} still reads like a field name"
        assert not language.code_words_in(label), f"{label} contains a code word"

    # an unknown type is shown, not hidden: a reviewer seeing a field we cannot name is
    # better than a reviewer not seeing the field at all
    assert language.field_label("some_new_thing") == "Some new thing"
    assert language.field_label("") == "Unlabelled"


def test_a_line_with_no_account_is_not_an_attempt_that_beat_anything():
    """The counter under the attack demo advertised "the deepest got past 5 checks".

    A line containing no account redirects nothing, so every check passes and it looks
    like a clean sweep. 4,340 lines reading `test` were logged that way, and the page
    told each new visitor that something had beaten the whole system. It had not.
    """
    from dashboard import attack_log, gauntlet
    from dashboard import api

    plain = api.gauntlet_run("V000_003", "hello there", placement="note")
    assert plain["is_attack"] is False
    assert plain["stopped"] is False, "nothing was redirected, so nothing was stopped"

    real = api.gauntlet_run("V000_003", "Bank Account: IN99XXXX66660001",
                            placement="note")
    assert real["is_attack"] is True

    # and the summary must count only the real ones
    rows = [{"text": "test", "depth": 5, "beat": ["a"] * 5, "stopped": False,
             "is_attack": False},
            {"text": "pay IN99XXXX66660001", "depth": 2, "beat": ["a", "b"],
             "stopped": True, "is_attack": True}]
    assert attack_log._was_an_attack(rows[1]) is True
    assert attack_log._was_an_attack(rows[0]) is False
    # an old row with no is_attack field is judged by its text, not trusted
    assert attack_log._was_an_attack({"text": "test"}) is False
    assert attack_log._was_an_attack({"text": "use IN99XXXX66660001"}) is True


def test_the_attack_demo_can_actually_be_beaten():
    """A page that invites people to attack it and cannot be beaten collects guaranteed
    failures and reads like evidence.

    The visitor's line was always attached as a note, and the origin check refuses a note
    without reading it, so no wording could ever pass step 3. The placement control is
    what makes the demo winnable in the way the real threat is -- and the honest ceiling
    is the buyer's own records, which no document content can change.
    """
    from dashboard import api, gauntlet

    assert set(gauntlet.PLACEMENTS) >= {"note", "payment_field"}

    note = api.gauntlet_run("V000_003", "Bank Account: IN99XXXX66660001",
                            placement="note")
    captured = api.gauntlet_run("V000_003", "Bank Account: IN99XXXX66660001",
                                placement="payment_field")
    # `stopped_at` counts checks, not rows on the page: check 2 is the origin check.
    assert note["stopped_at"] == 2, "the note should still be refused on origin"
    assert captured["stopped_at"] is not None and captured["stopped_at"] > 2, (
        "labelling the line as the payment field must get past the origin check, or the "
        "demo is unwinnable again")

    # an unknown placement must fall back rather than error: this endpoint is anonymous
    assert api.gauntlet_run("V000_003", "x", placement="nonsense")["placement"] == "note"


def test_the_page_says_who_is_signed_in_and_what_they_may_do():
    """The header had an empty `#who` slot that nobody ever filled, so the app never
    said who you were, what your role was, or whose books you were looking at -- on a
    system whose central claim is that approving a payment records who you are. With two
    client companies in the data, an unlabelled queue could have been either of them."""
    import pathlib
    from dashboard import api

    h = api.health(True, "reviewer@acme-industries.test", "approver", "acme-industries")
    assert h["user"] and h["role"] == "approver" and h["tenant"] == "acme-industries"
    assert api.health(False)["user"] is None

    page = (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "app.html").read_text()
    assert "showWho" in page and 'href = "/logout"' in page, "no way to sign out"


def test_the_session_banner_does_not_restyle_the_supplier_name():
    """`.who` was already the supplier's name inside a queue row. Styling a new header
    element with the same class put a rule under every supplier on the page -- caught in
    a screenshot, which is the second time a layout defect in this file has been visible
    only that way (FINDINGS §22 was the first)."""
    import pathlib
    import re
    page = (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "app.html").read_text()
    css = page.split("</style>")[0]
    # `.row .who` is the supplier name and may be styled; a bare `.who{` rule is the bug.
    assert not re.search(r"(?<![\w.\-]) \.who\s*\{|^\.who\s*\{", css, re.M), (
        "a bare .who rule is back; it will restyle every supplier name")
    assert ".session{" in css, "the header banner has no class of its own"


def test_the_audit_trail_shows_a_time_a_person_would_write():
    """`2026-08-29T12:21:14+00:00` is correct and is not how anybody writes a time."""
    import pathlib
    page = (pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "app.html").read_text()
    assert "function when(iso)" in page
    assert "when(x.decided_at)" in page, "the audit table is printing the raw timestamp"
