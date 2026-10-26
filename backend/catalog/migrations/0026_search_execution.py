"""SEARCH 活躍狀態綁真實快照／root 帳本；停止證明不可改刪，保留既有 PROFILE 與 READY 防線。"""
from importlib import import_module
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

PREVIOUS = import_module("catalog.migrations.0012_ready_guard")
BASE = PREVIOUS.STATE_BASE.replace(" RETURN NEW;", PREVIOUS.SEAL_CHECK + " RETURN NEW;")
OLD = """ IF (NEW.status='VALIDATING') IS DISTINCT FROM (NEW.active_run_id IS NOT NULL)
 THEN RAISE EXCEPTION 'Research active run mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.active_run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM catalog_profilebinding WHERE run_id=NEW.active_run_id AND research_version_id=NEW.research_version_id AND tenant_id=NEW.tenant_id)
 THEN RAISE EXCEPTION 'Research PROFILE mismatch' USING ERRCODE='23514'; END IF;"""
NEW = """ IF (NEW.status IN ('VALIDATING','RUNNING')) IS DISTINCT FROM (NEW.active_run_id IS NOT NULL)
 THEN RAISE EXCEPTION 'Research active run mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.status='VALIDATING' AND NOT EXISTS(SELECT 1 FROM catalog_profilebinding WHERE run_id=NEW.active_run_id AND research_version_id=NEW.research_version_id AND tenant_id=NEW.tenant_id)
 THEN RAISE EXCEPTION 'Research PROFILE mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.status='RUNNING' AND NOT EXISTS(SELECT 1 FROM runtime_runtimerun r
 JOIN runtime_inputsnapshot s ON s.run_id=r.id JOIN catalog_rootbudget b ON b.run_id=r.id
 WHERE r.id=NEW.active_run_id AND r.tenant_id=NEW.tenant_id AND NOT r.control_only
 AND r.document->>'type'='SEARCH' AND r.document->'is_root'='true'::jsonb
 AND r.document->>'research_version_id'=NEW.research_version_id::text)
 THEN RAISE EXCEPTION 'Research SEARCH mismatch' USING ERRCODE='23514'; END IF;"""
if OLD not in BASE:
    raise RuntimeError("State guard changed")


PROFILE = import_module("catalog.migrations.0010_profile_guards")
BUDGET_BASE = PROFILE.forward_sql.split("CREATE FUNCTION catalog_budget_guard()", 1)[1].split("CREATE TRIGGER research_budget_guard", 1)[0]
BUDGET_SQL = "CREATE OR REPLACE FUNCTION catalog_budget_guard()" + BUDGET_BASE.replace("document->>'type'='PROFILE'", "document->>'type' IN ('PROFILE','SEARCH')")
BUSINESS_BASE = import_module("catalog.migrations.0024_validate_business_guard").forward_sql
SEARCH_CHECK = """
 IF r.document->>'type'='SEARCH' AND r.document->'is_root'='true'::jsonb
 AND EXISTS(SELECT 1 FROM runtime_inputsnapshot WHERE run_id=r.id) THEN
  IF NOT EXISTS(SELECT 1 FROM catalog_rootbudget search_budget
   JOIN catalog_researchbudget a ON a.id=search_budget.research_budget_id
   JOIN catalog_researchversion v ON v.id=a.research_version_id
   JOIN runtime_inputsnapshot s ON s.run_id=r.id
   JOIN catalog_artifact i ON i.id=(r.document->>'input_artifact_id')::uuid
   JOIN catalog_artifact p ON p.id=(s.task_input->'payload'->>'projection_artifact_id')::uuid
   WHERE search_budget.run_id=r.id AND search_budget.tenant_id=r.tenant_id AND v.tenant_id=r.tenant_id
   AND r.document->>'research_version_id'=v.id::text
   AND r.document->>'research_budget_account_id'=a.id::text AND r.document->>'budget_account_id'=search_budget.id::text
   AND i.tenant_id=r.tenant_id AND i.research_version_id=v.id AND i.content=s.task_input
   AND i.document->>'access_class'='SEALED_DETAIL'
   AND p.tenant_id=r.tenant_id AND p.research_version_id=v.id AND p.document->>'access_class'='SEALED_DETAIL'
   AND p.content->>'kind'='SearchProjectionSource'
   AND p.content->'fit'=v.document->'observation_split'->'fit'
   AND p.content->'development'=v.document->'observation_split'->'development'
   AND p.content->'semantic_profile'=v.document->'semantic_profile'
   AND p.content->'domain'=v.document->'domain'
   AND r.document->'budget_usage'=search_budget.document->'usage'
   AND r.document->'budget_reservations'=search_budget.document->'reservations'
   AND (r.document->>'status' NOT IN ('QUEUED','RUNNING','CANCEL_REQUESTED') OR EXISTS(
    SELECT 1 FROM catalog_researchstate z WHERE z.active_run_id=r.id AND z.research_version_id=v.id AND z.status='RUNNING'))
   AND (r.document->>'status' NOT IN ('SUCCEEDED','FAILED','CANCELLED') OR NOT EXISTS(
    SELECT 1 FROM catalog_researchstate z WHERE z.active_run_id=r.id)))
  THEN RAISE EXCEPTION 'Atomic SEARCH authority required' USING ERRCODE='23514'; END IF;
 END IF;
"""
BUSINESS_SQL = BUSINESS_BASE.replace(" IF r.control_only THEN RETURN NULL; END IF;", " IF r.control_only THEN RETURN NULL; END IF;" + SEARCH_CHECK)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0025_research_event_submission_frozen"), ("runtime", "0014_child_runs")]
    operations = [
        migrations.RemoveConstraint(model_name="researchstate", name="research_state_local_status"),
        migrations.AddConstraint(model_name="researchstate", constraint=models.CheckConstraint(condition=models.Q(status__in=["DRAFT", "VALIDATING", "READY", "RUNNING", "FAILED", "CANCELLED"]), name="research_state_local_status")),
        migrations.CreateModel(name="SearchAttemptStop", fields=[
            ("attempt", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, serialize=False, to="runtime.runtimeattempt")),
            ("created_at", models.DateTimeField(default=django.utils.timezone.now))]),
        migrations.RunSQL(BUDGET_SQL, "CREATE OR REPLACE FUNCTION catalog_budget_guard()" + BUDGET_BASE),
        migrations.RunSQL(BUSINESS_SQL, BUSINESS_BASE),
        migrations.RunSQL("CREATE OR REPLACE FUNCTION catalog_state_guard()" + BASE.replace(OLD, NEW), "CREATE OR REPLACE FUNCTION catalog_state_guard()" + BASE),
        migrations.RunSQL("CREATE TRIGGER search_stop_immutable BEFORE UPDATE OR DELETE ON catalog_searchattemptstop FOR EACH ROW EXECUTE FUNCTION catalog_immutable();", "DROP TRIGGER search_stop_immutable ON catalog_searchattemptstop;")]
