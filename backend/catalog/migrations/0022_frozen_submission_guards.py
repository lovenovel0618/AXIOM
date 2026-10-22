"""FrozenSubmission 的同租戶複合外鍵、身分同步與不可改刪。"""
from django.db import migrations

forward_sql = """
ALTER TABLE catalog_frozensubmission ADD CONSTRAINT frozen_submission_version_fk FOREIGN KEY(research_version_id,tenant_id) REFERENCES catalog_researchversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION catalog_frozen_submission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'FrozenSubmission' OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NEW.document->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NEW.document->>'verification_plan_artifact_id' IS DISTINCT FROM NEW.verification_plan_artifact_id::text
 OR NEW.document->>'sealed_test_id' IS DISTINCT FROM NEW.sealed_test_id::text
 OR NEW.document->>'metric_version' IS DISTINCT FROM NEW.metric_version
 OR NEW.document->>'snapshot_hash' IS DISTINCT FROM NEW.snapshot_hash
 OR NEW.document->>'status' IS DISTINCT FROM NEW.status
 OR NOT EXISTS(SELECT 1 FROM catalog_artifact WHERE id=NEW.verification_plan_artifact_id AND tenant_id=NEW.tenant_id)
 THEN RAISE EXCEPTION 'Frozen submission identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER frozen_submission_guard BEFORE INSERT ON catalog_frozensubmission FOR EACH ROW EXECUTE FUNCTION catalog_frozen_submission_guard();
CREATE TRIGGER frozen_submission_immutable BEFORE UPDATE OR DELETE ON catalog_frozensubmission FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
"""

reverse_sql = """
DROP TRIGGER frozen_submission_immutable ON catalog_frozensubmission;
DROP TRIGGER frozen_submission_guard ON catalog_frozensubmission;
DROP FUNCTION catalog_frozen_submission_guard();
ALTER TABLE catalog_frozensubmission DROP CONSTRAINT frozen_submission_version_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0021_frozen_submission")]
    operations = [migrations.RunSQL(forward_sql, reverse_sql)]
