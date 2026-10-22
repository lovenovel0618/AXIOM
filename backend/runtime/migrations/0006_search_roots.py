"""在既有 Run 原生 guard 中允許最小權威的 SEARCH／FIT root。

SEARCH／FIT 只承載身分，不派送也不建快照，因此必須是 control_only=False；已有 SEARCH／FIT
資料時不允許切回僅 INGEST／PROFILE 的舊 guard。"""
from importlib import import_module
from django.db import migrations

PREVIOUS = import_module("runtime.migrations.0005_profile_roots")
OLD = "OR NEW.document->>'type' NOT IN ('INGEST','PROFILE') OR (NEW.control_only AND NEW.document->>'type'='PROFILE')"
NEW = "OR NEW.document->>'type' NOT IN ('INGEST','PROFILE','SEARCH','FIT') OR (NEW.control_only AND NEW.document->>'type' IN ('PROFILE','SEARCH','FIT'))"
FORWARD = PREVIOUS.FORWARD.replace(OLD, NEW)
REVERSE = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM runtime_runtimerun WHERE document->>'type' IN ('SEARCH','FIT')) THEN RAISE EXCEPTION 'SEARCH/FIT roots require explicit backup/migration before downgrade'; END IF; END $$;\n" + PREVIOUS.FORWARD


class Migration(migrations.Migration):
    dependencies = [("runtime", "0005_profile_roots")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
