"""Guard immutable execution inputs even against QuerySet.update and raw SQL."""
from django.db import migrations

FORWARD = """
CREATE FUNCTION runtime_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE field text;
BEGIN
  IF NEW.document->>'id' IS DISTINCT FROM NEW.id::text
    OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
    OR NEW.document->>'root_run_id' IS DISTINCT FROM NEW.id::text
    OR NEW.document->>'type' IS DISTINCT FROM 'INGEST'
    OR NEW.document->'is_root' IS DISTINCT FROM 'true'::jsonb
    OR NEW.document->'parent_run_id' IS DISTINCT FROM 'null'::jsonb
    OR NEW.document->>'status' IS NULL
    OR NEW.document->>'status' NOT IN ('QUEUED','RUNNING','CANCEL_REQUESTED','SUCCEEDED','FAILED','CANCELLED')
  THEN RAISE EXCEPTION 'Invalid runtime root identity' USING ERRCODE = '23514'; END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
    THEN RAISE EXCEPTION 'Immutable runtime identity' USING ERRCODE = '23514'; END IF;
    FOREACH field IN ARRAY ARRAY['id','tenant_id','type','research_version_id','dataset_id','seed','environment_digest','input_artifact_id','execution_manifest_id','budget_account_id','research_budget_account_id','provenance_id','root_run_id','parent_run_id','is_root','created_at'] LOOP
      IF NEW.document->field IS DISTINCT FROM OLD.document->field
      THEN RAISE EXCEPTION 'Immutable runtime binding' USING ERRCODE = '23514'; END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER runtime_run_guard BEFORE INSERT OR UPDATE ON runtime_runtimerun FOR EACH ROW EXECUTE FUNCTION runtime_run_guard();
CREATE FUNCTION runtime_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Immutable runtime snapshot or event' USING ERRCODE = '23514'; END $$;
CREATE TRIGGER runtime_input_immutable BEFORE UPDATE OR DELETE ON runtime_inputsnapshot FOR EACH ROW EXECUTE FUNCTION runtime_immutable_guard();
CREATE TRIGGER runtime_event_immutable BEFORE UPDATE OR DELETE ON runtime_runevent FOR EACH ROW EXECUTE FUNCTION runtime_immutable_guard();
CREATE FUNCTION runtime_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.document->>'id' IS DISTINCT FROM NEW.id::text
    OR NEW.document->>'run_id' IS DISTINCT FROM NEW.run_id::text
    OR NEW.document->>'generation' IS DISTINCT FROM NEW.generation::text
    OR NEW.document->>'tenant_id' IS DISTINCT FROM (SELECT tenant_id::text FROM runtime_runtimerun WHERE id=NEW.run_id)
    OR NEW.generation < 1
    OR NEW.document->>'status' IS NULL
    OR NEW.document->>'status' NOT IN ('RUNNING','SUCCEEDED','FAILED','CANCELLED','EXPIRED')
  THEN RAISE EXCEPTION 'Invalid attempt identity or state' USING ERRCODE = '23514'; END IF;
  IF TG_OP='UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.generation IS DISTINCT FROM OLD.generation)
  THEN RAISE EXCEPTION 'Immutable attempt identity' USING ERRCODE = '23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER runtime_attempt_guard BEFORE INSERT OR UPDATE ON runtime_runtimeattempt FOR EACH ROW EXECUTE FUNCTION runtime_attempt_guard();
"""
REVERSE = """
DROP TRIGGER runtime_attempt_guard ON runtime_runtimeattempt;
DROP FUNCTION runtime_attempt_guard();
DROP TRIGGER runtime_event_immutable ON runtime_runevent;
DROP TRIGGER runtime_input_immutable ON runtime_inputsnapshot;
DROP FUNCTION runtime_immutable_guard();
DROP TRIGGER runtime_run_guard ON runtime_runtimerun;
DROP FUNCTION runtime_run_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("runtime", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
