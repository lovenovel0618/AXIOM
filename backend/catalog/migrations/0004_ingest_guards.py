"""Native tenant, immutable-content and atomic business-result guards."""
from django.db import migrations

FORWARD = """
ALTER TABLE catalog_artifact ADD CONSTRAINT artifact_dataset_fk FOREIGN KEY(dataset_id,tenant_id) REFERENCES catalog_dataset(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_artifact ADD CONSTRAINT artifact_owner_fk FOREIGN KEY(owner_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_artifact ADD CONSTRAINT artifact_object_fk FOREIGN KEY(object_id,dataset_id,tenant_id) REFERENCES catalog_storedobject(id,dataset_id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_artifact ADD CONSTRAINT artifact_provenance_fk FOREIGN KEY(provenance_id,tenant_id) REFERENCES catalog_provenance(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_datasetversion ADD CONSTRAINT version_raw_fk FOREIGN KEY(raw_id,dataset_id,tenant_id) REFERENCES catalog_artifact(id,dataset_id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_datasetversion ADD CONSTRAINT version_preview_fk FOREIGN KEY(preview_id,dataset_id,tenant_id) REFERENCES catalog_artifact(id,dataset_id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_datasetversion ADD CONSTRAINT version_provenance_fk FOREIGN KEY(provenance_id,tenant_id) REFERENCES catalog_provenance(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_ingestbinding ADD CONSTRAINT binding_run_fk FOREIGN KEY(run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_ingestbinding ADD CONSTRAINT binding_upload_fk FOREIGN KEY(upload_id,dataset_id,tenant_id) REFERENCES catalog_upload(id,dataset_id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_ingestbinding ADD CONSTRAINT binding_actor_fk FOREIGN KEY(actor_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_ingestbinding ADD CONSTRAINT binding_result_fk FOREIGN KEY(result_id,dataset_id,tenant_id) REFERENCES catalog_datasetversion(id,dataset_id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE TRIGGER artifact_immutable BEFORE UPDATE OR DELETE ON catalog_artifact FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE TRIGGER version_immutable BEFORE UPDATE OR DELETE ON catalog_datasetversion FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_artifact_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'owner_id' IS DISTINCT FROM NEW.owner_id::text OR NEW.document->>'status' IS DISTINCT FROM 'AVAILABLE'
 OR NOT EXISTS(SELECT 1 FROM catalog_provenance WHERE id=NEW.provenance_id AND tenant_id=NEW.tenant_id AND resource_id=NEW.id AND resource_type='Artifact')
 OR NEW.document->>'artifact_uri' IS DISTINCT FROM '/api/v2/artifacts/' || NEW.id::text || '/content'
 THEN RAISE EXCEPTION 'Artifact identity mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.document->>'access_class'='PROJECT' AND (NEW.content IS NULL OR NEW.content->>'kind' IS NULL OR NEW.content->>'kind' NOT IN ('StructureAssessment','ImportDiagnostic'))
 THEN RAISE EXCEPTION 'Unsafe project content' USING ERRCODE='23514'; END IF;
 IF NEW.object_id IS NOT NULL AND (NEW.document->>'access_class' IS DISTINCT FROM 'SEALED_DETAIL'
 OR NEW.document->>'sha256' IS DISTINCT FROM (SELECT sha256 FROM catalog_storedobject WHERE id=NEW.object_id)
 OR (NEW.document->>'size_bytes')::bigint IS DISTINCT FROM (SELECT size_bytes FROM catalog_storedobject WHERE id=NEW.object_id))
 THEN RAISE EXCEPTION 'Raw artifact binding mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER artifact_guard BEFORE INSERT ON catalog_artifact FOR EACH ROW EXECUTE FUNCTION catalog_artifact_guard();
CREATE FUNCTION catalog_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE raw jsonb; preview jsonb;
BEGIN
 SELECT document INTO raw FROM catalog_artifact WHERE id=NEW.raw_id;
 SELECT content INTO preview FROM catalog_artifact WHERE id=NEW.preview_id;
 IF NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'dataset_id' IS DISTINCT FROM NEW.dataset_id::text OR NEW.document->>'sha256' IS DISTINCT FROM NEW.sha256
 OR NEW.document->>'artifact_id' IS DISTINCT FROM NEW.raw_id::text OR NEW.document->>'structure_preview_artifact_id' IS DISTINCT FROM NEW.preview_id::text
 OR NOT EXISTS(SELECT 1 FROM catalog_provenance WHERE id=NEW.provenance_id AND tenant_id=NEW.tenant_id AND resource_id=NEW.id AND resource_type='DatasetVersion')
 OR NOT EXISTS(SELECT 1 FROM catalog_artifact WHERE id=NEW.preview_id AND document->>'access_class'='PROJECT')
 OR raw->>'access_class' IS DISTINCT FROM 'SEALED_DETAIL'
 OR NEW.document->>'status' IS DISTINCT FROM 'AVAILABLE' OR raw->>'sha256' IS DISTINCT FROM NEW.sha256
 OR preview->>'dataset_version_id' IS DISTINCT FROM NEW.id::text OR preview->>'analysis_scope' IS DISTINCT FROM 'METADATA_ONLY'
 OR NEW.document->'row_count' IS DISTINCT FROM preview->'source_metadata'->'row_count'
 THEN RAISE EXCEPTION 'Version binding mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER version_guard BEFORE INSERT ON catalog_datasetversion FOR EACH ROW EXECUTE FUNCTION catalog_version_guard();
CREATE FUNCTION catalog_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.dataset_id IS DISTINCT FROM OLD.dataset_id
 OR NEW.upload_id IS DISTINCT FROM OLD.upload_id OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
 OR (OLD.result_id IS NOT NULL AND NEW.result_id IS DISTINCT FROM OLD.result_id)
 OR (OLD.error_code IS NOT NULL AND NEW.error_code IS DISTINCT FROM OLD.error_code)
 OR (NEW.result_id IS NOT NULL AND NEW.error_code IS NOT NULL)
 THEN RAISE EXCEPTION 'Immutable ingest binding' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER binding_guard BEFORE UPDATE ON catalog_ingestbinding FOR EACH ROW EXECUTE FUNCTION catalog_binding_guard();
CREATE TRIGGER binding_no_delete BEFORE DELETE ON catalog_ingestbinding FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_business_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE identity uuid; r runtime_runtimerun; b catalog_ingestbinding; u catalog_upload;
BEGIN
 IF TG_TABLE_NAME='runtime_runtimerun' THEN identity:=NEW.id; ELSE identity:=NEW.run_id; END IF;
 SELECT * INTO r FROM runtime_runtimerun WHERE id=identity;
 IF r.control_only THEN RETURN NULL; END IF;
 SELECT * INTO b FROM catalog_ingestbinding WHERE run_id=identity;
 SELECT * INTO u FROM catalog_upload WHERE id=b.upload_id;
 IF b.run_id IS NULL OR b.tenant_id IS DISTINCT FROM r.tenant_id OR b.dataset_id::text IS DISTINCT FROM r.document->>'dataset_id'
 OR u.ingest_run_id IS DISTINCT FROM r.id OR u.status IS DISTINCT FROM 'COMPLETED'
 OR NOT EXISTS(SELECT 1 FROM catalog_artifact WHERE id=(r.document->>'input_artifact_id')::uuid AND tenant_id=r.tenant_id AND dataset_id=b.dataset_id
 AND content->>'run_id'=r.id::text AND content->>'kind'='TaskInput'
 AND content=(SELECT task_input FROM runtime_inputsnapshot WHERE run_id=r.id)
 AND content->'payload'->>'upload_session_id'=u.id::text AND content->'payload'->>'expected_sha256'=u.sha256
 AND content->'payload'->>'object_version'=u.object_version::text)
 OR (r.document->>'status'='SUCCEEDED' AND b.result_id IS NULL)
 OR (b.result_id IS NOT NULL AND r.document->>'status' IS DISTINCT FROM 'SUCCEEDED')
 THEN RAISE EXCEPTION 'Atomic business ingest binding required' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER business_run_guard AFTER INSERT OR UPDATE ON runtime_runtimerun DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_business_guard();
CREATE CONSTRAINT TRIGGER business_binding_guard AFTER INSERT OR UPDATE ON catalog_ingestbinding DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_business_guard();
"""
REVERSE = """
DROP TRIGGER business_binding_guard ON catalog_ingestbinding;
DROP TRIGGER business_run_guard ON runtime_runtimerun;
DROP FUNCTION catalog_business_guard();
DROP TRIGGER binding_no_delete ON catalog_ingestbinding;
DROP TRIGGER binding_guard ON catalog_ingestbinding;
DROP FUNCTION catalog_binding_guard();
DROP TRIGGER version_guard ON catalog_datasetversion;
DROP FUNCTION catalog_version_guard();
DROP TRIGGER artifact_guard ON catalog_artifact;
DROP FUNCTION catalog_artifact_guard();
DROP TRIGGER artifact_immutable ON catalog_artifact;
DROP TRIGGER version_immutable ON catalog_datasetversion;
ALTER TABLE catalog_artifact DROP CONSTRAINT artifact_dataset_fk, DROP CONSTRAINT artifact_owner_fk, DROP CONSTRAINT artifact_object_fk, DROP CONSTRAINT artifact_provenance_fk;
ALTER TABLE catalog_datasetversion DROP CONSTRAINT version_raw_fk, DROP CONSTRAINT version_preview_fk, DROP CONSTRAINT version_provenance_fk;
ALTER TABLE catalog_ingestbinding DROP CONSTRAINT binding_run_fk, DROP CONSTRAINT binding_upload_fk, DROP CONSTRAINT binding_actor_fk, DROP CONSTRAINT binding_result_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_artifact_datasetversion_ingestbinding_and_more"), ("runtime", "0004_remove_runtimerun_runtime_control_only")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
