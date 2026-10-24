"""Checkpoint 的原生防線：同租戶複合外鍵、attempt 歸屬、身分同步與不可改刪。

checkpoint 只保存受控 JSON 進度，重試時據以恢復；因此它必須與 run／attempt 完全同租戶且身分
逐欄同步，且一經落庫即不可更新或刪除，避免他人改寫歷史進度後被當成已驗證狀態載入。"""
from django.db import migrations

forward_sql = """
ALTER TABLE runtime_runtimecheckpoint ADD CONSTRAINT checkpoint_run_fk FOREIGN KEY(run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION runtime_checkpoint_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'CheckpointRecord'
 OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text
 OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'run_id' IS DISTINCT FROM NEW.run_id::text
 OR NEW.document->>'attempt_id' IS DISTINCT FROM NEW.attempt_id::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NOT EXISTS(SELECT 1 FROM runtime_runtimeattempt a WHERE a.id=NEW.attempt_id AND a.run_id=NEW.run_id)
 THEN RAISE EXCEPTION 'Checkpoint identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER runtime_checkpoint_guard BEFORE INSERT ON runtime_runtimecheckpoint FOR EACH ROW EXECUTE FUNCTION runtime_checkpoint_guard();
CREATE FUNCTION runtime_checkpoint_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Immutable checkpoint' USING ERRCODE = '23514'; END $$;
CREATE TRIGGER runtime_checkpoint_no_update BEFORE UPDATE ON runtime_runtimecheckpoint FOR EACH ROW EXECUTE FUNCTION runtime_checkpoint_immutable();
CREATE TRIGGER runtime_checkpoint_no_delete BEFORE DELETE ON runtime_runtimecheckpoint FOR EACH ROW EXECUTE FUNCTION runtime_checkpoint_immutable();
"""

reverse_sql = """
DROP TRIGGER runtime_checkpoint_no_delete ON runtime_runtimecheckpoint;
DROP TRIGGER runtime_checkpoint_no_update ON runtime_runtimecheckpoint;
DROP FUNCTION runtime_checkpoint_immutable();
DROP TRIGGER runtime_checkpoint_guard ON runtime_runtimecheckpoint;
DROP FUNCTION runtime_checkpoint_guard();
ALTER TABLE runtime_runtimecheckpoint DROP CONSTRAINT checkpoint_run_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("runtime", "0012_checkpoint_table")]
    operations = [migrations.RunSQL(forward_sql, reverse_sql)]
