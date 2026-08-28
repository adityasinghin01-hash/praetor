# PRAETOR on Cloud Run. One image, two services.
#
#   dashboard/serve.py   the review queue          (default CMD)
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

# Cloud Run sets $PORT and expects the container to listen on 0.0.0.0.
EXPOSE 8080
CMD ["python", "dashboard/serve.py"]
