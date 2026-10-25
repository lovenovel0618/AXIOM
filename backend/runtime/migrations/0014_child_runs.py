"""在既有 Run 原生 guard 中允許研究子任務（SEARCH／FIT child）。

根仍自我引用且無親代；子列必須 is_root=false、parent_run_id 非空、root_run_id 指向他列且非自身，
且只能是研究型別。已有子列時不允許切回未含 child 的舊 guard。"""
from importlib import import_module
from django.db import migrations

PREVIOUS = import_module("runtime.migrations.0009_validate_roots")
OLD = "  IF NEW.document->>'id' IS DISTINCT FROM NEW.id::text\n    OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text\n    OR NEW.document->>'root_run_id' IS DISTINCT FROM NEW.id::text\n    OR NEW.document->>'type' IS NULL OR NEW.document->>'type' NOT IN ('INGEST','PROFILE','SEARCH','FIT','VALIDATE') OR (NEW.control_only AND NEW.document->>'type' IN ('PROFILE','SEARCH','FIT','VALIDATE'))\n    OR NEW.document->'is_root' IS DISTINCT FROM 'true'::jsonb\n    OR NEW.document->'parent_run_id' IS DISTINCT FROM 'null'::jsonb\n    OR NEW.document->>'status' IS NULL\n    OR NEW.document->>'status' NOT IN ('QUEUED','RUNNING','CANCEL_REQUESTED','SUCCEEDED','FAILED','CANCELLED')\n  THEN RAISE EXCEPTION 'Invalid runtime root identity' USING ERRCODE = '23514'; END IF;"
NEW = "  IF NEW.document->>'id' IS DISTINCT FROM NEW.id::text\n    OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text\n    OR NEW.document->>'status' IS NULL\n    OR NEW.document->>'status' NOT IN ('QUEUED','RUNNING','CANCEL_REQUESTED','SUCCEEDED','FAILED','CANCELLED')\n  THEN RAISE EXCEPTION 'Invalid runtime run identity' USING ERRCODE = '23514'; END IF;\n  IF NEW.document->>'is_root' = 'true' THEN\n    IF NEW.document->>'type' IS NULL OR NEW.document->>'type' NOT IN ('INGEST','PROFILE','SEARCH','FIT','VALIDATE')\n      OR (NEW.control_only AND NEW.document->>'type' IN ('PROFILE','SEARCH','FIT','VALIDATE'))\n      OR NEW.document->>'root_run_id' IS DISTINCT FROM NEW.id::text\n      OR NEW.document->'parent_run_id' IS DISTINCT FROM 'null'::jsonb\n    THEN RAISE EXCEPTION 'Invalid runtime root identity' USING ERRCODE = '23514'; END IF;\n  ELSIF NEW.document->>'is_root' = 'false' THEN\n    IF NEW.document->>'type' IS NULL OR NEW.document->>'type' NOT IN ('SEARCH','FIT')\n      OR NEW.control_only\n      OR NEW.document->>'parent_run_id' IS NULL\n      OR NEW.document->>'root_run_id' IS NULL\n      OR NEW.document->>'root_run_id' = NEW.id::text\n    THEN RAISE EXCEPTION 'Invalid runtime child identity' USING ERRCODE = '23514'; END IF;\n  ELSE\n    RAISE EXCEPTION 'Invalid runtime is_root value' USING ERRCODE = '23514';\n  END IF;"
if OLD not in PREVIOUS.FORWARD:
    raise RuntimeError("Runtime root guard text changed; update the child extension")
FORWARD = PREVIOUS.FORWARD.replace(OLD, NEW)
REVERSE = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM runtime_runtimerun WHERE document->>'is_root'='false') THEN RAISE EXCEPTION 'Child runs require explicit backup/migration before downgrade'; END IF; END $$;\n" + PREVIOUS.FORWARD


class Migration(migrations.Migration):
    dependencies = [("runtime", "0013_checkpoint_guards")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
