"""Run disposable T02 compatibility probes; this is not a product test suite."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
import hashlib
from importlib import import_module, metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Literal
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_ENV = "AXIOM_COMPAT_POSTGRES"
REDIS_ENV = "AXIOM_COMPAT_REDIS"
DISPOSABLE_ENV = "AXIOM_COMPAT_ALLOW_DISPOSABLE"


class NotRunError(Exception):
    """A service probe has not been configured for a disposable environment."""


@dataclass
class ProbeResult:
    name: str
    status: Literal["PASS", "FAIL", "NOT_RUN"]
    detail: str


def database_settings(dsn: str) -> dict[str, object]:
    parsed = urlparse(dsn)
    if parsed.scheme != "postgresql" or parsed.path != "/axiom_compat":
        raise ValueError("Only the disposable axiom_compat PostgreSQL database is supported")
    if not parsed.hostname or not parsed.username:
        raise ValueError("Disposable database connection is incomplete")
    settings: dict[str, object] = {
        "ENGINE": "django.db.backends.postgresql", "NAME": "axiom_compat",
        "USER": unquote(parsed.username), "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname, "PORT": str(parsed.port or 5432),
        "OPTIONS": {"connect_timeout": 5},
    }
    return settings


def require_disposable() -> None:
    if os.environ.get(DISPOSABLE_ENV) != "1":
        raise NotRunError("Disposable service opt-in is required")


def django_probe() -> str:
    dsn = os.environ.get(POSTGRES_ENV)
    database: dict[str, object] = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    if dsn:
        require_disposable()
        configured = database_settings(dsn)
        database.update(configured)
    settings = import_module("django.conf").settings
    settings.configure(
        INSTALLED_APPS=["django.contrib.contenttypes", "rest_framework"],
        DATABASES={"default": database}, SECRET_KEY="disposable-compatibility-only", USE_TZ=True,
    )
    import_module("django").setup()
    import_module("django.core.management").call_command("migrate", verbosity=0, interactive=False)
    content_type = import_module("django.contrib.contenttypes.models").ContentType
    row = content_type.objects.create(app_label="axiom_t02", model="compatibility_probe")
    try:
        if content_type.objects.get(pk=row.pk).model != "compatibility_probe":
            raise ValueError("ORM round-trip failed")
    finally:
        row.delete()
    serializer = import_module("rest_framework.serializers").Serializer(data={"value": 7})
    serializer.fields["value"] = import_module("rest_framework.serializers").IntegerField(min_value=0)
    serializer.is_valid(raise_exception=True)
    rendered = import_module("rest_framework.renderers").JSONRenderer().render(serializer.validated_data)
    if json.loads(rendered) != {"value": 7}:
        raise ValueError("DRF JSON round-trip failed")
    return "Django migration/ORM and DRF JSON passed on " + ("PostgreSQL" if dsn else "SQLite")


def postgres_probe() -> str:
    require_disposable()
    dsn = os.environ.get(POSTGRES_ENV)
    if not dsn:
        raise NotRunError("PostgreSQL not configured")
    database_settings(dsn)
    with import_module("psycopg").connect(dsn, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TEMP TABLE axiom_t02_probe (value integer)")
            cursor.execute("INSERT INTO axiom_t02_probe VALUES (%s)", (7,))
            cursor.execute("SELECT value FROM axiom_t02_probe")
            if cursor.fetchone() != (7,):
                raise ValueError("PostgreSQL transaction failed")
        connection.rollback()
    return "psycopg transaction and rollback passed"


def redis_configuration() -> str:
    require_disposable()
    url = os.environ.get(REDIS_ENV)
    if not url:
        raise NotRunError("Redis not configured")
    parsed = urlparse(url)
    if parsed.scheme != "redis" or not parsed.hostname or parsed.path != "/13":
        raise ValueError("Only disposable Redis database 13 is supported")
    return url


def celery_probe() -> str:
    url = redis_configuration()
    client = import_module("redis").Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)
    try:
        if not client.ping():
            raise ValueError("Redis ping failed")
    finally:
        client.close()
    app = import_module("tools.compatibility.celery_app").app
    command = [
        sys.executable, "-m", "celery", "-A", "tools.compatibility.celery_app:app", "worker",
        "--pool=solo", "--concurrency=1", "--loglevel=ERROR", "--without-gossip",
        "--without-mingle", "--without-heartbeat", "--queues=axiom-t02",
    ]
    worker = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        result = app.send_task("axiom.compat.add", args=[2, 3], queue="axiom-t02")
        try:
            if result.get(timeout=25) != 5:
                raise ValueError("Real Celery task returned an incorrect result")
        finally:
            result.forget()
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)
        app.close()
    return "Redis ping and real Celery worker/task/result passed (not eager)"


def numerical_probe() -> str:
    np = import_module("numpy")
    optimize = import_module("scipy.optimize")
    x = np.arange(8, dtype=float)
    y = 2 * x + 1
    def residual(parameters: Sequence[float]) -> list[float]:
        return [float(parameters[0]) * float(value) + float(parameters[1]) - float(target)
                for value, target in zip(x, y, strict=True)]

    fitted = optimize.least_squares(residual, [0, 0])
    if not fitted.success or not np.allclose(fitted.x, [2, 1], rtol=0, atol=1e-9):
        raise ValueError("Linear least-squares coefficients differ")
    symbolic = import_module("sympy")
    variable = symbolic.Symbol("x")
    expression = 2 * variable + 1
    if symbolic.diff(expression, variable) != 2:
        raise ValueError("Symbolic derivative differs")
    evaluate = symbolic.lambdify(variable, expression, "numpy")
    if not np.array_equal(evaluate(x), y):
        raise ValueError("Symbolic/numerical interoperability failed")
    return "NumPy/SciPy fit and SymPy derivative/lambdify passed"


def precision_table_probe() -> str:
    mp = import_module("mpmath").mp
    with mp.workdps(50):
        if abs(mp.sqrt(2) ** 2 - 2) > mp.mpf("1e-48"):
            raise ValueError("High-precision evaluation failed")
    frame = import_module("polars").DataFrame({"x": [0, 1, 2], "y": [1, 3, 5]})
    if frame.height != 3 or not math.isclose(float(frame["y"].mean()), 3):
        raise ValueError("Polars table values differ")
    return "mpmath 50-digit precision and Polars table passed"


def run_probe(name: str, check: Callable[[], str]) -> ProbeResult:
    try:
        return ProbeResult(name, "PASS", check())
    except NotRunError as error:
        return ProbeResult(name, "NOT_RUN", str(error))
    except Exception as error:
        # Driver exceptions can contain connection credentials; report only their type.
        return ProbeResult(name, "FAIL", type(error).__name__)


def successful(results: list[ProbeResult], require_services: bool) -> bool:
    if not results or any(result.status == "FAIL" for result in results):
        return False
    service_names = {"postgresql", "redis_celery"}
    if any(result.status == "NOT_RUN" and (require_services or result.name not in service_names)
           for result in results):
        return False
    return any(result.status == "PASS" and result.name not in service_names for result in results)


def inventory() -> list[dict[str, str]]:
    packages: list[dict[str, str]] = []
    for distribution in metadata.distributions():
        declared = distribution.metadata.get("License-Expression") or distribution.metadata.get("License")
        packages.append({
            "name": str(distribution.metadata["Name"]), "version": distribution.version,
            "license": (declared or "UNKNOWN").strip()[:160],
            "license_status": "DECLARED_NOT_REVIEWED" if declared else "UNKNOWN",
        })
    return sorted(packages, key=lambda item: item["name"].casefold())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-services", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    probes = [
        ("django_drf", django_probe), ("postgresql", postgres_probe), ("redis_celery", celery_probe),
        ("numerical", numerical_probe), ("precision_table", precision_table_probe),
    ]
    results = [run_probe(name, check) for name, check in probes]
    passed = successful(results, args.require_services)
    report = {
        "scope": "T02_COMPATIBILITY_ONLY", "product_status": "NOT_RUN",
        "status": "PASS" if passed else "FAIL", "require_services": args.require_services,
        "python": platform.python_version(), "platform": platform.system(), "machine": platform.machine(),
        "lock_sha256": hashlib.sha256((ROOT / "tools/compatibility/requirements.lock").read_bytes()).hexdigest(),
        "checks": [asdict(result) for result in results], "packages": inventory(),
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
