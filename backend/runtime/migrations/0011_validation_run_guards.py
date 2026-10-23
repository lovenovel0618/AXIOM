"""評估結果的原生防線：同租戶複合外鍵、身分同步、分母一致與不可改刪。

結果列只承載唯一鍵與固定身分，因此文件與欄位必須完全同步；`valid_count + failed_count` 必須等於
`selected_count`，讓「分母」不會被單獨改寫；結果一經落庫即不可更新或刪除，重算必須是新 run。"""
from django.db import migrations

forward_sql = """
ALTER TABLE runtime_validationrun ADD CONSTRAINT validation_run_run_fk FOREIGN KEY(run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION runtime_validation_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'ValidationRun'
 OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text
 OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'run_id' IS DISTINCT FROM NEW.run_id::text
 OR NEW.document->>'observation_split_id' IS DISTINCT FROM NEW.observation_split_id::text
 OR NEW.document->>'split_role' IS DISTINCT FROM NEW.split_role
 OR NEW.document->>'metric_version' IS DISTINCT FROM NEW.metric_version
 OR NOT NEW.document ? 'submission_id'
 OR NEW.document->>'submission_id' IS DISTINCT FROM NEW.submission_id::text
 OR NOT NEW.document ? 'frozen_candidate_id'
 OR NEW.document->>'frozen_candidate_id' IS DISTINCT FROM NEW.frozen_candidate_id::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 THEN RAISE EXCEPTION 'Validation run identity mismatch' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(NEW.document->'selected_count') IS DISTINCT FROM 'number'
 OR jsonb_typeof(NEW.document->'valid_count') IS DISTINCT FROM 'number'
 OR jsonb_typeof(NEW.document->'failed_count') IS DISTINCT FROM 'number'
 OR ((NEW.document->>'valid_count')::numeric + (NEW.document->>'failed_count')::numeric)
    IS DISTINCT FROM (NEW.document->>'selected_count')::numeric
 THEN RAISE EXCEPTION 'Validation run denominator mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER runtime_validation_run_guard BEFORE INSERT ON runtime_validationrun FOR EACH ROW EXECUTE FUNCTION runtime_validation_run_guard();
CREATE FUNCTION runtime_validation_run_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Immutable validation run' USING ERRCODE = '23514'; END $$;
CREATE TRIGGER runtime_validation_run_no_update BEFORE UPDATE ON runtime_validationrun FOR EACH ROW EXECUTE FUNCTION runtime_validation_run_immutable();
CREATE TRIGGER runtime_validation_run_no_delete BEFORE DELETE ON runtime_validationrun FOR EACH ROW EXECUTE FUNCTION runtime_validation_run_immutable();
"""

reverse_sql = """
DROP TRIGGER runtime_validation_run_no_delete ON runtime_validationrun;
DROP TRIGGER runtime_validation_run_no_update ON runtime_validationrun;
DROP FUNCTION runtime_validation_run_immutable();
DROP TRIGGER runtime_validation_run_guard ON runtime_validationrun;
DROP FUNCTION runtime_validation_run_guard();
ALTER TABLE runtime_validationrun DROP CONSTRAINT validation_run_run_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("runtime", "0010_validation_run")]
    operations = [migrations.RunSQL(forward_sql, reverse_sql)]
