"""Private draft ownership, tenant relations and no premature READY transition."""
from django.db import migrations

FORWARD = """
ALTER TABLE catalog_research ADD CONSTRAINT research_owner_fk FOREIGN KEY(owner_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_research ADD CONSTRAINT research_provenance_fk FOREIGN KEY(provenance_id,tenant_id) REFERENCES catalog_provenance(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_researchversion ADD CONSTRAINT research_version_parent_fk FOREIGN KEY(research_id,tenant_id) REFERENCES catalog_research(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_researchversion ADD CONSTRAINT research_version_dataset_fk FOREIGN KEY(dataset_version_id,tenant_id) REFERENCES catalog_datasetversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_researchversion ADD CONSTRAINT research_version_provenance_fk FOREIGN KEY(provenance_id,tenant_id) REFERENCES catalog_provenance(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE TRIGGER research_immutable BEFORE UPDATE OR DELETE ON catalog_research FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE TRIGGER research_version_immutable BEFORE UPDATE OR DELETE ON catalog_researchversion FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_research_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF btrim(NEW.name)='' OR NOT EXISTS(SELECT 1 FROM catalog_provenance WHERE id=NEW.provenance_id AND tenant_id=NEW.tenant_id
 AND resource_type='Research' AND resource_id=NEW.id AND document->>'creator_actor_id'=NEW.owner_id::text)
 THEN RAISE EXCEPTION 'Research provenance mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_guard BEFORE INSERT ON catalog_research FOR EACH ROW EXECUTE FUNCTION catalog_research_guard();
CREATE FUNCTION catalog_research_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key text;
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'ResearchVersion' OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'research_id' IS DISTINCT FROM NEW.research_id::text OR NEW.document->>'dataset_version_id' IS DISTINCT FROM NEW.dataset_version_id::text
 OR NEW.document->'observation_split'->>'dataset_version_id' IS DISTINCT FROM NEW.dataset_version_id::text
 OR NEW.document->>'status' IS DISTINCT FROM 'DRAFT' OR NEW.document->'revision' IS DISTINCT FROM '0'::jsonb
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NEW.document->>'current_event_cursor' IS DISTINCT FROM 'RESEARCH:' || NEW.id::text || ':0'
 OR NEW.document->'observation_split'->'sealed_final_test' IS DISTINCT FROM 'true'::jsonb
 OR NEW.document->'research_budget_usage' IS DISTINCT FROM '{"cpu_seconds":0,"gpu_seconds":0,"tokens":0,"peak_memory_bytes":0,"elapsed_wall_seconds":0,"candidates_generated":0,"candidates_accepted":0}'::jsonb
 OR NOT EXISTS(SELECT 1 FROM catalog_provenance p JOIN catalog_research r ON r.id=NEW.research_id
 WHERE p.id=NEW.provenance_id AND p.tenant_id=NEW.tenant_id AND p.resource_type='ResearchVersion' AND p.resource_id=NEW.id
 AND p.document->>'creator_actor_id'=r.owner_id::text)
 THEN RAISE EXCEPTION 'Research draft binding mismatch' USING ERRCODE='23514'; END IF;
 FOREACH key IN ARRAY ARRAY['quality_report_id','refit_policy_artifact_id','structure_assessment_artifact_id'] LOOP
  IF NEW.document->key IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Draft has fabricated result' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['frozen_submission_ids','evidence_bundle_ids'] LOOP
  IF NEW.document->key IS DISTINCT FROM '[]'::jsonb THEN RAISE EXCEPTION 'Draft has fabricated collection' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['sealed_test_id','benchmark_partition_id','benchmark_case_id'] LOOP
  IF NEW.document->'observation_split'->key IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Draft has unregistered seal' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER research_version_guard BEFORE INSERT ON catalog_researchversion FOR EACH ROW EXECUTE FUNCTION catalog_research_version_guard();
"""
REVERSE = """
DROP TRIGGER research_version_guard ON catalog_researchversion;
DROP FUNCTION catalog_research_version_guard();
DROP TRIGGER research_guard ON catalog_research;
DROP FUNCTION catalog_research_guard();
DROP TRIGGER research_version_immutable ON catalog_researchversion;
DROP TRIGGER research_immutable ON catalog_research;
ALTER TABLE catalog_researchversion DROP CONSTRAINT research_version_parent_fk, DROP CONSTRAINT research_version_dataset_fk, DROP CONSTRAINT research_version_provenance_fk;
ALTER TABLE catalog_research DROP CONSTRAINT research_owner_fk, DROP CONSTRAINT research_provenance_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0005_research_researchversion_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
