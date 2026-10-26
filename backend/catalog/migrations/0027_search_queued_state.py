"""依 AX-04 保存 READY→QUEUED→RUNNING；兩個活躍狀態都必須綁有快照的 SEARCH root。"""
from importlib import import_module
from django.db import migrations, models

PREVIOUS = import_module("catalog.migrations.0026_search_execution")
STATE_BASE = "CREATE OR REPLACE FUNCTION catalog_state_guard()" + PREVIOUS.BASE.replace(PREVIOUS.OLD, PREVIOUS.NEW)
STATE_NEW = STATE_BASE.replace("('VALIDATING','RUNNING')", "('VALIDATING','QUEUED','RUNNING')").replace("NEW.status='RUNNING' AND", "NEW.status IN ('QUEUED','RUNNING') AND")
BUSINESS_NEW = PREVIOUS.BUSINESS_SQL.replace("z.status='RUNNING'", "z.status IN ('QUEUED','RUNNING')")


class Migration(migrations.Migration):
    dependencies = [("catalog", "0026_search_execution")]
    operations = [
        migrations.RemoveConstraint(model_name="researchstate", name="research_state_local_status"),
        migrations.AddConstraint(model_name="researchstate", constraint=models.CheckConstraint(condition=models.Q(status__in=["DRAFT", "VALIDATING", "READY", "QUEUED", "RUNNING", "FAILED", "CANCELLED"]), name="research_state_local_status")),
        migrations.RunSQL(STATE_NEW, STATE_BASE),
        migrations.RunSQL(BUSINESS_NEW, PREVIOUS.BUSINESS_SQL)]
