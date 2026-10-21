"""READY 的原生防線：品質報告與研究狀態都必須有同租戶／同版本的不透明封存登記。

0010 的 QualityReport 檢查只允許「永遠 BLOCKED」，封存啟用後不再成立。
這裡改為兩段式：BLOCKED 需附非空 remaining，READY 需 quality=PASS、remaining 為空，
且同交易已有可用的原生封存登記；研究狀態的 READY 也必須指向同一登記。"""
from importlib import import_module
from django.db import migrations

PREVIOUS = import_module("catalog.migrations.0010_profile_guards")
ARTIFACT_BASE = PREVIOUS.ARTIFACT_BASE
STATE_BASE = PREVIOUS.forward_sql.split("CREATE FUNCTION catalog_state_guard()",1)[1].split("CREATE TRIGGER state_guard",1)[0]

QUALITY_EXTRA = PREVIOUS.ARTIFACT_EXTRA.replace(""" OR NEW.content->'remaining' IS DISTINCT FROM '["SEALED_TEST_NOT_REGISTERED"]'::jsonb OR NEW.content->'precision_bits' IS DISTINCT FROM '53'::jsonb
  OR NEW.content->>'readiness' IS DISTINCT FROM 'BLOCKED' OR NEW.content->>'quality' IS NULL OR NEW.content->>'quality' NOT IN ('PASS','BLOCKED')
  OR (NEW.content->>'quality'='BLOCKED' AND NEW.content->'fit_summary' IS DISTINCT FROM 'null'::jsonb)
  THEN RAISE EXCEPTION 'Unsafe quality report' USING ERRCODE='23514'; END IF;""",""" OR NEW.content->>'run_id' IS NULL OR NEW.content->>'run_id' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  OR NEW.content->'precision_bits' IS DISTINCT FROM '53'::jsonb
  OR NEW.content->>'readiness' IS NULL OR NEW.content->>'readiness' NOT IN ('READY','BLOCKED')
  OR NEW.content->>'quality' IS NULL OR NEW.content->>'quality' NOT IN ('PASS','BLOCKED')
  OR (NEW.content->>'quality'='BLOCKED' AND NEW.content->'fit_summary' IS DISTINCT FROM 'null'::jsonb)
  THEN RAISE EXCEPTION 'Unsafe quality report' USING ERRCODE='23514'; END IF;
  IF NEW.content->>'readiness'='READY' THEN
   IF NEW.content->>'quality'<>'PASS' OR NEW.content->'remaining' IS DISTINCT FROM '[]'::jsonb
   OR NOT EXISTS(SELECT 1 FROM catalog_sealregistration s WHERE s.tenant_id=NEW.tenant_id AND s.research_version_id=NEW.research_version_id
    AND s.run_id=(NEW.content->>'run_id')::uuid AND s.available)
   THEN RAISE EXCEPTION 'Quality report READY requires a native seal registration' USING ERRCODE='23514'; END IF;
  ELSE
   IF jsonb_typeof(NEW.content->'remaining') IS DISTINCT FROM 'array'
   THEN RAISE EXCEPTION 'Unsafe quality report' USING ERRCODE='23514';
   ELSIF NEW.content->'remaining'='[]'::jsonb
   THEN RAISE EXCEPTION 'Unsafe quality report' USING ERRCODE='23514';
   END IF;
  END IF;""")

SEAL_CHECK = """
 IF NEW.status='READY' AND NOT EXISTS(SELECT 1 FROM catalog_sealregistration s WHERE s.id=NEW.seal_id
  AND s.tenant_id=NEW.tenant_id AND s.research_version_id=NEW.research_version_id AND s.available)
 THEN RAISE EXCEPTION 'Research READY requires a native seal registration' USING ERRCODE='23514'; END IF;
"""

forward_sql = "CREATE OR REPLACE FUNCTION catalog_artifact_guard()" + ARTIFACT_BASE.replace("'StructureAssessment','ImportDiagnostic'","'StructureAssessment','ImportDiagnostic','QualityReport'").replace(" RETURN NEW;",QUALITY_EXTRA+" RETURN NEW;")
forward_sql += "CREATE OR REPLACE FUNCTION catalog_state_guard()" + STATE_BASE.replace(" RETURN NEW;",SEAL_CHECK+" RETURN NEW;")

reverse_sql = "CREATE OR REPLACE FUNCTION catalog_artifact_guard()" + ARTIFACT_BASE.replace("'StructureAssessment','ImportDiagnostic'","'StructureAssessment','ImportDiagnostic','QualityReport'").replace(" RETURN NEW;",PREVIOUS.ARTIFACT_EXTRA+" RETURN NEW;")
reverse_sql += "CREATE OR REPLACE FUNCTION catalog_state_guard()" + STATE_BASE


class Migration(migrations.Migration):
    dependencies = [("catalog","0011_sealregistration_and_more")]
    operations = [migrations.RunSQL(forward_sql,reverse_sql)]
