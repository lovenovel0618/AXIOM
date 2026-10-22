"""刪除傳播的原生防線：同租戶複合 FK、身分不可改、狀態白名單與政策 Fail-Closed。

政策未放行（policy_status 非 ACTIVE）時，任何轉入 PROPAGATING 或 COMPLETED 的寫入
一律拒絕，因此 D-05 未決前刪除工作只能停在 BLOCKED，不會悄悄選擇永久保留或全部刪光。
tombstone 寫入即生效，不可改也不可刪。"""
from django.db import migrations

FORWARD = """
ALTER TABLE catalog_deletionrequest ADD CONSTRAINT deletion_request_version_fk FOREIGN KEY(dataset_version_id,tenant_id) REFERENCES catalog_datasetversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_deletiontarget ADD CONSTRAINT deletion_target_request_fk FOREIGN KEY(deletion_request_id,tenant_id) REFERENCES catalog_deletionrequest(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_tombstone ADD CONSTRAINT tombstone_request_fk FOREIGN KEY(deletion_request_id,tenant_id) REFERENCES catalog_deletionrequest(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION catalog_deletion_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
 OR NEW.dataset_version_id IS DISTINCT FROM OLD.dataset_version_id OR NEW.requested_by_id IS DISTINCT FROM OLD.requested_by_id
 OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.revision<>OLD.revision+1)
 THEN RAISE EXCEPTION 'Immutable deletion request identity' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND NEW.status IS DISTINCT FROM OLD.status AND NOT (
  (OLD.status='REQUESTED' AND NEW.status IN ('BLOCKED','PROPAGATING','FAILED'))
  OR (OLD.status='BLOCKED' AND NEW.status IN ('REQUESTED','PROPAGATING','FAILED'))
  OR (OLD.status='PROPAGATING' AND NEW.status IN ('COMPLETED','FAILED'))
  OR (OLD.status='FAILED' AND NEW.status IN ('REQUESTED','PROPAGATING')))
 THEN RAISE EXCEPTION 'Invalid deletion status transition' USING ERRCODE='23514'; END IF;
 IF NEW.status IN ('PROPAGATING','COMPLETED') AND NEW.policy_status<>'ACTIVE'
 THEN RAISE EXCEPTION 'Deletion policy is not active' USING ERRCODE='23514'; END IF;
 IF NEW.status='COMPLETED' AND EXISTS(SELECT 1 FROM catalog_deletiontarget WHERE deletion_request_id=NEW.id AND outcome<>'DONE')
 THEN RAISE EXCEPTION 'Deletion completed with unfinished targets' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER deletion_request_guard BEFORE INSERT OR UPDATE ON catalog_deletionrequest FOR EACH ROW EXECUTE FUNCTION catalog_deletion_request_guard();
CREATE TRIGGER deletion_request_no_delete BEFORE DELETE ON catalog_deletionrequest FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE TRIGGER deletion_target_no_delete BEFORE DELETE ON catalog_deletiontarget FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE TRIGGER tombstone_immutable BEFORE UPDATE OR DELETE ON catalog_tombstone FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
"""
REVERSE = """
DROP TRIGGER tombstone_immutable ON catalog_tombstone;
DROP TRIGGER deletion_target_no_delete ON catalog_deletiontarget;
DROP TRIGGER deletion_request_no_delete ON catalog_deletionrequest;
DROP TRIGGER deletion_request_guard ON catalog_deletionrequest;
DROP FUNCTION catalog_deletion_request_guard();
ALTER TABLE catalog_tombstone DROP CONSTRAINT tombstone_request_fk;
ALTER TABLE catalog_deletiontarget DROP CONSTRAINT deletion_target_request_fk;
ALTER TABLE catalog_deletionrequest DROP CONSTRAINT deletion_request_version_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0015_deletion_and_tombstone")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
