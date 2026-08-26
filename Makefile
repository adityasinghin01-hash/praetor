# PRAETOR
#
#   make install    create .venv and install dependencies
#   make test       run the invariants (no API key, no network)
#   make demo       full offline demo: rules baseline + review dashboard
#   make db         load results into SQLite (tenants, users, approvals)
#   make serve      the review queue with live approvals (http://127.0.0.1:8000)
#   make trace      run the kernel with tracing on and print one document's spans
#   make readpath   the real path end to end: reader -> resolver -> rules (free)
#   make verify     everything that needs no API key, end to end
#
# Targets that spend nothing are the default. The two that call the Gemini API
# (attacks, adjudicate) are never run by `demo` or `verify`, and both are capped
# by praetor/costguard.py.

PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
RUN := PYTHONPATH=. $(PY)

.PHONY: help install test demo verify corpus rules db dashboard serve trace readpath attacks adjudicate diagram clean

help:
	@sed -n '2,10p' Makefile | sed 's/^# \?//'

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	@echo "\nReady. Next: make test"

# ---------------------------------------------------------------- no API key

test:
	$(RUN) -m pytest tests/ -q

corpus:
	$(RUN) eval/make_invoices.py --out data/constructed --per-vendor 14

rules:
	$(RUN) eval/build_vendor_master.py --annotations data/constructed --out out/vm_constructed.json
	$(RUN) eval/find_exceptions.py --master out/vm_constructed.json \
		--annotations data/constructed --out out/exc_constructed.jsonl
	$(RUN) eval/run_eval.py --truth data/constructed_truth.jsonl \
		--predictions out/exc_constructed.jsonl

# The real path end to end: quarantined reader -> resolver -> rules. Free on local
# Gemma; add --remote to use Gemini instead (one call per document, capped by costguard).
readpath:
	$(RUN) eval/run_readpath.py --limit $(N)

N ?= 25

# Re-run the rules over the corpus with tracing on, then print one document's spans.
# Costs nothing and needs no API key: the traced path is the deterministic kernel.
trace:
	@rm -f out/trace.jsonl
	PRAETOR_TRACE=1 $(RUN) eval/find_exceptions.py --master out/vm_constructed.json \
		--annotations data/constructed --out out/exc_constructed.jsonl >/dev/null
	$(RUN) eval/show_trace.py --doc $(DOC)

DOC ?= V014_009

# Load the file-based results into SQLite: tenants, users, documents, findings,
# adjudications and purchase orders. Approvals are never touched by a re-import.
db:
	$(RUN) eval/build_db.py

dashboard:
	$(RUN) dashboard/build.py
	@echo "open dashboard/index.html"

# The queue with working approvals. Calls the real praetor.gate.approve().
serve: db
	$(RUN) dashboard/serve.py

demo: test rules dashboard
	@echo
	@echo "Done. Every number above came from a results file, not from this Makefile."
	@echo "Open dashboard/index.html for the queue a human actually works."

# Regenerates the corpus first, to prove it is reproducible bit-for-bit.
verify: corpus demo

# ---------------------------------------------------------------- needs GOOGLE_API_KEY

attacks:
	$(RUN) eval/measure_attacks.py --out out/attacks_undefended.jsonl --delay 6

adjudicate:
	$(RUN) eval/run_adjudication.py

# ---------------------------------------------------------------- docs

# Needs Pillow, which is not a runtime dependency:  pip install Pillow
diagram:
	@$(PY) -c "import PIL" 2>/dev/null || { echo "needs Pillow: pip install Pillow"; exit 1; }
	$(PY) docs/render.py architecture.html architecture.png

clean:
	rm -rf .pytest_cache **/__pycache__ out/spend.json out/*.lock out/trace.jsonl
