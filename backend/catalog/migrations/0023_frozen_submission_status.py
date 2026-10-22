"""FrozenSubmission 狀態流：僅允許單向 FROZEN→EVALUATING→EVALUATED／FAILED，其身分、快照與刪除仍不可改。"""
from django.db import migrations

forward_sql = """
DROP TRIGGER frozen_submission_immutable ON catalog_frozensubmission;
CREATE FUNCTION catalog_frozen_submission_status_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
 OR NEW.research_version_id IS DISTINCT FROM OLD.research_version_id
 OR NEW.verification_plan_artifact_id IS DISTINCT FROM OLD.verification_plan_artifact_id
 OR NEW.sealed_test_id IS DISTINCT FROM OLD.sealed_test_id
 OR NEW.metric_version IS DISTINCT FROM OLD.metric_version
 OR NEW.snapshot_hash IS DISTINCT FROM OLD.snapshot_hash
 OR NEW.created_at IS DISTINCT FROM OLD.created_at
 OR OLD.document - 'status' IS DISTINCT FROM NEW.document - 'status'
 OR NEW.document->>'status' IS DISTINCT FROM NEW.status
 THEN RAISE EXCEPTION 'Immutable frozen submission' USING ERRCODE='23514'; END IF;
 IF NEW.status IS DISTINCT FROM OLD.status
 AND NOT ((OLD.status='FROZEN' AND NEW.status='EVALUATING')
       OR (OLD.status='EVALUATING' AND NEW.status IN ('EVALUATED','FAILED')))
 THEN RAISE EXCEPTION 'Invalid frozen submission transition' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER frozen_submission_status_guard BEFORE UPDATE ON catalog_frozensubmission FOR EACH ROW EXECUTE FUNCTION catalog_frozen_submission_status_guard();
CREATE TRIGGER frozen_submission_no_delete BEFORE DELETE ON catalog_frozensubmission FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
"""

reverse_sql = """
DROP TRIGGER frozen_submission_no_delete ON catalog_frozensubmission;
DROP TRIGGER frozen_submission_status_guard ON catalog_frozensubmission;
DROP FUNCTION catalog_frozen_submission_status_guard();
CREATE TRIGGER frozen_submission_immutable BEFORE UPDATE OR DELETE ON catalog_frozensubmission FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0022_frozen_submission_guards")]
    operations = [migrations.RunSQL(forward_sql, reverse_sql)]
