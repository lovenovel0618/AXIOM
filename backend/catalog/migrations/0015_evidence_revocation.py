"""撤銷登記表與原生防線：同租戶複合 FK、身分不可改、狀態之外不可變、禁止刪除。

撤銷在同交易立即排除權威有效性，之後由撤銷工作推進狀態；撤銷紀錄是稽核證據，
因此不可刪除，且只有 status 允許前進，其餘欄位與文件內容一律凍結。"""
import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models

FORWARD = """
ALTER TABLE catalog_evidencerevocation ADD CONSTRAINT evidence_revocation_bundle_fk FOREIGN KEY(evidence_bundle_id,tenant_id) REFERENCES catalog_evidencebundle(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_evidencerevocation ADD CONSTRAINT evidence_revocation_run_fk FOREIGN KEY(run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_evidencerevocation ADD CONSTRAINT evidence_revocation_actor_fk FOREIGN KEY(actor_id,tenant_id) REFERENCES catalog_account(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION catalog_evidence_revocation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
 OR NEW.evidence_bundle_id IS DISTINCT FROM OLD.evidence_bundle_id OR NEW.run_id IS DISTINCT FROM OLD.run_id
 OR NEW.actor_id IS DISTINCT FROM OLD.actor_id OR NEW.counterexample_artifact_id IS DISTINCT FROM OLD.counterexample_artifact_id
 OR NEW.created_at IS DISTINCT FROM OLD.created_at OR (NEW.document - 'status') IS DISTINCT FROM (OLD.document - 'status'))
 THEN RAISE EXCEPTION 'Immutable evidence revocation identity' USING ERRCODE='23514'; END IF;
 IF NEW.document->>'kind' IS DISTINCT FROM 'EvidenceRevocation' OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR NEW.document->>'evidence_bundle_id' IS DISTINCT FROM NEW.evidence_bundle_id::text
 OR NEW.document->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
 OR NEW.document->>'status' IS DISTINCT FROM NEW.status
 OR (NEW.document->>'counterexample_artifact_id') IS DISTINCT FROM (NEW.counterexample_artifact_id::text)
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 THEN RAISE EXCEPTION 'Evidence revocation identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER evidence_revocation_guard BEFORE INSERT OR UPDATE ON catalog_evidencerevocation FOR EACH ROW EXECUTE FUNCTION catalog_evidence_revocation_guard();
CREATE TRIGGER evidence_revocation_no_delete BEFORE DELETE ON catalog_evidencerevocation FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
"""
REVERSE = """
DROP TRIGGER evidence_revocation_no_delete ON catalog_evidencerevocation;
DROP TRIGGER evidence_revocation_guard ON catalog_evidencerevocation;
DROP FUNCTION catalog_evidence_revocation_guard();
ALTER TABLE catalog_evidencerevocation DROP CONSTRAINT evidence_revocation_actor_fk, DROP CONSTRAINT evidence_revocation_run_fk, DROP CONSTRAINT evidence_revocation_bundle_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0014_evidence_bundle_guards"), ("runtime", "0006_revoke_roots"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="EvidenceRevocation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("counterexample_artifact_id", models.UUIDField(null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("status", models.CharField(default="REQUESTED", max_length=12)),
                ("document", models.JSONField()),
            ],
        ),
        migrations.AddField(model_name="evidencerevocation", name="actor", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalog.account")),
        migrations.AddField(model_name="evidencerevocation", name="evidence_bundle", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalog.evidencebundle")),
        migrations.AddField(model_name="evidencerevocation", name="run", field=models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="runtime.runtimerun")),
        migrations.AddField(model_name="evidencerevocation", name="tenant", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalog.tenant")),
        migrations.AddConstraint(model_name="evidencerevocation", constraint=models.UniqueConstraint(fields=("id", "tenant"), name="evidence_revocation_tenant_identity")),
        migrations.AddConstraint(model_name="evidencerevocation", constraint=models.CheckConstraint(condition=models.Q(status__in=["REQUESTED", "BLOCKED", "PROPAGATING", "COMPLETED", "FAILED"]), name="evidence_revocation_valid_status")),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
