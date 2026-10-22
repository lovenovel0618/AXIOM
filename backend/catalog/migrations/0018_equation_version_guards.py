"""公式版本的原生防線：文件與欄位必須同步，寫入後不可改、不可刪。

EquationVersion 是候選公式的權威身分，因此只允許 INSERT；UPDATE 與 DELETE 一律拒絕，
同一 (tenant, identity_hash, dsl_version) 不能出現兩份真相。"""
from django.db import migrations

FORWARD = """
CREATE FUNCTION catalog_equation_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'EquationVersion' OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NEW.document->>'identity_hash' IS DISTINCT FROM NEW.identity_hash
 OR NEW.document->'dsl'->>'dsl_version' IS DISTINCT FROM NEW.dsl_version
 OR NEW.identity_hash !~ '^[0-9a-f]{64}$'
 THEN RAISE EXCEPTION 'Equation version identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER equation_version_guard BEFORE INSERT ON catalog_equationversion FOR EACH ROW EXECUTE FUNCTION catalog_equation_version_guard();
CREATE TRIGGER equation_version_immutable BEFORE UPDATE OR DELETE ON catalog_equationversion FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
"""
REVERSE = """
DROP TRIGGER equation_version_immutable ON catalog_equationversion;
DROP TRIGGER equation_version_guard ON catalog_equationversion;
DROP FUNCTION catalog_equation_version_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0017_equationversion")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
