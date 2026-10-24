"""讓研究事件守衛認得 SubmissionFrozen。

0010 的事件守衛要求每筆 RESEARCH 事件的 `payload.status` 等於當前 ResearchState.status，因為當時
只有 `ResearchVersionStateChanged` 一種研究事件。派送觸發的凍結必須在狀態維持 READY 時寫入
`SubmissionFrozen`，而 event-v2 schema 對其 payload 是 `additionalProperties:false`（只允許
submission_id 與 snapshot_hash），因此不可能帶 status。這裡把守衛改成逐事件型別判定：
`ResearchVersionStateChanged` 仍比對狀態，`SubmissionFrozen` 改為要求同一交易已存在同租戶、
同版本、同 id 的 FrozenSubmission；其餘事件維持原本的狀態比對。"""
from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION catalog_research_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'event_id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'sequence' IS DISTINCT FROM NEW.sequence::text
 OR NEW.document->>'stream_scope' IS DISTINCT FROM 'RESEARCH' OR NEW.document->>'stream_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NEW.document->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NOT EXISTS(SELECT 1 FROM catalog_researchstate s WHERE s.research_version_id=NEW.research_version_id AND s.tenant_id::text=NEW.document->>'tenant_id'
  AND s.revision=NEW.sequence
  AND CASE NEW.document->>'event_type'
   WHEN 'SubmissionFrozen' THEN EXISTS(SELECT 1 FROM catalog_frozensubmission f WHERE f.id=(NEW.document->'payload'->>'submission_id')::uuid
    AND f.research_version_id=NEW.research_version_id AND f.tenant_id::text=NEW.document->>'tenant_id')
   ELSE s.status=NEW.document->'payload'->>'status' END)
THEN RAISE EXCEPTION 'Research event mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

REVERSE = """
CREATE OR REPLACE FUNCTION catalog_research_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'event_id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'sequence' IS DISTINCT FROM NEW.sequence::text
 OR NEW.document->>'stream_scope' IS DISTINCT FROM 'RESEARCH' OR NEW.document->>'stream_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NEW.document->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NOT EXISTS(SELECT 1 FROM catalog_researchstate s WHERE s.research_version_id=NEW.research_version_id AND s.tenant_id::text=NEW.document->>'tenant_id'
  AND s.revision=NEW.sequence AND s.status=NEW.document->'payload'->>'status')
THEN RAISE EXCEPTION 'Research event mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0024_validate_business_guard")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
