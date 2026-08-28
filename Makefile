# PRAETOR
#
#   make install    create .venv and install dependencies
#   make test       run the invariants (no API key, no network)
#   make demo       full offline demo: rules baseline + review dashboard
#   make db         load results into SQLite (tenants, users, approvals)
#   make serve      the review queue with live approvals (http://127.0.0.1:8000)
#   make api        the same contract on FastAPI: paging, live updates, uploads
#   make web        build the React app (needs node); make api then serves it
#   make trace      run the kernel with tracing on and print one document's spans
#   make readpath   the real path end to end: reader -> resolver -> rules (free)
#   make volume     5,000 documents through the kernel: throughput and concurrency
#   make pathb      fit the second extraction path, then try to break it
#   make tenancy    two client companies, shared suppliers, and the refusal network
#   make queue      what the queue ordering has learned (currently: nothing)
#   make ingest     the automated front door, offline and free
#   make load       the deployed surface under concurrent load
#   make tf-check   the infrastructure as code: format, init, validate
#   make verify     everything that needs no API key, end to end
#
# Targets that spend nothing are the default. The three that call the Gemini API
# (attacks, adjudicate, twopath) are never run by `demo` or `verify`, and all are
# capped by praetor/costguard.py. `armor` calls Google Model Armor, which is free.

PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
RUN := PYTHONPATH=. $(PY)

.PHONY: help install test demo verify corpus rules db dashboard serve trace readpath canary pathb app pdf volume attacks adjudicate twopath armor ingest tenancy queue api web web-test load tf-check tf-plan diagram clean

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

# Throughput and concurrency for the deterministic kernel. Generates its own corpus
# under out/volume the first time. No API calls, so it costs nothing.
volume:
	$(RUN) eval/run_volume.py --docs $(DOCS)

DOCS ?= 5000

# The real path end to end: quarantined reader -> resolver -> rules. Free on local
# Gemma; add --remote to use Gemini instead (one call per document, capped by costguard).
readpath:
	$(RUN) eval/run_readpath.py --limit $(N)

canary:
	$(RUN) eval/run_canary.py

# The second extraction path: fit it (held out by layout) and then try to break it.
# Deterministic, no model, no network. FINDINGS sec 16 and 17.
pathb:
	$(RUN) eval/train_pathb.py
	@echo
	$(RUN) eval/run_pathb_stress.py

# The front door: a real PDF becomes spans the kernel accepts. DECISIONS.md #9.
# DOC=V000_003 picks the invoice; --cached re-uses a saved response and charges nothing.
PDFDOC ?= V000_003
pdf:
	$(RUN) eval/make_invoice_pdf.py $(PDFDOC)
	$(RUN) eval/run_pdf.py out/pdf/$(PDFDOC).pdf

# The three tabs: Priya's queue, what we stopped, and try to break it.
# Nothing is baked into the page -- it reads /v1/* on every request.
app: db
	@echo "open http://127.0.0.1:8000/app  (sign in, password: praetor)"
	$(RUN) dashboard/serve.py

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

# The React app. Needs node; `make serve` and its plain /app page do not, which is why
# both exist. Output goes to web/dist, which is gitignored: it is derived.
web:
	cd web && npm install --no-audit --no-fund && npm run build
	@echo "\nBuilt. `make api` will serve it at http://127.0.0.1:8000/"

# Frontend tests: behaviour, keyboard, and an axe accessibility pass.
web-test:
	cd web && npm test

# The FastAPI transport: same JSON as `make serve`, plus paging, live updates and
# uploads, with OpenAPI at /v1/docs. `make serve` remains the zero-dependency path.
api: db
	@echo "open http://127.0.0.1:8000/v1/docs"
	$(RUN) dashboard/asgi.py

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

# The headline of phase 3: all 20 payloads against BOTH extraction paths, on the same
# spans of the same document. 100 model calls, about Rs 8. Resumable.
twopath:
	$(RUN) eval/run_twopath.py --delay 2

# The moat: a second client company, the isolation claim measured on real documents,
# and what the refusal network is and is not allowed to do. Free, no model.
tenancy: 
	$(RUN) eval/make_tenant_b.py
	@echo
	$(RUN) eval/run_tenancy.py

# What the queue ordering has learned from decisions people actually made.
queue:
	$(RUN) eval/run_queue.py

# The automated front door, run locally on a saved Document AI response: no network,
# no credentials, no charge. This is the exact path the Cloud Run ingest service runs.
ingest:
	$(RUN) -c "from ingest import pipeline; \
	o = pipeline.process(b'', 'V000_003', \
	    analyse=pipeline.cached_analyser('tests/fixtures/docai_V000_003.json'), \
	    charge=False); \
	print(f'action={o.action} codes={o.codes} spans={o.spans} hash={o.doc_hash}')"

# What the deployed surface does under concurrent load. Needs `make api` running in
# another shell. Raise PRAETOR_READ_LIMIT on that server to measure capacity rather than
# measuring the rate limiter.
load:
	$(RUN) eval/run_load.py --requests $(N)

# ---------------------------------------------------------------- infrastructure

# Everything the cloud runs on, as code. tf-check needs no credentials; tf-plan is read
# only and talks to the real project. There is deliberately no `apply` target -- read the
# plan first, every time. See terraform/README.md.
tf-check:
	terraform -chdir=terraform fmt -check
	terraform -chdir=terraform init -backend=false -input=false >/dev/null
	terraform -chdir=terraform validate

tf-plan: tf-check
	terraform -chdir=terraform init -input=false >/dev/null
	terraform -chdir=terraform plan -input=false -lock=false

# ------------------------------------------------------- needs gcloud, costs nothing

# The 20 payloads through Google Model Armor, three templates, two framings. Turns
# DECISIONS #1 from an assertion into a measurement. Free to 2M tokens/month.
#   gcloud services enable modelarmor.googleapis.com --project praetor-run-2026
armor:
	$(RUN) eval/run_model_armor.py

# ---------------------------------------------------------------- docs

# Needs Pillow, which is not a runtime dependency:  pip install Pillow
diagram:
	@$(PY) -c "import PIL" 2>/dev/null || { echo "needs Pillow: pip install Pillow"; exit 1; }
	$(PY) docs/render.py architecture.html architecture.png

clean:
	rm -rf .pytest_cache **/__pycache__ out/spend.json out/*.lock out/trace.jsonl
