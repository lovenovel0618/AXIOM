"""Native private-inspection identity and immutable snapshot constraints."""
from django.db import migrations

FORWARD = """
ALTER TABLE catalog_researchinspection ADD CONSTRAINT inspection_actor_fk FOREIGN KEY(actor_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_researchinspection ADD CONSTRAINT inspection_version_fk FOREIGN KEY(research_version_id,tenant_id) REFERENCES catalog_researchversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE TRIGGER inspection_immutable BEFORE UPDATE OR DELETE ON catalog_researchinspection FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_inspection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version catalog_researchversion; dataset catalog_datasetversion;
BEGIN
 SELECT * INTO version FROM catalog_researchversion WHERE id=NEW.research_version_id;
 SELECT * INTO dataset FROM catalog_datasetversion WHERE id=version.dataset_version_id;
 IF NEW.document->>'kind' IS DISTINCT FROM 'ResearchInspection' OR NEW.document->>'schema_version' IS DISTINCT FROM '1.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text OR NEW.document->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR NEW.document->>'request_hash' IS DISTINCT FROM NEW.request_hash OR NEW.request_hash !~ '^[0-9a-f]{64}$'
 OR NEW.document->>'research_status' IS DISTINCT FROM 'DRAFT' OR NEW.document->>'product_gate_status' IS DISTINCT FROM 'NOT_RUN'
 OR NEW.document->>'usage_scope' IS DISTINCT FROM 'LOCAL_PREFLIGHT_EXECUTION_ONLY'
 OR NEW.configuration->'research' IS DISTINCT FROM version.document
 OR NEW.configuration->>'source_sha256' IS DISTINCT FROM dataset.sha256
 OR NEW.document->>'source_sha256' IS DISTINCT FROM dataset.sha256
 OR NEW.configuration->>'source_object_version' IS DISTINCT FROM (SELECT object_id::text FROM catalog_artifact WHERE id=dataset.raw_id)
 OR NEW.configuration->'metadata' IS DISTINCT FROM (SELECT content->'source_metadata' FROM catalog_artifact WHERE id=dataset.preview_id)
 OR NEW.document->>'environment_digest' IS DISTINCT FROM NEW.configuration->>'environment_digest'
 OR NOT EXISTS(SELECT 1 FROM catalog_research WHERE id=version.research_id AND owner_id=NEW.actor_id AND tenant_id=NEW.tenant_id)
 THEN RAISE EXCEPTION 'Research inspection binding mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER inspection_guard BEFORE INSERT ON catalog_researchinspection FOR EACH ROW EXECUTE FUNCTION catalog_inspection_guard();
"""
REVERSE = """
DROP TRIGGER inspection_guard ON catalog_researchinspection;
DROP FUNCTION catalog_inspection_guard();
DROP TRIGGER inspection_immutable ON catalog_researchinspection;
ALTER TABLE catalog_researchinspection DROP CONSTRAINT inspection_actor_fk, DROP CONSTRAINT inspection_version_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0007_researchinspection")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
