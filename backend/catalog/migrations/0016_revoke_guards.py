"""撤銷的原生授權：REVOKE root 的原子權威、以及非狀態變更的研究事件。

撤銷在同交易先寫權威紀錄再異步清理，因此 native 防線要求在交易末同時看到
REVOKE run、撤銷登記與已排除的證據包；研究串流則放行 payload 不含 status 的
事件（如 EvidenceRevoked），但仍要求序號與狀態 revision 一致以維持 cursor 語意。"""
from importlib import import_module
from django.db import migrations

PREVIOUS = import_module("catalog.migrations.0010_profile_guards")
BUSINESS_PROFILE = PREVIOUS.forward_sql.split("CREATE OR REPLACE FUNCTION catalog_business_guard()",1)[1].split("CREATE CONSTRAINT TRIGGER business_profile_guard",1)[0]
RESEARCH_EVENT_BASE = PREVIOUS.forward_sql.split("CREATE FUNCTION catalog_research_event_guard()",1)[1].split("CREATE TRIGGER research_event_guard",1)[0]

REVOKE_CHECK = """
 IF r.document->>'type'='REVOKE' THEN
  IF NOT EXISTS(SELECT 1 FROM catalog_evidencerevocation v
    JOIN catalog_evidencebundle e ON e.id=v.evidence_bundle_id AND e.tenant_id=v.tenant_id
    WHERE v.run_id=r.id AND v.tenant_id=r.tenant_id
    AND e.research_version_id::text=r.document->>'research_version_id'
    AND e.status='REVOKED' AND e.document->>'status'='REVOKED')
  THEN RAISE EXCEPTION 'Atomic evidence revocation authority required' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
"""
STATE_MATCH = " AND s.revision=NEW.sequence AND s.status=NEW.document->'payload'->>'status')"
EVENT_MATCH = " AND s.revision=NEW.sequence AND (NEW.document->>'event_type'<>'ResearchVersionStateChanged' OR s.status=NEW.document->'payload'->>'status'))"

forward_sql = "CREATE OR REPLACE FUNCTION catalog_business_guard()" + BUSINESS_PROFILE.replace(" SELECT * INTO b FROM catalog_ingestbinding",REVOKE_CHECK+" SELECT * INTO b FROM catalog_ingestbinding")
forward_sql += "CREATE CONSTRAINT TRIGGER business_revocation_guard AFTER INSERT OR UPDATE ON catalog_evidencerevocation DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_business_guard();\n"
forward_sql += "CREATE OR REPLACE FUNCTION catalog_research_event_guard()" + RESEARCH_EVENT_BASE.replace(STATE_MATCH,EVENT_MATCH)

reverse_sql = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM catalog_evidencerevocation) THEN RAISE EXCEPTION 'REVOKE data requires explicit backup/migration before downgrade'; END IF; END $$;\n"
reverse_sql += "DROP TRIGGER business_revocation_guard ON catalog_evidencerevocation;\n"
reverse_sql += "CREATE OR REPLACE FUNCTION catalog_business_guard()" + BUSINESS_PROFILE
reverse_sql += "CREATE OR REPLACE FUNCTION catalog_research_event_guard()" + RESEARCH_EVENT_BASE


class Migration(migrations.Migration):
    dependencies = [("catalog","0015_evidence_revocation")]
    operations = [migrations.RunSQL(forward_sql,reverse_sql)]
