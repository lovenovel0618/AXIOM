"""在既有 Run 原生 guard 中允許有完整業務綁定的 PROFILE root。

沿用原不可變身分及合法狀態防線；已有 PROFILE 資料時不允許切回僅 INGEST 的舊 guard。"""
from importlib import import_module
from django.db import migrations

BASE = import_module("runtime.migrations.0002_document_guards").FORWARD.split("CREATE TRIGGER runtime_run_guard",1)[0]
FORWARD = BASE.replace("CREATE FUNCTION runtime_run_guard", "CREATE OR REPLACE FUNCTION runtime_run_guard").replace("OR NEW.document->>'type' IS DISTINCT FROM 'INGEST'", "OR NEW.document->>'type' IS NULL OR NEW.document->>'type' NOT IN ('INGEST','PROFILE') OR (NEW.control_only AND NEW.document->>'type'='PROFILE')")
REVERSE = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM runtime_runtimerun WHERE document->>'type'='PROFILE') THEN RAISE EXCEPTION 'PROFILE roots require explicit backup/migration before downgrade'; END IF; END $$;\n" + BASE.replace("CREATE FUNCTION runtime_run_guard", "CREATE OR REPLACE FUNCTION runtime_run_guard")


class Migration(migrations.Migration):
    dependencies = [("runtime","0004_remove_runtimerun_runtime_control_only")]
    operations = [migrations.RunSQL(FORWARD,REVERSE)]
