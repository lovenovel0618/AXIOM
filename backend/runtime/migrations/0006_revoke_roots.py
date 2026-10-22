"""在既有 Run 原生 guard 中允許具有業務綁定的 REVOKE root。

沿用原不可變身分及合法狀態防線；已有 REVOKE 資料時不允許切回僅 INGEST／PROFILE 的舊 guard。"""
from importlib import import_module
from django.db import migrations

BASE = import_module("runtime.migrations.0005_profile_roots").FORWARD
FORWARD = BASE.replace("OR NEW.document->>'type' NOT IN ('INGEST','PROFILE') OR (NEW.control_only AND NEW.document->>'type'='PROFILE')",
    "OR NEW.document->>'type' NOT IN ('INGEST','PROFILE','REVOKE') OR (NEW.control_only AND NEW.document->>'type' IN ('PROFILE','REVOKE'))")
REVERSE = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM runtime_runtimerun WHERE document->>'type'='REVOKE') THEN RAISE EXCEPTION 'REVOKE roots require explicit backup/migration before downgrade'; END IF; END $$;\n" + BASE


class Migration(migrations.Migration):
    dependencies = [("runtime","0005_profile_roots")]
    operations = [migrations.RunSQL(FORWARD,REVERSE)]
