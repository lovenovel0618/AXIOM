"""只對真實 catalog 版本施加 SEARCH 業務防線；runtime 的獨立合成研究探針不假裝業務輸入。"""
from importlib import import_module
from django.db import migrations

PREVIOUS = import_module("catalog.migrations.0027_search_queued_state")
OLD = "AND EXISTS(SELECT 1 FROM runtime_inputsnapshot WHERE run_id=r.id) THEN"
NEW = """AND EXISTS(SELECT 1 FROM runtime_inputsnapshot WHERE run_id=r.id)
 AND EXISTS(SELECT 1 FROM catalog_researchversion search_version
  WHERE search_version.id::text=r.document->>'research_version_id' AND search_version.tenant_id=r.tenant_id) THEN"""
if OLD not in PREVIOUS.BUSINESS_NEW:
    raise RuntimeError("SEARCH business scope changed")
FORWARD = PREVIOUS.BUSINESS_NEW.replace(OLD, NEW)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0027_search_queued_state")]
    operations = [migrations.RunSQL(FORWARD, PREVIOUS.BUSINESS_NEW)]
