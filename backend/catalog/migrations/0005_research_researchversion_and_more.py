import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0004_ingest_guards'),
    ]

    operations = [
        migrations.CreateModel(
            name='Research',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.TextField()),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('provenance_id', models.UUIDField()),
            ],
        ),
        migrations.CreateModel(
            name='ResearchVersion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('document', models.JSONField()),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('provenance_id', models.UUIDField()),
            ],
        ),
        migrations.AddConstraint(
            model_name='datasetversion',
            constraint=models.UniqueConstraint(fields=('id', 'tenant'), name='version_tenant_identity'),
        ),
        migrations.AddField(
            model_name='research',
            name='owner',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.account'),
        ),
        migrations.AddField(
            model_name='research',
            name='tenant',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.tenant'),
        ),
        migrations.AddField(
            model_name='researchversion',
            name='dataset_version',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.datasetversion'),
        ),
        migrations.AddField(
            model_name='researchversion',
            name='research',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.research'),
        ),
        migrations.AddField(
            model_name='researchversion',
            name='tenant',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.tenant'),
        ),
        migrations.AddConstraint(
            model_name='research',
            constraint=models.UniqueConstraint(fields=('id', 'tenant'), name='research_tenant_identity'),
        ),
        migrations.AddIndex(
            model_name='researchversion',
            index=models.Index(fields=['research', '-created_at', '-id'], name='research_version_page'),
        ),
        migrations.AddConstraint(
            model_name='researchversion',
            constraint=models.UniqueConstraint(fields=('id', 'tenant'), name='research_version_tenant_identity'),
        ),
    ]
