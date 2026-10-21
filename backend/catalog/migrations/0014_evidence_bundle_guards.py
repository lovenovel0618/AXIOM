"""證據包的原生防線：同租戶複合 FK、身分不可改、引用必須是真實可用產物。

證據包是 READY 版本的公開引用入口，因此不可刪除；狀態變更（如 REVOKED）
只允許 revision 每次加一，且文件與欄位必須同步，避免出現兩份真相。"""
from django.db import migrations

FORWARD = """
ALTER TABLE catalog_evidencebundle ADD CONSTRAINT evidence_bundle_version_fk FOREIGN KEY(research_version_id,tenant_id) REFERENCES catalog_researchversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_evidencebundle ADD CONSTRAINT evidence_bundle_run_fk FOREIGN KEY(run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION catalog_evidence_bundle_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE artifact uuid;
BEGIN
 IF TG_OP='UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
 OR NEW.research_version_id IS DISTINCT FROM OLD.research_version_id OR NEW.run_id IS DISTINCT FROM OLD.run_id
 OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.revision<>OLD.revision+1)
 THEN RAISE EXCEPTION 'Immutable evidence bundle identity' USING ERRCODE='23514'; END IF;
 IF NEW.document->>'kind' IS DISTINCT FROM 'EvidenceBundle' OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NEW.document->>'status' IS DISTINCT FROM NEW.status OR NEW.document->>'revision' IS DISTINCT FROM NEW.revision::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR jsonb_typeof(NEW.document->'validation_ids') IS DISTINCT FROM 'array' OR jsonb_typeof(NEW.document->'proof_artifact_ids') IS DISTINCT FROM 'array'
 OR (NEW.document->'validation_ids'='[]'::jsonb AND NEW.document->'proof_artifact_ids'='[]'::jsonb)
 THEN RAISE EXCEPTION 'Evidence bundle identity mismatch' USING ERRCODE='23514'; END IF;
 FOR artifact IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.document->'proof_artifact_ids') LOOP
  IF NOT EXISTS(SELECT 1 FROM catalog_artifact WHERE id=artifact AND research_version_id=NEW.research_version_id
   AND tenant_id=NEW.tenant_id AND document->>'status'='AVAILABLE')
  THEN RAISE EXCEPTION 'Evidence bundle artifact mismatch' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER evidence_bundle_guard BEFORE INSERT OR UPDATE ON catalog_evidencebundle FOR EACH ROW EXECUTE FUNCTION catalog_evidence_bundle_guard();
CREATE TRIGGER evidence_bundle_no_delete BEFORE DELETE ON catalog_evidencebundle FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
"""
REVERSE = """
DROP TRIGGER evidence_bundle_no_delete ON catalog_evidencebundle;
DROP TRIGGER evidence_bundle_guard ON catalog_evidencebundle;
DROP FUNCTION catalog_evidence_bundle_guard();
ALTER TABLE catalog_evidencebundle DROP CONSTRAINT evidence_bundle_run_fk, DROP CONSTRAINT evidence_bundle_version_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0013_evidencebundle")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
