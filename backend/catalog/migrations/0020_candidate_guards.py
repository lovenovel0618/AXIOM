"""候選、擬合與凍結的原生防線：同租戶複合外鍵、身分同步與不可改刪。

Candidate／FitRun／FrozenCandidate／ObservationSplit／RepresentationSpec 只允許 INSERT；
document 的 kind／id／tenant_id 與外鍵欄位必須與資料列同步。ObservationSplit 的文件沒有
tenant_id 與 schema_version，且 kind 是切分種類（IID_ROWS／GROUPED_ROWS／TIME_ORDERED／EXPLICIT），
因此只比對 id／dataset_version_id／row_ids_hash 與 kind 值域。最小權威 SEARCH／FIT run 沒有 ingest
綁定，business guard 對其早退，仍受 runtime run guard 與本檔複合外鍵保護。

business guard 同時掛在 runtime_runtimerun、catalog_ingestbinding 與 catalog_profilebinding 上，後兩者沒有
document 欄位；PL/pgSQL 會解析記錄欄位而非短路，因此型別判斷讀取靜態型別化的 r.document，而非 NEW.document。"""
from importlib import import_module
from django.db import migrations

PROFILE = import_module("catalog.migrations.0010_profile_guards")
BUSINESS_CURRENT = PROFILE.forward_sql.split("CREATE OR REPLACE FUNCTION catalog_business_guard()",1)[1].split("CREATE CONSTRAINT TRIGGER business_profile_guard",1)[0]
EARLY = " IF r.control_only THEN RETURN NULL; END IF;\n IF TG_TABLE_NAME='runtime_runtimerun' AND r.document->>'type' IN ('SEARCH','FIT') THEN RETURN NULL; END IF;"
BUSINESS_NEW = BUSINESS_CURRENT.replace(" IF r.control_only THEN RETURN NULL; END IF;", EARLY)

forward_sql = """
ALTER TABLE catalog_candidate ADD CONSTRAINT candidate_run_fk FOREIGN KEY(search_run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_candidate ADD CONSTRAINT candidate_equation_fk FOREIGN KEY(equation_version_id,tenant_id) REFERENCES catalog_equationversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_observationsplit ADD CONSTRAINT split_version_fk FOREIGN KEY(dataset_version_id,tenant_id) REFERENCES catalog_datasetversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_representationspec ADD CONSTRAINT representation_version_fk FOREIGN KEY(research_version_id,tenant_id) REFERENCES catalog_researchversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_representationspec ADD CONSTRAINT representation_dataset_fk FOREIGN KEY(dataset_version_id,tenant_id) REFERENCES catalog_datasetversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_representationspec ADD CONSTRAINT representation_split_fk FOREIGN KEY(observation_split_id,tenant_id) REFERENCES catalog_observationsplit(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_fitrun ADD CONSTRAINT fit_run_run_fk FOREIGN KEY(run_id,tenant_id) REFERENCES runtime_runtimerun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_fitrun ADD CONSTRAINT fit_run_equation_fk FOREIGN KEY(equation_version_id,tenant_id) REFERENCES catalog_equationversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_fitrun ADD CONSTRAINT fit_run_version_fk FOREIGN KEY(dataset_version_id,tenant_id) REFERENCES catalog_datasetversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_fitrun ADD CONSTRAINT fit_run_split_fk FOREIGN KEY(observation_split_id,tenant_id) REFERENCES catalog_observationsplit(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_fitrun ADD CONSTRAINT fit_run_representation_fk FOREIGN KEY(representation_artifact_id,tenant_id) REFERENCES catalog_representationspec(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_frozencandidate ADD CONSTRAINT frozen_candidate_fk FOREIGN KEY(candidate_id,tenant_id) REFERENCES catalog_candidate(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_frozencandidate ADD CONSTRAINT frozen_fit_run_fk FOREIGN KEY(fit_run_id,tenant_id) REFERENCES catalog_fitrun(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_frozencandidate ADD CONSTRAINT frozen_equation_fk FOREIGN KEY(equation_version_id,tenant_id) REFERENCES catalog_equationversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_frozencandidate ADD CONSTRAINT frozen_version_fk FOREIGN KEY(dataset_version_id,tenant_id) REFERENCES catalog_datasetversion(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_frozencandidate ADD CONSTRAINT frozen_split_fk FOREIGN KEY(observation_split_id,tenant_id) REFERENCES catalog_observationsplit(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE catalog_frozencandidate ADD CONSTRAINT frozen_representation_fk FOREIGN KEY(representation_artifact_id,tenant_id) REFERENCES catalog_representationspec(id,tenant_id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION catalog_candidate_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'Candidate' OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NEW.document->>'search_run_id' IS DISTINCT FROM NEW.search_run_id::text
 OR NEW.document->>'equation_version_id' IS DISTINCT FROM NEW.equation_version_id::text
 OR NEW.document->>'development_rank' IS DISTINCT FROM NEW.development_rank::text
 THEN RAISE EXCEPTION 'Candidate identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER candidate_guard BEFORE INSERT ON catalog_candidate FOR EACH ROW EXECUTE FUNCTION catalog_candidate_guard();
CREATE TRIGGER candidate_immutable BEFORE UPDATE OR DELETE ON catalog_candidate FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_observation_split_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS NULL OR NEW.document->>'kind' NOT IN ('IID_ROWS','GROUPED_ROWS','TIME_ORDERED','EXPLICIT')
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text
 OR NEW.document->>'dataset_version_id' IS DISTINCT FROM NEW.dataset_version_id::text
 OR NEW.document->>'row_ids_hash' IS DISTINCT FROM NEW.row_ids_hash
 THEN RAISE EXCEPTION 'Observation split identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER observation_split_guard BEFORE INSERT ON catalog_observationsplit FOR EACH ROW EXECUTE FUNCTION catalog_observation_split_guard();
CREATE TRIGGER observation_split_immutable BEFORE UPDATE OR DELETE ON catalog_observationsplit FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_representation_spec_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'RepresentationSpec' OR NEW.document->>'schema_version' IS DISTINCT FROM '1.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NEW.document->>'research_version_id' IS DISTINCT FROM NEW.research_version_id::text
 OR NEW.document->>'dataset_version_id' IS DISTINCT FROM NEW.dataset_version_id::text
 OR NEW.document->>'observation_split_id' IS DISTINCT FROM NEW.observation_split_id::text
 OR NEW.document->>'fit_rows_hash' IS DISTINCT FROM NEW.fit_rows_hash
 THEN RAISE EXCEPTION 'Representation spec identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER representation_spec_guard BEFORE INSERT ON catalog_representationspec FOR EACH ROW EXECUTE FUNCTION catalog_representation_spec_guard();
CREATE TRIGGER representation_spec_immutable BEFORE UPDATE OR DELETE ON catalog_representationspec FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_fit_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'FitRun' OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NEW.document->>'run_id' IS DISTINCT FROM NEW.run_id::text
 OR NEW.document->>'equation_version_id' IS DISTINCT FROM NEW.equation_version_id::text
 OR NEW.document->>'dataset_version_id' IS DISTINCT FROM NEW.dataset_version_id::text
 OR NEW.document->>'observation_split_id' IS DISTINCT FROM NEW.observation_split_id::text
 OR NEW.document->>'representation_artifact_id' IS DISTINCT FROM NEW.representation_artifact_id::text
 OR NEW.document->>'fit_rows_hash' IS DISTINCT FROM NEW.fit_rows_hash
 THEN RAISE EXCEPTION 'Fit run identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fit_run_guard BEFORE INSERT ON catalog_fitrun FOR EACH ROW EXECUTE FUNCTION catalog_fit_run_guard();
CREATE TRIGGER fit_run_immutable BEFORE UPDATE OR DELETE ON catalog_fitrun FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
CREATE FUNCTION catalog_frozen_candidate_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.document->>'kind' IS DISTINCT FROM 'FrozenCandidate' OR NEW.document->>'schema_version' IS DISTINCT FROM '2.0'
 OR NEW.document->>'id' IS DISTINCT FROM NEW.id::text OR NEW.document->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text
 OR (NEW.document->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at
 OR NEW.document->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
 OR NEW.document->>'equation_version_id' IS DISTINCT FROM NEW.equation_version_id::text
 OR NEW.document->>'fit_run_id' IS DISTINCT FROM NEW.fit_run_id::text
 OR NEW.document->>'dataset_version_id' IS DISTINCT FROM NEW.dataset_version_id::text
 OR NEW.document->>'observation_split_id' IS DISTINCT FROM NEW.observation_split_id::text
 OR NEW.document->>'representation_artifact_id' IS DISTINCT FROM NEW.representation_artifact_id::text
 OR NEW.document->>'dsl_identity_hash' IS DISTINCT FROM NEW.dsl_identity_hash
 OR NEW.document->>'parameter_binding_hash' IS DISTINCT FROM NEW.parameter_binding_hash
 OR NEW.document->>'development_rank' IS DISTINCT FROM NEW.development_rank::text
 THEN RAISE EXCEPTION 'Frozen candidate identity mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER frozen_candidate_guard BEFORE INSERT ON catalog_frozencandidate FOR EACH ROW EXECUTE FUNCTION catalog_frozen_candidate_guard();
CREATE TRIGGER frozen_candidate_immutable BEFORE UPDATE OR DELETE ON catalog_frozencandidate FOR EACH ROW EXECUTE FUNCTION catalog_immutable();
"""
forward_sql += "CREATE OR REPLACE FUNCTION catalog_business_guard()" + BUSINESS_NEW

reverse_sql = """
DROP TRIGGER frozen_candidate_immutable ON catalog_frozencandidate;
DROP TRIGGER frozen_candidate_guard ON catalog_frozencandidate;
DROP FUNCTION catalog_frozen_candidate_guard();
DROP TRIGGER fit_run_immutable ON catalog_fitrun;
DROP TRIGGER fit_run_guard ON catalog_fitrun;
DROP FUNCTION catalog_fit_run_guard();
DROP TRIGGER representation_spec_immutable ON catalog_representationspec;
DROP TRIGGER representation_spec_guard ON catalog_representationspec;
DROP FUNCTION catalog_representation_spec_guard();
DROP TRIGGER observation_split_immutable ON catalog_observationsplit;
DROP TRIGGER observation_split_guard ON catalog_observationsplit;
DROP FUNCTION catalog_observation_split_guard();
DROP TRIGGER candidate_immutable ON catalog_candidate;
DROP TRIGGER candidate_guard ON catalog_candidate;
DROP FUNCTION catalog_candidate_guard();
"""
reverse_sql += "CREATE OR REPLACE FUNCTION catalog_business_guard()" + BUSINESS_CURRENT
reverse_sql += """
ALTER TABLE catalog_frozencandidate DROP CONSTRAINT frozen_candidate_fk, DROP CONSTRAINT frozen_fit_run_fk, DROP CONSTRAINT frozen_equation_fk, DROP CONSTRAINT frozen_version_fk, DROP CONSTRAINT frozen_split_fk, DROP CONSTRAINT frozen_representation_fk;
ALTER TABLE catalog_fitrun DROP CONSTRAINT fit_run_run_fk, DROP CONSTRAINT fit_run_equation_fk, DROP CONSTRAINT fit_run_version_fk, DROP CONSTRAINT fit_run_split_fk, DROP CONSTRAINT fit_run_representation_fk;
ALTER TABLE catalog_representationspec DROP CONSTRAINT representation_version_fk, DROP CONSTRAINT representation_dataset_fk, DROP CONSTRAINT representation_split_fk;
ALTER TABLE catalog_observationsplit DROP CONSTRAINT split_version_fk;
ALTER TABLE catalog_candidate DROP CONSTRAINT candidate_run_fk, DROP CONSTRAINT candidate_equation_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0019_candidate_fit_and_freeze"), ("runtime", "0006_search_roots")]
    operations = [migrations.RunSQL(forward_sql, reverse_sql)]
