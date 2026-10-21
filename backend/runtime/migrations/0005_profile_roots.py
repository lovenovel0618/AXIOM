"""Permit only the next fixed business root; preserve immutable run bindings."""
from importlib import import_module
from django.db import migrations

BASE = import_module("runtime.migrations.0002_document_guards").FORWARD.split("CREATE TRIGGER runtime_run_guard",1)[0]
FORWARD = BASE.replace("CREATE FUNCTION runtime_run_guard", "CREATE OR REPLACE FUNCTION runtime_run_guard").replace("OR NEW.document->>'type' IS DISTINCT FROM 'INGEST'", "OR NEW.document->>'type' IS NULL OR NEW.document->>'type' NOT IN ('INGEST','PROFILE') OR (NEW.control_only AND NEW.document->>'type'='PROFILE')")
REVERSE = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM runtime_runtimerun WHERE document->>'type'='PROFILE') THEN RAISE EXCEPTION 'PROFILE roots require explicit backup/migration before downgrade'; END IF; END $$;\n" + BASE.replace("CREATE FUNCTION runtime_run_guard", "CREATE OR REPLACE FUNCTION runtime_run_guard")


class Migration(migrations.Migration):
    dependencies = [("runtime","0004_remove_runtimerun_runtime_control_only")]
    operations = [migrations.RunSQL(FORWARD,REVERSE)]
