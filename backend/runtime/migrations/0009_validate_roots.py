"""在既有 Run 原生 guard 中允許最小權威的 VALIDATE root。

VALIDATE 只承載身分，不派送也不建快照，因此必須是 control_only=False；已有 VALIDATE 資料時
不允許切回未含 VALIDATE 的舊 guard。"""
from importlib import import_module
from django.db import migrations

PREVIOUS = import_module("runtime.migrations.0006_search_roots")
OLD = "NOT IN ('INGEST','PROFILE','SEARCH','FIT') OR (NEW.control_only AND NEW.document->>'type' IN ('PROFILE','SEARCH','FIT'))"
NEW = "NOT IN ('INGEST','PROFILE','SEARCH','FIT','VALIDATE') OR (NEW.control_only AND NEW.document->>'type' IN ('PROFILE','SEARCH','FIT','VALIDATE'))"
if OLD not in PREVIOUS.FORWARD:
    raise RuntimeError("Runtime root guard text changed; update the VALIDATE extension")
FORWARD = PREVIOUS.FORWARD.replace(OLD, NEW)
REVERSE = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM runtime_runtimerun WHERE document->>'type'='VALIDATE') THEN RAISE EXCEPTION 'VALIDATE roots require explicit backup/migration before downgrade'; END IF; END $$;\n" + PREVIOUS.FORWARD


class Migration(migrations.Migration):
    dependencies = [("runtime", "0008_final_slot_guards")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
