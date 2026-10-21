"""The fixed task accepts identities only, never code or research data."""
from uuid import UUID
from config.celery import app
from foundation.dispatch import claim, complete


def execute_probe(probe_id: str, generation: int) -> bool:
    """實際 worker 處理世代受控探針，證明 broker 與 handler 確實接通。"""
    identity = UUID(probe_id)
    token = claim(identity, generation)
    return token is not None and complete(identity, generation, token)


app.task(name="foundation.execute_probe", ignore_result=True)(execute_probe)


def publish_probe(probe_id: str, generation: int) -> None:
    """將持久探針送至 foundation queue，不授予原始資料檔存取權。"""
    app.send_task("foundation.execute_probe", args=[probe_id, generation], retry=False)
