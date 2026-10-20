"""Composite foreign keys and immutable source records, enforced by PostgreSQL."""
from django.db import migrations

FORWARD = """
ALTER TABLE catalog_upload ADD CONSTRAINT upload_ingest_tenant_fk FOREIGN KEY(ingest_run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_dataset ADD CONSTRAINT dataset_owner_tenant_fk FOREIGN KEY(owner_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_dataset ADD CONSTRAINT dataset_provenance_tenant_fk FOREIGN KEY(provenance_id,tenant_id) REFERENCES catalog_provenance(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_grant ADD CONSTRAINT grant_actor_tenant_fk FOREIGN KEY(actor_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_grant ADD CONSTRAINT grant_dataset_tenant_fk FOREIGN KEY(dataset_id,tenant_id) REFERENCES catalog_dataset(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_upload ADD CONSTRAINT upload_actor_tenant_fk FOREIGN KEY(actor_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_upload ADD CONSTRAINT upload_dataset_tenant_fk FOREIGN KEY(dataset_id,tenant_id) REFERENCES catalog_dataset(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_storedobject ADD CONSTRAINT object_upload_tenant_fk FOREIGN KEY(upload_id,dataset_id,tenant_id) REFERENCES catalog_upload(id,dataset_id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_storedobject ADD CONSTRAINT object_provenance_tenant_fk FOREIGN KEY(provenance_id,tenant_id) REFERENCES catalog_provenance(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_upload ADD CONSTRAINT upload_object_version_fk FOREIGN KEY(object_version,id,tenant_id) REFERENCES catalog_storedobject(id,upload_id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION catalog_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Immutable catalog source' USING ERRCODE='23514'; END $$;
CREATE TRIGGER catalog_dataset_immutable BEFORE UPDATE OR DELETE ON catalog_dataset FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE TRIGGER catalog_object_immutable BEFORE UPDATE OR DELETE ON catalog_storedobject FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE TRIGGER catalog_provenance_immutable BEFORE UPDATE OR DELETE ON catalog_provenance FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE TRIGGER catalog_audit_immutable BEFORE UPDATE OR DELETE ON catalog_audit FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_account_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.user_id IS DISTINCT FROM OLD.user_id
 THEN RAISE EXCEPTION 'Immutable actor identity' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER catalog_account_guard BEFORE UPDATE ON catalog_account FOR EACH ROW EXECUTE FUNCTION catalog_account_guard();
CREATE TRIGGER catalog_actor_no_delete BEFORE DELETE ON catalog_account FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_upload_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.dataset_id IS DISTINCT FROM OLD.dataset_id
 OR NEW.actor_id IS DISTINCT FROM OLD.actor_id OR NEW.sha256 IS DISTINCT FROM OLD.sha256 OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
 OR NEW.format IS DISTINCT FROM OLD.format OR NEW.filename IS DISTINCT FROM OLD.filename OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
 OR (OLD.object_version IS NOT NULL AND NEW.object_version IS DISTINCT FROM OLD.object_version)
 OR (OLD.ingest_run_id IS NOT NULL AND NEW.ingest_run_id IS DISTINCT FROM OLD.ingest_run_id))
 THEN RAISE EXCEPTION 'Immutable upload binding' USING ERRCODE='23514'; END IF;
 IF NEW.status='COMPLETED' AND NOT EXISTS(SELECT 1 FROM runtime_runtimerun WHERE id=NEW.ingest_run_id AND tenant_id=NEW.tenant_id AND NOT control_only AND document->>'type'='INGEST' AND document->>'dataset_id'=NEW.dataset_id::text)
 THEN RAISE EXCEPTION 'A business INGEST run is required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER catalog_upload_guard BEFORE INSERT OR UPDATE ON catalog_upload FOR EACH ROW EXECUTE FUNCTION catalog_upload_guard();
CREATE FUNCTION catalog_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid; source uuid;
BEGIN
 IF NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'resource_id' IS DISTINCT FROM NEW.resource_id::text OR NEW.document->>'resource_type' IS DISTINCT FROM NEW.resource_type
 THEN RAISE EXCEPTION 'Provenance identity mismatch' USING ERRCODE='23514'; END IF;
 actor := (NEW.document->>'creator_actor_id')::uuid;
 IF NOT EXISTS(SELECT 1 FROM catalog_account WHERE id=actor AND tenant_id=NEW.tenant_id)
 THEN RAISE EXCEPTION 'Provenance actor tenant mismatch' USING ERRCODE='23514'; END IF;
 FOR actor IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.document->'responsible_human_ids') LOOP
  IF NOT EXISTS(SELECT 1 FROM catalog_account WHERE id=actor AND tenant_id=NEW.tenant_id)
  THEN RAISE EXCEPTION 'Provenance human tenant mismatch' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NEW.document->>'root_provenance_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM catalog_provenance WHERE id=(NEW.document->>'root_provenance_id')::uuid AND tenant_id=NEW.tenant_id)
 THEN RAISE EXCEPTION 'Provenance root tenant mismatch' USING ERRCODE='23514'; END IF;
 FOR source IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.document->'source_provenance_ids') LOOP
  IF NOT EXISTS(SELECT 1 FROM catalog_provenance WHERE id=source AND tenant_id=NEW.tenant_id)
  THEN RAISE EXCEPTION 'Provenance source tenant mismatch' USING ERRCODE='23514'; END IF;
  IF NOT (NEW.document->'responsible_human_ids' @> (SELECT document->'responsible_human_ids' FROM catalog_provenance WHERE id=source))
  THEN RAISE EXCEPTION 'Missing inherited responsibility' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER catalog_provenance_guard BEFORE INSERT ON catalog_provenance FOR EACH ROW EXECUTE FUNCTION catalog_provenance_guard();
"""
REVERSE = """
ALTER TABLE catalog_upload DROP CONSTRAINT upload_ingest_tenant_fk;
DROP TRIGGER catalog_provenance_guard ON catalog_provenance;
DROP FUNCTION catalog_provenance_guard();
DROP TRIGGER catalog_upload_guard ON catalog_upload;
DROP FUNCTION catalog_upload_guard();
DROP TRIGGER catalog_account_guard ON catalog_account;
DROP FUNCTION catalog_account_guard();
DROP TRIGGER catalog_actor_no_delete ON catalog_account;
DROP TRIGGER catalog_audit_immutable ON catalog_audit;
DROP TRIGGER catalog_provenance_immutable ON catalog_provenance;
DROP TRIGGER catalog_object_immutable ON catalog_storedobject;
DROP TRIGGER catalog_dataset_immutable ON catalog_dataset;
DROP FUNCTION catalog_immutable();
ALTER TABLE catalog_upload DROP CONSTRAINT upload_object_version_fk;
ALTER TABLE catalog_storedobject DROP CONSTRAINT object_provenance_tenant_fk;
ALTER TABLE catalog_storedobject DROP CONSTRAINT object_upload_tenant_fk;
ALTER TABLE catalog_upload DROP CONSTRAINT upload_dataset_tenant_fk;
ALTER TABLE catalog_upload DROP CONSTRAINT upload_actor_tenant_fk;
ALTER TABLE catalog_grant DROP CONSTRAINT grant_dataset_tenant_fk;
ALTER TABLE catalog_grant DROP CONSTRAINT grant_actor_tenant_fk;
ALTER TABLE catalog_dataset DROP CONSTRAINT dataset_provenance_tenant_fk;
ALTER TABLE catalog_dataset DROP CONSTRAINT dataset_owner_tenant_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial"), ("runtime", "0003_runtimerun_runtime_run_tenant_identity")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
