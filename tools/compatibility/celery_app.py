"""Real task registration for the disposable T02 broker only."""
from importlib import import_module
from tools.compatibility.python_probe import redis_configuration


def add(left: int, right: int) -> int:
    return left + right


broker = redis_configuration()
app = import_module("celery").Celery("axiom_t02", broker=broker, backend=broker)
app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], result_expires=60)
app.task(name="axiom.compat.add")(add)
