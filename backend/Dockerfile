FROM python@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS runtime
WORKDIR /app
COPY backend/requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
 && groupadd --gid 10003 axiom-raw \
 && groupadd --gid 10004 axiom-journal \
 && useradd --create-home axiom \
 && usermod --append --groups axiom-raw axiom \
 && useradd --uid 10002 --gid 10003 --no-create-home --shell /usr/sbin/nologin axiom-evaluator \
 && useradd --uid 10004 --gid 10004 --no-create-home --shell /usr/sbin/nologin axiom-journal \
 && install -d --owner axiom --group axiom-raw --mode 2750 /var/lib/axiom/objects \
 && install -d --owner axiom-evaluator --group axiom-raw --mode 700 /var/lib/axiom/sealed /var/lib/axiom/sealed-keys \
 && install -d --owner axiom-journal --group axiom-journal --mode 700 /var/lib/axiom/journal /var/lib/axiom/authority \
 && install -d --owner axiom-journal --group axiom-raw --mode 2750 /var/lib/axiom/socket
COPY backend/ /app/
COPY docs/企劃案/contracts/*.schema.json /app/contracts/
COPY docs/企劃案/contracts/openapi-v2.json docs/企劃案/contracts/dsl-v1.examples.json /app/contracts/
USER axiom
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]

# Coverage uses the same runtime dependencies and real PostgreSQL guards, but
# instrumentation stays in an explicit build target, outside production images.
FROM runtime AS coverage
USER root
COPY tools/coverage/requirements.lock /tmp/coverage-requirements.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /tmp/coverage-requirements.lock
WORKDIR /workspace
COPY backend/ backend/
COPY docs/企劃案/contracts/ backend/contracts/
COPY .coveragerc .coveragerc
RUN install -d --owner axiom --group axiom reports
USER axiom

FROM runtime AS production
