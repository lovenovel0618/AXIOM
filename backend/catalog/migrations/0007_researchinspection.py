import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0006_research_guards'),
    ]

    operations = [
        migrations.CreateModel(
            name='ResearchInspection',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('request_hash', models.CharField(max_length=64)),
                ('configuration', models.JSONField()),
                ('document', models.JSONField()),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.account')),
                ('research_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.researchversion')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalog.tenant')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('research_version', 'request_hash'), name='research_inspection_request_unique')],
            },
        ),
    ]
