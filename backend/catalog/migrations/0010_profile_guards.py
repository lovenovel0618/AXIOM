"""帳本與 PROFILE 的原生跨表防線。

同租戶複合 FK 保護關聯；限額／身分不可改，receipt 與事件不可改刪。
延遲 constraint trigger 在交易末核對研究合計與各 root 最新 receipt，容許同交易內先後更新。
QualityReport 只允許遮罩／fit 白名單；已有 PROFILE 資料時禁止無備份直接降版。"""
from importlib import import_module
from uuid import uuid4
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.utils import timezone

PREVIOUS = import_module("catalog.migrations.0004_ingest_guards")
ARTIFACT_BASE = PREVIOUS.FORWARD.split("CREATE FUNCTION catalog_artifact_guard()",1)[1].split("CREATE TRIGGER artifact_guard",1)[0]
BUSINESS_BASE = PREVIOUS.FORWARD.split("CREATE FUNCTION catalog_business_guard()",1)[1].split("CREATE CONSTRAINT TRIGGER business_run_guard",1)[0]

PROFILE_CHECK = """
 IF r.document->>'type'='PROFILE' THEN
  IF NOT EXISTS(SELECT 1 FROM catalog_profilebinding p
    JOIN catalog_researchversion v ON v.id=p.research_version_id AND v.tenant_id=p.tenant_id
    JOIN catalog_datasetversion d ON d.id=v.dataset_version_id AND d.tenant_id=p.tenant_id AND d.dataset_id=p.dataset_id
    JOIN catalog_rootbudget profile_budget ON profile_budget.id=p.root_budget_id AND profile_budget.run_id=p.run_id AND profile_budget.tenant_id=p.tenant_id
    JOIN catalog_researchbudget a ON a.id=profile_budget.research_budget_id AND a.research_version_id=v.id AND a.tenant_id=p.tenant_id
    JOIN catalog_reservation h ON h.root_id=profile_budget.id
    JOIN runtime_inputsnapshot s ON s.run_id=r.id
    JOIN catalog_artifact i ON i.id=(r.document->>'input_artifact_id')::uuid AND i.research_version_id=v.id AND i.tenant_id=p.tenant_id
    WHERE p.run_id=r.id AND p.tenant_id=r.tenant_id AND p.research_version_id::text=r.document->>'research_version_id'
    AND profile_budget.id::text=r.document->>'budget_account_id' AND a.id::text=r.document->>'research_budget_account_id'
    AND r.document->'budget_usage'=profile_budget.document->'usage' AND r.document->'budget_reservations'=profile_budget.document->'reservations'
    AND i.content=s.task_input AND i.document->>'access_class'='SEALED_DETAIL'
    AND s.task_input->>'research_version_id'=v.id::text AND s.task_input->'payload'->>'dataset_version_id'=d.id::text
    AND s.task_input->'payload'->'semantic_profile'=v.document->'semantic_profile'
    AND s.task_input->'payload'->'observation_split'=v.document->'observation_split'
    AND s.task_input->'payload'->'domain'=v.document->'domain' AND s.task_input->'payload'->'evaluation_policy'=v.document->'evaluation_policy'
    AND NOT EXISTS(SELECT 1 FROM catalog_researchstate z WHERE z.active_run_id=r.id AND r.document->>'status' IN ('SUCCEEDED','FAILED','CANCELLED'))
    AND (r.document->>'status' NOT IN ('QUEUED','RUNNING','CANCEL_REQUESTED') OR EXISTS(SELECT 1 FROM catalog_researchstate z WHERE z.research_version_id=v.id AND z.active_run_id=r.id AND z.status='VALIDATING'))
    AND (r.document->>'status'<>'SUCCEEDED' OR (p.result_id IS NOT NULL AND profile_budget.document->>'status'='CLOSED' AND h.state='RELEASED'))
    AND (p.result_id IS NULL OR r.document->>'status'='SUCCEEDED'))
  THEN RAISE EXCEPTION 'Atomic PROFILE authority required' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
"""
ARTIFACT_EXTRA = """
 IF NEW.research_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM catalog_researchversion v
 JOIN catalog_research q ON q.id=v.research_id JOIN catalog_datasetversion d ON d.id=v.dataset_version_id
 WHERE v.id=NEW.research_version_id AND v.tenant_id=NEW.tenant_id AND d.dataset_id=NEW.dataset_id AND q.owner_id=NEW.owner_id)
 THEN RAISE EXCEPTION 'Private research artifact mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.research_version_id IS NOT NULL AND NEW.content->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
 THEN RAISE EXCEPTION 'Research content identity mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.content->>'kind'='QualityReport' THEN
  IF NEW.research_version_id IS NULL OR NEW.content->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
  OR NEW.content - ARRAY['kind','schema_version','research_version_id','run_id','quality','blocking_code','fit_summary','readiness','remaining','precision_bits'] <> '{}'::jsonb
  OR NEW.content->>'schema_version' IS DISTINCT FROM '1.0'
  OR NEW.content->'remaining' IS DISTINCT FROM '["SEALED_TEST_NOT_REGISTERED"]'::jsonb OR NEW.content->'precision_bits' IS DISTINCT FROM '53'::jsonb
  OR NEW.content->>'readiness' IS DISTINCT FROM 'BLOCKED' OR NEW.content->>'quality' IS NULL OR NEW.content->>'quality' NOT IN ('PASS','BLOCKED')
  OR (NEW.content->>'quality'='BLOCKED' AND NEW.content->'fit_summary' IS DISTINCT FROM 'null'::jsonb)
  THEN RAISE EXCEPTION 'Unsafe quality report' USING ERRCODE='23514'; END IF;
  IF NEW.content->>'quality'='PASS' AND (jsonb_typeof(NEW.content->'fit_summary') IS DISTINCT FROM 'object'
   OR (NEW.content->'fit_summary') - ARRAY['selected_count','unique_x','target_min','target_max','target_mean','target_iqr'] <> '{}'::jsonb)
  THEN RAISE EXCEPTION 'Unsafe fit-only summary' USING ERRCODE='23514'; END IF;
 END IF;
"""
forward_sql = """
ALTER TABLE catalog_artifact ADD CONSTRAINT artifact_research_fk FOREIGN KEY(research_version_id,tenant_id) REFERENCES catalog_researchversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_researchbudget ADD CONSTRAINT budget_version_fk FOREIGN KEY(research_version_id,tenant_id) REFERENCES catalog_researchversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_rootbudget ADD CONSTRAINT root_budget_run_fk FOREIGN KEY(run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_rootbudget ADD CONSTRAINT root_budget_research_fk FOREIGN KEY(research_budget_id,tenant_id) REFERENCES catalog_researchbudget(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_profilebinding ADD CONSTRAINT profile_run_fk FOREIGN KEY(run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_profilebinding ADD CONSTRAINT profile_version_fk FOREIGN KEY(research_version_id,tenant_id) REFERENCES catalog_researchversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_profilebinding ADD CONSTRAINT profile_dataset_fk FOREIGN KEY(dataset_id,tenant_id) REFERENCES catalog_dataset(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_profilebinding ADD CONSTRAINT profile_actor_fk FOREIGN KEY(actor_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_profilebinding ADD CONSTRAINT profile_root_budget_fk FOREIGN KEY(root_budget_id,tenant_id) REFERENCES catalog_rootbudget(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_researchstate ADD CONSTRAINT state_version_fk FOREIGN KEY(research_version_id,tenant_id) REFERENCES catalog_researchversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_researchstate ADD CONSTRAINT state_run_fk FOREIGN KEY(active_run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION catalog_budget_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key text; doc_kind text;
BEGIN
 doc_kind:=CASE WHEN TG_TABLE_NAME='catalog_researchbudget' THEN 'ResearchBudgetAccount' ELSE 'BudgetAccount' END;
 IF NEW.document->>'kind' IS DISTINCT FROM doc_kind OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text
 OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR NEW.document->>'status' IS NULL OR NEW.document->>'status' NOT IN ('OPEN','CLOSING','CLOSED')
 THEN RAISE EXCEPTION 'Invalid budget identity' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='catalog_researchbudget' THEN
  IF NEW.document->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
  OR NEW.document->'limit' IS DISTINCT FROM (SELECT document->'budget' FROM catalog_researchversion WHERE id=NEW.research_version_id)
  THEN RAISE EXCEPTION 'Research limit mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.document->>'root_run_id' IS DISTINCT FROM NEW.run_id::text OR NEW.document->>'research_budget_account_id' IS DISTINCT FROM NEW.research_budget_id::text
  THEN RAISE EXCEPTION 'Root limit binding mismatch' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT 1 FROM runtime_runtimerun WHERE id=NEW.run_id AND tenant_id=NEW.tenant_id AND NOT control_only AND document->>'type'='PROFILE'
   AND document->>'budget_account_id'=NEW.id::text AND document->>'research_budget_account_id'=NEW.research_budget_id::text)
  THEN RAISE EXCEPTION 'Only a bound PROFILE owns this account' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='UPDATE' THEN
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
  OR NEW.document - ARRAY['usage','reservations','status'] IS DISTINCT FROM OLD.document - ARRAY['usage','reservations','status']
  OR (OLD.document->>'status'='CLOSED' AND NEW.document->>'status'<>'CLOSED')
  OR (OLD.document->>'status'='CLOSING' AND NEW.document->>'status'='OPEN')
  THEN RAISE EXCEPTION 'Immutable budget limits' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='catalog_researchbudget' THEN
   IF NEW.research_version_id IS DISTINCT FROM OLD.research_version_id THEN RAISE EXCEPTION 'Immutable research account' USING ERRCODE='23514'; END IF;
  ELSE
   IF NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.research_budget_id IS DISTINCT FROM OLD.research_budget_id THEN RAISE EXCEPTION 'Immutable root account' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 FOREACH key IN ARRAY ARRAY['cpu_seconds','gpu_seconds','tokens','peak_memory_bytes','elapsed_wall_seconds','candidates_generated','candidates_accepted'] LOOP
  IF jsonb_typeof(NEW.document->'usage'->key) IS DISTINCT FROM 'number' OR (NEW.document->'usage'->>key)::numeric<0
  THEN RAISE EXCEPTION 'Invalid usage projection' USING ERRCODE='23514'; END IF;
  IF TG_OP='UPDATE' AND (NEW.document->'usage'->>key)::numeric<(OLD.document->'usage'->>key)::numeric
  THEN RAISE EXCEPTION 'Usage cannot decrease' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER research_budget_guard BEFORE INSERT OR UPDATE ON catalog_researchbudget FOR EACH ROW EXECUTE FUNCTION catalog_budget_guard();
CREATE TRIGGER root_budget_guard BEFORE INSERT OR UPDATE ON catalog_rootbudget FOR EACH ROW EXECUTE FUNCTION catalog_budget_guard();
CREATE FUNCTION catalog_reservation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key text;
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.requested IS DISTINCT FROM (SELECT document->'limit' FROM catalog_rootbudget WHERE id=NEW.root_id) OR NEW.held IS DISTINCT FROM NEW.requested OR NEW.state<>'HELD'
  THEN RAISE EXCEPTION 'Reservation limit mismatch' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.root_id IS DISTINCT FROM OLD.root_id OR NEW.requested IS DISTINCT FROM OLD.requested OR (OLD.state='RELEASED' AND NEW.state<>'RELEASED')
  THEN RAISE EXCEPTION 'Immutable reservation binding' USING ERRCODE='23514'; END IF;
  FOR key IN SELECT jsonb_object_keys(NEW.requested) LOOP
   IF jsonb_typeof(NEW.held->key) IS DISTINCT FROM 'number' OR (NEW.held->>key)::numeric<0 OR (NEW.held->>key)::numeric>(OLD.held->>key)::numeric OR (NEW.state='RELEASED' AND (NEW.held->>key)::numeric<>0)
   THEN RAISE EXCEPTION 'Invalid remaining reservation' USING ERRCODE='23514'; END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER reservation_guard BEFORE INSERT OR UPDATE ON catalog_reservation FOR EACH ROW EXECUTE FUNCTION catalog_reservation_guard();
CREATE FUNCTION catalog_usage_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'UsageReport' OR NEW.document->>'usage_event_id' IS DISTINCT FROM NEW.id::text
 OR NEW.document->>'attempt_id' IS DISTINCT FROM NEW.attempt_id::text OR NEW.document->>'sequence' IS DISTINCT FROM NEW.sequence::text
 OR NOT EXISTS(SELECT 1 FROM catalog_rootbudget b JOIN runtime_runtimeattempt a ON a.run_id=b.run_id
 WHERE b.id=NEW.root_id AND a.id=NEW.attempt_id AND b.run_id::text=NEW.document->>'run_id' AND b.tenant_id::text=NEW.document->>'tenant_id')
 THEN RAISE EXCEPTION 'Usage receipt binding mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER usage_receipt_guard BEFORE INSERT ON catalog_usagereceipt FOR EACH ROW EXECUTE FUNCTION catalog_usage_guard();
CREATE FUNCTION catalog_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE artifact uuid;
BEGIN
 IF TG_OP='UPDATE' AND (NEW.research_version_id IS DISTINCT FROM OLD.research_version_id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.revision<>OLD.revision+1)
 THEN RAISE EXCEPTION 'Research state revision mismatch' USING ERRCODE='23514'; END IF;
 IF (NEW.status='VALIDATING') IS DISTINCT FROM (NEW.active_run_id IS NOT NULL)
 THEN RAISE EXCEPTION 'Research active run mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.active_run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM catalog_profilebinding WHERE run_id=NEW.active_run_id AND research_version_id=NEW.research_version_id AND tenant_id=NEW.tenant_id)
 THEN RAISE EXCEPTION 'Research PROFILE mismatch' USING ERRCODE='23514'; END IF;
 FOREACH artifact IN ARRAY ARRAY[NEW.quality_id,NEW.structure_id] LOOP
  IF artifact IS NOT NULL AND NOT EXISTS(SELECT 1 FROM catalog_artifact WHERE id=artifact AND research_version_id=NEW.research_version_id AND tenant_id=NEW.tenant_id)
  THEN RAISE EXCEPTION 'Research result mismatch' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER state_guard BEFORE INSERT OR UPDATE ON catalog_researchstate FOR EACH ROW EXECUTE FUNCTION catalog_state_guard();
CREATE FUNCTION catalog_profile_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.research_version_id IS DISTINCT FROM OLD.research_version_id
 OR NEW.dataset_id IS DISTINCT FROM OLD.dataset_id OR NEW.actor_id IS DISTINCT FROM OLD.actor_id OR NEW.root_budget_id IS DISTINCT FROM OLD.root_budget_id
 OR (OLD.result_id IS NOT NULL AND NEW.result_id IS DISTINCT FROM OLD.result_id) OR (OLD.error_code IS NOT NULL AND NEW.error_code IS DISTINCT FROM OLD.error_code))
 THEN RAISE EXCEPTION 'Immutable PROFILE identity' USING ERRCODE='23514'; END IF;
 IF NEW.result_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM catalog_artifact WHERE id=NEW.result_id AND research_version_id=NEW.research_version_id AND tenant_id=NEW.tenant_id AND content->>'kind'='QualityReport')
 THEN RAISE EXCEPTION 'PROFILE result mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER profile_binding_guard BEFORE INSERT OR UPDATE ON catalog_profilebinding FOR EACH ROW EXECUTE FUNCTION catalog_profile_binding_guard();
CREATE FUNCTION catalog_research_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'event_id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'sequence' IS DISTINCT FROM NEW.sequence::text
 OR NEW.document->>'stream_scope' IS DISTINCT FROM 'RESEARCH' OR NEW.document->>'stream_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NEW.document->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NOT EXISTS(SELECT 1 FROM catalog_researchstate s WHERE s.research_version_id=NEW.research_version_id AND s.tenant_id::text=NEW.document->>'tenant_id'
 AND s.revision=NEW.sequence AND s.status=NEW.document->'payload'->>'status')
 THEN RAISE EXCEPTION 'Research event mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_event_guard BEFORE INSERT ON catalog_researchevent FOR EACH ROW EXECUTE FUNCTION catalog_research_event_guard();
"""
forward_sql += "CREATE OR REPLACE FUNCTION catalog_artifact_guard()" + ARTIFACT_BASE.replace("'StructureAssessment','ImportDiagnostic'", "'StructureAssessment','ImportDiagnostic','QualityReport'").replace(" RETURN NEW;",ARTIFACT_EXTRA+" RETURN NEW;")
forward_sql += "CREATE OR REPLACE FUNCTION catalog_business_guard()" + BUSINESS_BASE.replace(" SELECT * INTO b FROM catalog_ingestbinding",PROFILE_CHECK+" SELECT * INTO b FROM catalog_ingestbinding")
forward_sql += """
CREATE CONSTRAINT TRIGGER business_profile_guard AFTER INSERT OR UPDATE ON catalog_profilebinding DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_business_guard();
"""
for table in ("researchbudget","rootbudget","reservation","usagereceipt","researchstate","profilebinding","researchevent"):
    forward_sql += f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON catalog_{table} FOR EACH ROW EXECUTE FUNCTION catalog_immutable();\n"
for table in ("usagereceipt","researchevent"):
    forward_sql += f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON catalog_{table} FOR EACH ROW EXECUTE FUNCTION catalog_immutable();\n"

forward_sql += """
CREATE FUNCTION catalog_budget_total_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE account uuid; key text; total numeric; projected numeric; budget catalog_researchbudget; root catalog_rootbudget;
BEGIN
 IF TG_TABLE_NAME='catalog_researchbudget' THEN account:=NEW.id;
 ELSIF TG_TABLE_NAME='catalog_rootbudget' THEN account:=NEW.research_budget_id;
 ELSE SELECT research_budget_id INTO account FROM catalog_rootbudget WHERE id=NEW.root_id; END IF;
 SELECT * INTO budget FROM catalog_researchbudget WHERE id=account;
 FOREACH key IN ARRAY ARRAY['cpu_seconds','gpu_seconds','tokens','peak_memory_bytes','elapsed_wall_seconds','candidates_generated','candidates_accepted'] LOOP
  IF key='peak_memory_bytes' THEN
   SELECT COALESCE(MAX((document->'usage'->>key)::numeric),0) INTO total FROM catalog_rootbudget WHERE research_budget_id=account;
  ELSE
   SELECT COALESCE(SUM((document->'usage'->>key)::numeric),0) INTO total FROM catalog_rootbudget WHERE research_budget_id=account;
  END IF;
  IF total IS DISTINCT FROM (budget.document->'usage'->>key)::numeric THEN RAISE EXCEPTION 'Atomic research usage projection required' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR root IN SELECT * FROM catalog_rootbudget WHERE research_budget_id=account LOOP
  FOREACH key IN ARRAY ARRAY['cpu_seconds','gpu_seconds','tokens','peak_memory_bytes','elapsed_wall_seconds','candidates_generated','candidates_accepted'] LOOP
   SELECT CASE WHEN key='peak_memory_bytes' THEN COALESCE(MAX((q.document->'cumulative_usage'->>key)::numeric),0) ELSE COALESCE(SUM((q.document->'cumulative_usage'->>key)::numeric),0) END INTO projected FROM
    (SELECT DISTINCT ON (attempt_id) document FROM catalog_usagereceipt WHERE root_id=root.id ORDER BY attempt_id,sequence DESC) q;
   IF projected IS DISTINCT FROM (root.document->'usage'->>key)::numeric THEN RAISE EXCEPTION 'Receipt/root usage mismatch' USING ERRCODE='23514'; END IF;
  END LOOP;
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER research_budget_total AFTER INSERT OR UPDATE ON catalog_researchbudget DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_budget_total_guard();
CREATE CONSTRAINT TRIGGER root_budget_total AFTER INSERT OR UPDATE ON catalog_rootbudget DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_budget_total_guard();
CREATE CONSTRAINT TRIGGER receipt_budget_total AFTER INSERT ON catalog_usagereceipt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_budget_total_guard();
"""


def backfill(apps: StateApps, _schema: BaseDatabaseSchemaEditor) -> None:
    version_model = apps.get_model("catalog","ResearchVersion")
    account_model = apps.get_model("catalog","ResearchBudget")
    for version in version_model.objects.all().iterator(chunk_size=100):
        identity = uuid4()
        usage = dict.fromkeys(["cpu_seconds","gpu_seconds","tokens","peak_memory_bytes","elapsed_wall_seconds","candidates_generated","candidates_accepted"],0)
        account_model.objects.get_or_create(research_version_id=version.pk,defaults={"id":identity,"tenant_id":version.tenant_id,"document":{
            "kind":"ResearchBudgetAccount","id":str(identity),"tenant_id":str(version.tenant_id),"schema_version":"2.0","created_at":timezone.now().isoformat(),"research_version_id":str(version.pk),
            "limit":version.document["budget"],"usage":usage,"reservations":[],"status":"OPEN"}})


reverse_sql = "DO $$ BEGIN IF EXISTS(SELECT 1 FROM catalog_profilebinding) THEN RAISE EXCEPTION 'PROFILE data requires explicit backup/migration before downgrade'; END IF; END $$;\n"
reverse_sql += "DROP TRIGGER research_budget_total ON catalog_researchbudget; DROP TRIGGER root_budget_total ON catalog_rootbudget; DROP TRIGGER receipt_budget_total ON catalog_usagereceipt; DROP FUNCTION catalog_budget_total_guard();\n"
reverse_sql += "DROP TRIGGER business_profile_guard ON catalog_profilebinding;\n"
reverse_sql += "CREATE OR REPLACE FUNCTION catalog_business_guard()" + BUSINESS_BASE
reverse_sql += "CREATE OR REPLACE FUNCTION catalog_artifact_guard()" + ARTIFACT_BASE
for table in ("usagereceipt","researchevent"):
    reverse_sql += f"DROP TRIGGER {table}_no_update ON catalog_{table};\n"
for table in ("researchbudget","rootbudget","reservation","usagereceipt","researchstate","profilebinding","researchevent"):
    reverse_sql += f"DROP TRIGGER {table}_no_delete ON catalog_{table};\n"
for table,trigger,function in [("researchbudget","research_budget_guard",None),("rootbudget","root_budget_guard","catalog_budget_guard"),("reservation","reservation_guard","catalog_reservation_guard"),("usagereceipt","usage_receipt_guard","catalog_usage_guard"),("researchstate","state_guard","catalog_state_guard"),("profilebinding","profile_binding_guard","catalog_profile_binding_guard"),("researchevent","research_event_guard","catalog_research_event_guard")]:
    reverse_sql += f"DROP TRIGGER {trigger} ON catalog_{table};\n"
    if function is not None:reverse_sql += f"DROP FUNCTION {function}();\n"
reverse_sql += """
ALTER TABLE catalog_artifact DROP CONSTRAINT artifact_research_fk;
ALTER TABLE catalog_researchbudget DROP CONSTRAINT budget_version_fk;
ALTER TABLE catalog_rootbudget DROP CONSTRAINT root_budget_run_fk,DROP CONSTRAINT root_budget_research_fk;
ALTER TABLE catalog_profilebinding DROP CONSTRAINT profile_run_fk,DROP CONSTRAINT profile_version_fk,DROP CONSTRAINT profile_dataset_fk,DROP CONSTRAINT profile_actor_fk,DROP CONSTRAINT profile_root_budget_fk;
ALTER TABLE catalog_researchstate DROP CONSTRAINT state_version_fk,DROP CONSTRAINT state_run_fk;
"""

VERSION_BUDGET_GUARD = """
CREATE FUNCTION catalog_version_budget_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM catalog_researchbudget WHERE research_version_id=NEW.id AND tenant_id=NEW.tenant_id AND document->'limit'=NEW.document->'budget')
 THEN RAISE EXCEPTION 'An atomic research account is required' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER version_budget_required AFTER INSERT ON catalog_researchversion DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION catalog_version_budget_guard();
"""
VERSION_BUDGET_REVERSE = "DROP TRIGGER version_budget_required ON catalog_researchversion; DROP FUNCTION catalog_version_budget_guard();"


class Migration(migrations.Migration):
    dependencies = [("catalog","0009_artifact_research_version_researchbudget_and_more"),("runtime","0005_profile_roots")]
    operations = [migrations.RunSQL(forward_sql,reverse_sql),migrations.RunPython(backfill,migrations.RunPython.noop),migrations.RunSQL(VERSION_BUDGET_GUARD,VERSION_BUDGET_REVERSE)]
