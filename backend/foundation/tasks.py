"""The fixed task accepts identities only, never code or research data."""
from uuid import UUID
from config.celery import app
from foundation.dispatch import claim, complete


def execute_probe(probe_id: str, generation: int) -> bool:
    identity = UUID(probe_id)
    token = claim(identity, generation)
    return token is not None and complete(identity, generation, token)


app.task(name="foundation.execute_probe", ignore_result=True)(execute_probe)


def publish_probe(probe_id: str, generation: int) -> None:
    app.send_task("foundation.execute_probe", args=[probe_id, generation], retry=False)
