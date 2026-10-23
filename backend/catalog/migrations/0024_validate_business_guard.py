"""讓 business guard 對最小權威 VALIDATE root 早退。

`VALIDATE` 由 `catalog.final_evaluation` 在派送最終評估時建立，與 SEARCH／FIT 一樣只承載身分，
沒有 ingest 綁定、快照或帳本列；它仍受 runtime run guard 與複合外鍵保護，因此 business guard
必須比照 SEARCH／FIT 早退，否則合法的最終評估 root 會在提交時被誤判為缺少 ingest 綁定。"""
from importlib import import_module
from django.db import migrations

CANDIDATE = import_module("catalog.migrations.0020_candidate_guards")
BUSINESS = CANDIDATE.forward_sql.split("CREATE OR REPLACE FUNCTION catalog_business_guard()", 1)[1]
OLD = " IF TG_TABLE_NAME='runtime_runtimerun' AND r.document->>'type' IN ('SEARCH','FIT') THEN RETURN NULL; END IF;"
NEW = " IF TG_TABLE_NAME='runtime_runtimerun' AND r.document->>'type' IN ('SEARCH','FIT','VALIDATE') THEN RETURN NULL; END IF;"
if OLD not in BUSINESS:
    raise RuntimeError("Business guard text changed; update the VALIDATE early return")
forward_sql = "CREATE OR REPLACE FUNCTION catalog_business_guard()" + BUSINESS.replace(OLD, NEW)
reverse_sql = "CREATE OR REPLACE FUNCTION catalog_business_guard()" + BUSINESS


class Migration(migrations.Migration):
    dependencies = [("catalog", "0023_frozen_submission_status")]
    operations = [migrations.RunSQL(forward_sql, reverse_sql)]
