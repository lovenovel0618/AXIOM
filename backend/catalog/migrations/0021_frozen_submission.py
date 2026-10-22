from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0020_candidate_guards"),
    ]

    operations = [
        migrations.CreateModel(
            name="FrozenSubmission",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sealed_test_id", models.UUIDField()),
                ("metric_version", models.CharField(default="2.0", max_length=8)),
                ("snapshot_hash", models.CharField(max_length=64)),
                ("status", models.CharField(default="FROZEN", max_length=12)),
                ("document", models.JSONField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("research_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalog.researchversion")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalog.tenant")),
                ("verification_plan_artifact", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="catalog.artifact")),
            ],
        ),
        migrations.AddIndex(
            model_name="frozensubmission",
            index=models.Index(fields=["research_version", "created_at", "id"], name="frozen_submission_page"),
        ),
        migrations.AddConstraint(
            model_name="frozensubmission",
            constraint=models.UniqueConstraint(fields=("id", "tenant"), name="frozen_submission_tenant_identity"),
        ),
        migrations.AddConstraint(
            model_name="frozensubmission",
            constraint=models.UniqueConstraint(fields=("research_version", "snapshot_hash"), name="frozen_submission_snapshot_unique"),
        ),
        migrations.AddConstraint(
            model_name="frozensubmission",
            constraint=models.CheckConstraint(condition=models.Q(("metric_version", "2.0")), name="frozen_submission_metric_version"),
        ),
        migrations.AddConstraint(
            model_name="frozensubmission",
            constraint=models.CheckConstraint(condition=models.Q(("snapshot_hash__regex", "^[0-9a-f]{64}$")), name="frozen_submission_snapshot_format"),
        ),
        migrations.AddConstraint(
            model_name="frozensubmission",
            constraint=models.CheckConstraint(condition=models.Q(("status__in", ["FROZEN", "EVALUATING", "EVALUATED", "FAILED"])), name="frozen_submission_status"),
        ),
    ]
