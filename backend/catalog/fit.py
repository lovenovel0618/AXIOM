"""成功 SEARCH 的固定 binding 重放：真實 FIT 快照、預留、隔離評分與 fenced 結果提交。"""
from datetime import timedelta
from fractions import Fraction
import json
import platform
from uuid import UUID, uuid4
from django.conf import settings
from django.db import DatabaseError, transaction
from catalog.artifacts import register
from catalog.budget import remaining, reserve, release_unstarted, report_usage, usage_report
from catalog.ingest import Meter
from catalog.ingest_manifest import environment
from catalog.inspection import configuration, current
from catalog.models import Account, Candidate, FitRun, Provenance, ResearchBudget, ResearchVersion, SearchAttemptStop
from catalog.profile_manifest import documents, MEMORY
from catalog.search import Scope
from catalog.storage import LocalVersionStore, StorageRejected
from catalog.validation import ApiError
from ingestion.limits import ImportLimits, ImportRejected
from ingestion.research_protocol import report_check
from ingestion.supervisor import inspect_research
from runtime.budget_types import integer, object_fields, read_limit, LIMIT_KEYS
from runtime.completion import confirm_business_stopped, finish
from runtime.control import check_submission, claim, recover
from runtime.contracts import canonical_bytes, identity_hash, validate
from runtime.models import InputSnapshot, RuntimeAttempt, RuntimeRun, ValidationRun
from runtime.records import ControlError, db_now, emit, lock_run, save_run, save_attempt, snapshot_for, state_event, task_input_hash, validate_bindings


def limits_for(version: ResearchVersion) -> ImportLimits:
    """FIT 限 Linux 與完整容量；4096 列及 30 秒是可逆開發上限，非正式 SLO。"""
    if not settings.FIT_ENABLED or platform.system() != "Linux":
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    try:
        limits = ImportLimits(**json.loads(settings.FIT_LIMITS_JSON))
    except (ValueError, TypeError) as error:
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503) from error
    if limits.max_rows > 4096 or limits.max_parse_seconds > 30 or version.dataset_version.document["row_count"] > limits.max_rows:
        raise ApiError("IMPORT_LIMIT_EXCEEDED", 413)
    return limits


def source_candidate(fit: FitRun) -> Candidate:
    """只認成功且有快照的 SEARCH 所產生的同版本候選；離線 fixture 保留離線語意。"""
    candidate = Candidate.objects.filter(tenant_id=fit.tenant_id, document__fit_run_ids__contains=[str(fit.id)],
        equation_version_id=fit.equation_version_id, search_run__document__status="SUCCEEDED",
        search_run__inputsnapshot__isnull=False,
        search_run__document__research_version_id=str(fit.representation_artifact.research_version_id)).first()
    if candidate is None:
        raise ApiError("FIT_REFERENCE_MISMATCH", 409)
    return candidate


def attach(tenant: UUID, identity: UUID) -> bool:
    """在既有 pristine FIT 根附加真實輸入；鎖 root 後才鎖帳本，冪等與准入共用交易。"""
    with transaction.atomic():
        row = lock_run(tenant, identity)
        if row.document["type"] != "FIT" or not row.document["is_root"] or row.control_only:
            return False
        if InputSnapshot.objects.filter(run=row).exists():
            return True
        if row.document["status"] != "QUEUED" or row.document["revision"] != 0:
            return False
        fit = FitRun.objects.select_related("representation_artifact", "equation_version").get(run=row, tenant_id=tenant)
        candidate = source_candidate(fit)
        version = ResearchVersion.objects.get(pk=fit.representation_artifact.research_version_id, tenant_id=tenant)
        limits = limits_for(version)
        actor, version, reference = current(version.research.owner_id, version.id, allow_validating=True)
        LocalVersionStore(settings.OBJECT_ROOT).verify(reference)
        if row.document["environment_digest"] != environment():
            raise ApiError("CHECKPOINT_INCOMPATIBLE", 409)
        account = ResearchBudget.objects.select_for_update().get(research_version=version, tenant_id=tenant)
        available = remaining(account, allow_closing=True)
        limit = read_limit({"cpu_seconds": limits.max_parse_seconds + 15, "wall_seconds": limits.max_parse_seconds + 30,
            "memory_bytes": MEMORY, "gpu_seconds": 0, "tokens": 0, "candidate_limit": 0})
        if any(available[key] < limit[key] for key in LIMIT_KEYS):
            raise ApiError("RESEARCH_BUDGET_EXHAUSTED", 429)
        record = row.document
        _record, task, execution, budget = documents(actor, version, account, limit, limits,
            str(record["input_artifact_id"]), str(record["provenance_id"]))
        projection_id = uuid4()
        source = Provenance.objects.get(pk=version.provenance_id, tenant_id=tenant)
        recipe = {"kind": "FitProjectionSource", "id": str(projection_id), "tenant_id": str(tenant),
            "research_version_id": str(version.id), "purpose": version.document["purpose"],
            "fit_run_id": str(fit.id), "candidate_id": str(candidate.id), "source_sha256": reference.sha256,
            "source_object_version": str(reference.version), "fit_rows_hash": fit.fit_rows_hash,
            "parameters": fit.document["parameters"], "equation_hash": fit.equation_version.document["identity_hash"]}
        register(actor, Scope(version), projection_id, recipe, source, research_version=version)
        task.update(run_id=str(row.id), type="FIT", execution_manifest_id=record["execution_manifest_id"], payload={
            "candidate_id": str(candidate.id), "equation_version_id": str(fit.equation_version_id),
            "fit_projection_artifact_id": str(projection_id), "optimizer": fit.document["optimizer"], "seed": record["seed"],
            "split_role": "FIT", "fit_row_ids": fit.document["fit_row_ids"], "fit_rows_hash": fit.fit_rows_hash,
            "refit_policy_artifact_id": None, "representation_artifact_id": str(fit.representation_artifact_id)})
        execution.update(id=record["execution_manifest_id"], seed=record["seed"], input_hash=task_input_hash(task))
        plugin = execution["plugins"][0]
        plugin["config"].update(actor_id=str(actor.id), fit_run_id=str(fit.id), capacity_policy="local-fit-v1")
        plugin.update(plugin_id="local-bounded-fit", config_sha256=identity_hash(plugin["config"]))
        budget.update(id=record["budget_account_id"], root_run_id=str(row.id))
        validate_bindings(record, task, execution, budget)
        register(actor, Scope(version), UUID(record["input_artifact_id"]), task, source, research_version=version)
        InputSnapshot.objects.create(run=row, task_input=task, execution=execution, budget=budget, content_hash=identity_hash([task, execution, budget]))
        reserve(row, budget, allow_closing=True)
        # 未預留時等待 SEARCH 完成的時間不計入 FIT queue timeout。
        row.queue_deadline = db_now() + timedelta(seconds=60)
        row.available_at = db_now()
        emit(row, "RunQueued", {"status": "QUEUED", "attempt_id": None, "generation": 0}, db_now())
        save_run(row)
        return True


def recover_fit(tenant: UUID, identity: UUID) -> None:
    """回收佇列逾時與取消；失聯預留維持未知，不能把 lease 到期當停止證明。"""
    with transaction.atomic():
        row = lock_run(tenant, identity)
        if row.document["type"] != "FIT" or not InputSnapshot.objects.filter(run=row).exists():
            return
        recover(tenant, identity)
        row.refresh_from_db()
        if row.document["status"] == "CANCEL_REQUESTED" and not RuntimeAttempt.objects.filter(run=row).exclude(pk__in=SearchAttemptStop.objects.values("attempt_id")).exists():
            if row.document["active_attempt_id"] is not None:
                attempt = RuntimeAttempt.objects.select_for_update().get(pk=UUID(row.document["active_attempt_id"]))
                attempt.document.update(status="CANCELLED", finished_at=db_now().isoformat())
                save_attempt(attempt)
            row.document.update(status="CANCELLED", stop_reason="USER_CANCELLED", dispatch_stage="CLOSED")
            row.document["revision"] += 1
            state_event(row, "RunCancelled", db_now())
            save_run(row)
        if row.document["status"] in {"FAILED", "CANCELLED"}:
            release_unstarted(row)


def persist_results(actor: Account, version: ResearchVersion, fit: FitRun, row: RuntimeRun, report: dict[str, object]) -> None:
    """finish 回呼內寫入兩區不可變結果；描述性評分不宣稱 final 支持或形式化證明。"""
    payload = object_fields(snapshot_for(row).task_input["payload"])
    projection_id = UUID(str(payload["fit_projection_artifact_id"]))
    from catalog.models import Artifact
    projection = Artifact.objects.get(pk=projection_id, tenant_id=actor.tenant_id, research_version=version)
    source = Provenance.objects.get(pk=version.provenance_id, tenant_id=actor.tenant_id)
    scored = object_fields(report["model_evaluation"])
    for role in ("fit", "development"):
        value = object_fields(scored[role])
        identity, created = uuid4(), db_now()
        artifact = register(actor, Scope(version), identity, {"kind": "FitEvaluation", "id": str(identity), "tenant_id": str(actor.tenant_id),
            "research_version_id": str(version.id), "split_role": role.upper(),
            "fit_run_id": str(fit.id), "run_id": str(row.id), "metrics": value}, source, research_version=version)
        metrics = {name: None if value[name] is None else float(Fraction(str(value[name]))) for name in ("mae", "rmse")}
        document: dict[str, object] = {"kind": "ValidationRun", "id": str(identity), "tenant_id": str(actor.tenant_id),
            "schema_version": "2.0", "created_at": created.isoformat(), "run_id": str(row.id), "fit_run_id": str(fit.id),
            "metric_version": "2.0", "metrics": metrics, "valid_coverage": float(Fraction(str(value["coverage"]))),
            "empirical_level": "E1", "proof_level": "P0", "outcome_status": "INSUFFICIENT_EVIDENCE",
            "artifact_uri": artifact.document["artifact_uri"], "sha256": artifact.document["sha256"], "artifact_id": str(artifact.id),
            "metric_reasons": {name: "NO_EVALUABLE_ROWS" for name, score in metrics.items() if score is None},
            "observation_split_id": str(fit.observation_split_id), "split_role": role.upper(),
            "frozen_candidate_id": None, "submission_id": None, "evaluation_policy_hash": version.document["evaluation_policy_hash"],
            "selected_count": integer(value["selected_count"]), "valid_count": integer(value["valid_count"]),
            "failed_count": integer(value["failed_count"]), "verification_plan_artifact_id": str(projection_id),
            "verification_plan_hash": identity_hash(projection.content)}
        validate(document, "runtime-v2.schema.json", "ValidationRun")
        ValidationRun.objects.create(id=identity, tenant_id=actor.tenant_id, run_id=row.id,
            observation_split_id=fit.observation_split_id, split_role=role.upper(), document=document, created_at=created)


def fit_tick(tenant_id: str, run_id: str, generation: int) -> bool:
    """有快照才可領取；隔離程序退出後提交，任何過期 lease、取消或來源失效都拒收結果。"""
    if not settings.FIT_ENABLED:
        return False
    tenant, identity = UUID(tenant_id), UUID(run_id)
    row = RuntimeRun.objects.filter(pk=identity, tenant_id=tenant, control_only=False, document__type="FIT",
        document__is_root=True, inputsnapshot__isnull=False, rootbudget__isnull=False).first()
    if row is None:
        return False
    lease = claim(tenant, identity, generation, "fit:" + str(uuid4()))
    if lease is None:
        recover_fit(tenant, identity)
        return False
    meter = Meter()
    try:
        fit = FitRun.objects.select_related("equation_version", "representation_artifact").get(run=row, tenant_id=tenant)
        snapshot = snapshot_for(row)
        config = object_fields(snapshot.execution["plugins"][0]["config"])
        with transaction.atomic():
            actor, version, reference = current(UUID(str(config["actor_id"])), fit.representation_artifact.research_version_id, allow_validating=True)
            limits = ImportLimits(**snapshot.execution["plugins"][0]["config"]["import_limits"])
            if (row.document["environment_digest"] != environment() or reference.sha256 != config["source_sha256"]
                    or str(reference.version) != config["source_object_version"]):
                raise ApiError("CHECKPOINT_INCOMPATIBLE", 409)
            source_candidate(fit)
            parameters = {name: str(value) for name, value in object_fields(fit.document["parameters"]).items()}
            settings_document = configuration(version, limits, canonical_bytes(fit.equation_version.document["dsl"]), parameters)
            check_submission(lease)
            store = LocalVersionStore(settings.OBJECT_ROOT)
            content = store.read_verified(reference)
        report = inspect_research(content, version.dataset_version.document["format"], limits, settings_document)
        report_check(report, settings_document)
        if report["quality"] != "PASS":
            raise ApiError("DATA_QUALITY_BLOCKED", 409)
        with transaction.atomic():
            locked = lock_run(tenant, identity)
            actor, version, reference = current(actor.id, version.id, allow_validating=True)
            store.verify(reference)
            usage = meter.usage()
            finish(lease, usage, lambda: persist_results(actor, version, fit, locked, report), lambda _run, _code: None)
            SearchAttemptStop.objects.get_or_create(attempt_id=lease.attempt_id)
            report_usage(lease, usage_report(lease, usage, 1), stopped=True)
    except (ApiError, ImportRejected, StorageRejected, ControlError, OSError, DatabaseError, ValueError) as error:
        with transaction.atomic():
            row = lock_run(tenant, identity)
            usage = meter.usage()
            SearchAttemptStop.objects.get_or_create(attempt_id=lease.attempt_id)
            if row.document["status"] == "CANCEL_REQUESTED":
                confirm_business_stopped(lease, usage)
            else:
                try:
                    finish(lease, usage, lambda: None, lambda _run, _code: None, getattr(error, "code", "DEPENDENCY_UNAVAILABLE"))
                except ControlError:
                    recover(tenant, identity)
            report_usage(lease, usage_report(lease, usage, 1), stopped=True)
    return True
