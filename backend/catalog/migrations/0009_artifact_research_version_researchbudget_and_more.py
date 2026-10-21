import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0008_inspection_guards'),
        ('runtime', '0004_remove_runtimerun_runtime_control_only'),
    ]

    operations = [
        migrations.AddField(
            model_name='artifact',
            name='research_version',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='catalog.researchversion'),
        ),
        migrations.CreateModel(
            name='ResearchBudget',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('document', models.JSONField()),
                ('research_version', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to='catalog.researchversion')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.tenant')),
            ],
        ),
        migrations.CreateModel(
            name='ResearchEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sequence', models.PositiveBigIntegerField()),
                ('document', models.JSONField()),
                ('research_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.researchversion')),
            ],
        ),
        migrations.CreateModel(
            name='ResearchState',
            fields=[
                ('research_version', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, serialize=False, to='catalog.researchversion')),
                ('revision', models.PositiveBigIntegerField(default=0)),
                ('status', models.CharField(default='DRAFT', max_length=10)),
                ('active_run', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='runtime.runtimerun')),
                ('quality', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='quality_states', to='catalog.artifact')),
                ('structure', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='structure_states', to='catalog.artifact')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.tenant')),
            ],
        ),
        migrations.CreateModel(
            name='RootBudget',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('document', models.JSONField()),
                ('research_budget', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.researchbudget')),
                ('run', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to='runtime.runtimerun')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.tenant')),
            ],
        ),
        migrations.CreateModel(
            name='Reservation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('requested', models.JSONField()),
                ('held', models.JSONField()),
                ('state', models.CharField(default='HELD', max_length=9)),
                ('root', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to='catalog.rootbudget')),
            ],
        ),
        migrations.CreateModel(
            name='ProfileBinding',
            fields=[
                ('run', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, serialize=False, to='runtime.runtimerun')),
                ('error_code', models.CharField(max_length=40, null=True)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.account')),
                ('dataset', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.dataset')),
                ('research_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.researchversion')),
                ('result', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='profile_results', to='catalog.artifact')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.tenant')),
                ('root_budget', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to='catalog.rootbudget')),
            ],
        ),
        migrations.CreateModel(
            name='UsageReceipt',
            fields=[
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('sequence', models.PositiveIntegerField()),
                ('document', models.JSONField()),
                ('content_hash', models.CharField(max_length=64)),
                ('attempt', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='runtime.runtimeattempt')),
                ('root', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.rootbudget')),
            ],
        ),
        migrations.AddConstraint(
            model_name='researchbudget',
            constraint=models.UniqueConstraint(fields=('id', 'tenant'), name='research_budget_tenant_identity'),
        ),
        migrations.AddConstraint(
            model_name='researchevent',
            constraint=models.UniqueConstraint(fields=('research_version', 'sequence'), name='research_event_sequence_unique'),
        ),
        migrations.AddConstraint(
            model_name='researchstate',
            constraint=models.CheckConstraint(condition=models.Q(('status__in', ['DRAFT', 'VALIDATING'])), name='research_state_local_status'),
        ),
        migrations.AddConstraint(
            model_name='rootbudget',
            constraint=models.UniqueConstraint(fields=('id', 'tenant'), name='root_budget_tenant_identity'),
        ),
        migrations.AddConstraint(
            model_name='reservation',
            constraint=models.CheckConstraint(condition=models.Q(('state__in', ['HELD', 'UNCERTAIN', 'RELEASED'])), name='reservation_state_valid'),
        ),
        migrations.AddConstraint(
            model_name='usagereceipt',
            constraint=models.UniqueConstraint(fields=('attempt', 'sequence'), name='usage_attempt_sequence_unique'),
        ),
    ]
