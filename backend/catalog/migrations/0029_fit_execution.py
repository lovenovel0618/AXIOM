"""FIT 真實快照須與既有擬合、候選、成功 SEARCH 及兩層帳本同交易綁定。"""
from importlib import import_module
from django.db import migrations

PREVIOUS = import_module("catalog.migrations.0028_search_catalog_scope")
BUDGET = import_module("catalog.migrations.0026_search_execution").BUDGET_SQL
FIT = """
 IF r.document->>'type'='FIT' AND r.document->'is_root'='true'::jsonb
 AND EXISTS(SELECT 1 FROM runtime_inputsnapshot WHERE run_id=r.id) THEN
  IF NOT EXISTS(SELECT 1 FROM catalog_fitrun f
   JOIN catalog_representationspec p ON p.id=f.representation_artifact_id
   JOIN catalog_researchversion v ON v.id=p.research_version_id
   JOIN catalog_rootbudget fit_budget ON fit_budget.run_id=r.id
   JOIN runtime_inputsnapshot s ON s.run_id=r.id
   JOIN catalog_candidate c ON c.id=(s.task_input->'payload'->>'candidate_id')::uuid
   JOIN runtime_runtimerun search ON search.id=c.search_run_id
   JOIN runtime_inputsnapshot search_input ON search_input.run_id=search.id
   JOIN catalog_artifact i ON i.id=(r.document->>'input_artifact_id')::uuid
   JOIN catalog_artifact projection ON projection.id=(s.task_input->'payload'->>'fit_projection_artifact_id')::uuid
   WHERE f.run_id=r.id AND f.tenant_id=r.tenant_id AND v.tenant_id=r.tenant_id
   AND c.tenant_id=r.tenant_id AND c.equation_version_id=f.equation_version_id
   AND c.document->'fit_run_ids' @> jsonb_build_array(f.id::text)
   AND search.document->>'status'='SUCCEEDED' AND search.document->>'type'='SEARCH'
   AND search.document->>'research_version_id'=v.id::text
   AND r.document->>'research_version_id'=v.id::text
   AND r.document->>'equation_version_id'=f.equation_version_id::text
   AND r.document->>'budget_account_id'=fit_budget.id::text
   AND r.document->>'research_budget_account_id'=fit_budget.research_budget_id::text
   AND fit_budget.research_budget_id=(SELECT id FROM catalog_researchbudget WHERE research_version_id=v.id)
   AND s.task_input->'payload'->>'equation_version_id'=f.equation_version_id::text
   AND s.task_input->'payload'->>'fit_rows_hash'=f.fit_rows_hash
   AND s.task_input->'payload'->'fit_row_ids'=f.document->'fit_row_ids'
   AND s.task_input->'payload'->>'split_role'='FIT'
   AND i.tenant_id=r.tenant_id AND i.research_version_id=v.id AND i.content=s.task_input
   AND i.document->>'access_class'='SEALED_DETAIL'
   AND projection.tenant_id=r.tenant_id AND projection.research_version_id=v.id
   AND projection.content->>'kind'='FitProjectionSource'
   AND projection.content->>'fit_run_id'=f.id::text
   AND projection.content->'parameters'=f.document->'parameters'
   AND r.document->'budget_usage'=fit_budget.document->'usage'
   AND r.document->'budget_reservations'=fit_budget.document->'reservations')
  THEN RAISE EXCEPTION 'Atomic FIT authority required' USING ERRCODE='23514'; END IF;
 END IF;
"""
FORWARD = PREVIOUS.FORWARD.replace(" IF r.control_only THEN RETURN NULL; END IF;", " IF r.control_only THEN RETURN NULL; END IF;" + FIT)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0028_search_catalog_scope")]
    operations = [migrations.RunSQL(BUDGET.replace("('PROFILE','SEARCH')", "('PROFILE','SEARCH','FIT')"), BUDGET),
        migrations.RunSQL(FORWARD, PREVIOUS.FORWARD)]
