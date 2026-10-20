FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
WORKDIR /app
COPY backend/requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /tmp/requirements.lock && useradd --create-home axiom && mkdir -p /var/lib/axiom/objects && chown axiom:axiom /var/lib/axiom/objects && chmod 700 /var/lib/axiom/objects
COPY backend/ /app/
COPY docs/企劃案/contracts/*.schema.json /app/contracts/
COPY docs/企劃案/contracts/openapi-v2.json docs/企劃案/contracts/dsl-v1.examples.json /app/contracts/
USER axiom
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]
