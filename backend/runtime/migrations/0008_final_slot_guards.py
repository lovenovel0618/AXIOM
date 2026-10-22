"""FinalEvaluationSlot 的身分同步、單向狀態與不可改刪。

槽位只在派送時以 PENDING 建立並固定 run_id；只有結果引用（status／validation_run_id）
可前進一次，其餘欄位與 DELETE 一律拒絕。"""
from django.db import migrations

forward_sql = """
CREATE FUNCTION runtime_final_slot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'FinalEvaluationSlot'
 OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text
 OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'submission_id' IS DISTINCT FROM NEW.submission_id::text
 OR NEW.document->>'frozen_candidate_id' IS DISTINCT FROM NEW.frozen_candidate_id::text
 OR NEW.document->>'metric_version' IS DISTINCT FROM NEW.metric_version
 OR NEW.document->>'run_id' IS DISTINCT FROM NEW.run_id::text
 OR NOT NEW.document ? 'validation_run_id'
 OR NEW.document->>'validation_run_id' IS DISTINCT FROM NEW.validation_run_id::text
 OR NEW.document->>'status' IS DISTINCT FROM NEW.status
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 THEN RAISE EXCEPTION 'Final evaluation slot identity mismatch' USING ERRCODE='23514'; END IF;
 IF TG_OP = 'INSERT' AND (NEW.status IS DISTINCT FROM 'PENDING' OR NEW.validation_run_id IS NOT NULL)
 THEN RAISE EXCEPTION 'Final evaluation slot must start pending' USING ERRCODE='23514'; END IF;
 IF TG_OP = 'UPDATE' THEN
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
  OR NEW.submission_id IS DISTINCT FROM OLD.submission_id OR NEW.frozen_candidate_id IS DISTINCT FROM OLD.frozen_candidate_id
  OR NEW.metric_version IS DISTINCT FROM OLD.metric_version OR NEW.run_id IS DISTINCT FROM OLD.run_id
  OR NEW.created_at IS DISTINCT FROM OLD.created_at
  THEN RAISE EXCEPTION 'Immutable final evaluation slot identity' USING ERRCODE='23514'; END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND OLD.status IS DISTINCT FROM 'PENDING'
  THEN RAISE EXCEPTION 'Final evaluation slot already settled' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER runtime_final_slot_guard BEFORE INSERT OR UPDATE ON runtime_finalevaluationslot FOR EACH ROW EXECUTE FUNCTION runtime_final_slot_guard();
CREATE FUNCTION runtime_final_slot_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Immutable final evaluation slot' USING ERRCODE = '23514'; END $$;
CREATE TRIGGER runtime_final_slot_no_delete BEFORE DELETE ON runtime_finalevaluationslot FOR EACH ROW EXECUTE FUNCTION runtime_final_slot_immutable();
"""

reverse_sql = """
DROP TRIGGER runtime_final_slot_no_delete ON runtime_finalevaluationslot;
DROP FUNCTION runtime_final_slot_immutable();
DROP TRIGGER runtime_final_slot_guard ON runtime_finalevaluationslot;
DROP FUNCTION runtime_final_slot_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("runtime", "0007_final_evaluation_slot")]
    operations = [migrations.RunSQL(forward_sql, reverse_sql)]
