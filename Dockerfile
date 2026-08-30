# PRAETOR on Cloud Run. One image, two services.
#
#   dashboard/asgi.py    the review queue          (default CMD)
#   ingest/server.py     the Eventarc ingest path  (deployed with --command/--args)
#
# The queue carries nothing that calls a model: adjudication is an offline script, so a
# deployed queue instance cannot burn API quota or spend money. That property is
# unchanged and still worth having, which is why the ingest path is a SEPARATE service
# rather than a route added to this one -- ingestion does spend, per page, and the two
# should not share a blast radius.
#
# State must be Firestore here. Cloud Run containers have an ephemeral filesystem, so a
# SQLite file would vanish on every cold start -- which is exactly why the store was put
# behind one interface with two backends.
# The React app is built here and copied in. `web/dist` is derived and gitignored, so
# without this stage the image ships no frontend at all and the queue falls back to the
# server-rendered page — which is what happened: nine phases of frontend, none of it
# deployable.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build


FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PRAETOR_BACKEND=firestore

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt google-cloud-firestore

COPY praetor/ praetor/
COPY dashboard/ dashboard/
COPY ingest/ ingest/
COPY eval/ eval/
COPY data/ data/
COPY results/ results/

# Built in the stage above. Only the output is copied — no node_modules, no sources.
COPY --from=web /web/dist/ web/dist/

# Cloud Run sets $PORT and expects the container to listen on 0.0.0.0.
EXPOSE 8080

# FastAPI, not the stdlib server. It serves the same JSON contract plus the three things
# the React app needs and `serve.py` does not have: the built assets, paging and uploads,
# and a way to sign in. `serve.py` stays in the image and stays tested — `make demo` runs
# it with nothing installed — it is simply not what a deployed queue runs any more.
CMD ["python", "dashboard/asgi.py"]
