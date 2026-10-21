"""真正 PROFILE 業務執行：固定來源、目前授權、lease fencing 與原子品質提交。

Fenced business PROFILE with real reservations and private research results."""
from datetime import datetime
import math
from uuid import UUID, uuid4
from django.conf import settings
from django.db import DatabaseError, transaction
from catalog.artifacts import register
from catalog.budget import report_usage, reserve, release_unstarted, usage_report
from catalog.ingest import Meter
from catalog.ingest_manifest import environment
from catalog.inspection import current, configuration
from catalog.models import Account, Audit, ProfileBinding, Provenance, ResearchBudget, ResearchVersion, Reservation, SealRegistration
from catalog.profile_manifest import documents, limits_for, limit_for
from catalog.research_state import state_for, transition
from catalog.sealing import attach, registration
from catalog.services import provenance
from catalog.storage import LocalVersionStore, StorageRejected
from catalog.validation import ApiError
from ingestion.limits import ImportLimits, ImportRejected
from ingestion.supervisor import inspect_research
from runtime.completion import finish, confirm_business_stopped
from runtime.contracts import JsonObject, identity_hash, validate
from runtime.budget_types import BudgetUsage
from runtime.control import Lease, check_submission, claim, enqueue, recover
from runtime.models import RuntimeAttempt, RuntimeRun
from runtime.records import ControlError, db_now, lock_run, public_run, save_attempt, save_run, snapshot_for, state_event
from sealing.types import Attestation


def enqueue_profile(actor: Account, version: ResearchVersion, data: JsonObject, revision: int) -> JsonObject:
    """在 API 外層交易中固定輸入、來源與環境，原子建立 root、預留及 VALIDATING 狀態。

    caller 已持授權鎖；取得新 root 鎖後才鎖研究狀態及帳本，revision 衝突使全部副作用回滾。"""
    limits = limits_for(version)
    account = ResearchBudget.objects.get(research_version=version,tenant_id=actor.tenant_id)
    limit = limit_for(account,data.get("run_budget"),limits)
    _actor,_version,reference = current(actor.id,version.id,allow_validating=True)
    LocalVersionStore(settings.OBJECT_ROOT).verify(reference)
    input_id,source_id = uuid4(),uuid4()
    record,task,execution,budget = documents(actor,version,account,limit,limits,str(input_id),str(source_id))
    source = Provenance.objects.get(pk=version.provenance_id,tenant_id=actor.tenant_id)
    provenance(actor,"Run",UUID(record["id"]),source_id,source)
    binding = ProfileBinding(run_id=UUID(record["id"]),tenant_id=actor.tenant_id,research_version=version,dataset_id=version.dataset_version.dataset_id,actor=actor,root_budget_id=UUID(budget["id"]))
    register(actor,binding,input_id,task,source,research_version=version)
    identity = enqueue(actor.tenant_id,record,task,execution,budget,control_only=False)
    run = lock_run(actor.tenant_id,identity)
    state = state_for(version)
    if state.revision!=revision:
        raise ApiError("REVISION_CONFLICT",412)
    if state.active_run_id is not None or state.status!="DRAFT":
        raise ApiError("INVALID_TRANSITION",409)
    reserve(run,budget)
    binding.save(force_insert=True)
    state.active_run_id = identity
    state.quality_id,state.structure_id = None,None
    transition(state,"VALIDATING")
    Audit.objects.create(tenant_id=actor.tenant_id,actor_id=actor.id,action="QUEUE_PROFILE",code="OK")
    return public_run(actor.tenant_id,identity)


def close_state(binding: ProfileBinding, quality: UUID | None = None, structure: UUID | None = None, seal: SealRegistration | None = None) -> None:
    """僅清除屬於本 root 的活躍狀態；只有同時具備原生封存登記才投影 READY，否則回 DRAFT。"""
    state = state_for(binding.research_version)
    if state.active_run_id==binding.run_id:
        state.active_run_id = None
        state.quality_id,state.structure_id,state.seal = quality,structure,seal
        transition(state,"READY" if seal is not None else "DRAFT")


def recover_profile(tenant: UUID, identity: UUID) -> None:
    """以 root 鎖序列化逾時與取消裁決；未啟動可釋放，已啟動失聯必須保留未知成本。"""
    with transaction.atomic():
        run = lock_run(tenant,identity)
        binding = ProfileBinding.objects.get(run=run)
        recover(tenant,identity)
        run.refresh_from_db()
        if run.document["status"] in {"FAILED","CANCELLED"}:
            # State lock precedes account locks in every root-owned transaction.
            close_state(binding)
            release_unstarted(run)
        elif run.document["status"]=="CANCEL_REQUESTED" and (run.first_started_at is None or Reservation.objects.get(root=binding.root_budget).state=="RELEASED"):
            if run.document["active_attempt_id"] is not None:
                attempt = RuntimeAttempt.objects.select_for_update().get(pk=UUID(run.document["active_attempt_id"]))
                attempt.document.update(status="CANCELLED",finished_at=db_now().isoformat())
                save_attempt(attempt)
            run.document.update(status="CANCELLED",stop_reason="USER_CANCELLED",dispatch_stage="CLOSED")
            run.document["revision"] += 1
            state_event(run,"RunCancelled",db_now())
            save_run(run)
            close_state(binding)
            release_unstarted(run)
        elif run.document["status"]=="CANCEL_REQUESTED" and run.document["active_attempt_id"] is not None:
            attempt = RuntimeAttempt.objects.get(pk=UUID(run.document["active_attempt_id"]))
            if datetime.fromisoformat(attempt.document["lease_expires_at"])<=db_now():
                release_unstarted(run)


def inputs(binding: ProfileBinding, lease: Lease) -> tuple[bytes,str,ImportLimits,JsonObject]:
    """領取後重驗 lease、現行授權與固定來源；比對完整快照及環境後才讀 bytes，解析不持 DB 鎖。"""
    check_submission(lease)
    with transaction.atomic():
        _actor,version,reference = current(binding.actor_id,binding.research_version_id,allow_validating=True)
        run = RuntimeRun.objects.get(pk=binding.run_id)
        snapshot = snapshot_for(run)
        plugin = snapshot.execution["plugins"][0]["config"]
        limits = ImportLimits(**plugin["import_limits"])
        config = configuration(version,limits,None,{})
        expected = {key:version.document[key] for key in ("dataset_version_id","semantic_profile","observation_split","domain","evaluation_policy")}
        if snapshot.task_input["payload"]!=expected or run.document["environment_digest"]!=environment() or plugin["source_sha256"]!=reference.sha256 or plugin["source_object_version"]!=str(reference.version):
            raise ApiError("CHECKPOINT_INCOMPATIBLE",409)
        content = LocalVersionStore(settings.OBJECT_ROOT).read_verified(reference)
        return content,version.dataset_version.document["format"],limits,config


def results(binding: ProfileBinding, run: RuntimeRun, result: JsonObject, execution: UUID, seal: Attestation | None = None, remaining: str = "") -> tuple[UUID,UUID | None]:
    """提交遮罩品質報告；只有 PASS 才產生 fit-only／UNKNOWN 結構，READY 需同時有封存登記。"""
    version = binding.research_version
    source = Provenance.objects.get(pk=UUID(run.document["provenance_id"]),tenant_id=binding.tenant_id)
    ready = seal is not None
    report: JsonObject = {"kind":"QualityReport","schema_version":"1.0","research_version_id":str(version.id),"run_id":str(run.id),"quality":result["quality"],
        "blocking_code":result["blocking_code"],"fit_summary":result["fit_summary"],"readiness":"READY" if ready else "BLOCKED",
        "remaining":[] if ready else [remaining or "SEALED_TEST_NOT_REGISTERED"],"precision_bits":53}
    quality = register(binding.actor,binding,uuid4(),report,source,research_version=version)
    structure_id = None
    if result["quality"]=="PASS":
        structure_id = uuid4()
        structure: JsonObject = {"kind":"StructureAssessment","id":str(structure_id),"tenant_id":str(binding.tenant_id),"research_version_id":str(version.id),"schema_version":"1.0",
            "created_at":db_now().isoformat(),"artifact_access_class":"PROJECT","dataset_version_id":str(version.dataset_version_id),"observation_dimension":2,"coordinate_dimension":None,
            "representation_dimension":1,"intrinsic_dimension_estimate":None,"structure_candidates":["UNKNOWN"],"time_basis":"UNKNOWN","periodicity":"UNKNOWN",
            "method_manifest_id":str(execution),"fit_rows_hash":identity_hash(version.document["observation_split"]["fit"]),"uncertainty_reason":"Fit-only scalar quality checked; structural identification and physical semantics remain unestablished","analysis_scope":"FIT_ONLY"}
        validate(structure,"research-learning-v1.schema.json","StructureAssessment")
        register(binding.actor,binding,structure_id,structure,source,research_version=version)
    binding.result = quality
    binding.save(update_fields=["result"])
    return quality.id,structure_id


def measured(run: RuntimeRun, meter: Meter) -> BudgetUsage:
    """保留具體用量型別；wall 至少涵蓋首次啟動至結算前，CPU／RSS 沿用保守量測。"""
    usage = meter.usage()
    if run.first_started_at is not None:
        usage["elapsed_wall_seconds"] = max(usage["elapsed_wall_seconds"],math.ceil((db_now()-run.first_started_at).total_seconds()))
    return usage


def submit(binding: ProfileBinding, lease: Lease, result: JsonObject, meter: Meter, content: bytes, format_name: str, limits: ImportLimits, config: object) -> None:
    """提交前再驗授權、來源及 fencing；封存副作用早於 app DB commit，未通過不得投影 READY。"""
    attestation: Attestation | None = None
    remaining = ""
    if result["quality"]=="PASS" and settings.SEALING_ENABLED:
        attestation,remaining = attach(content,format_name,limits,config)
    with transaction.atomic():
        actor,_version,reference = current(binding.actor_id,binding.research_version_id,allow_validating=True)
        LocalVersionStore(settings.OBJECT_ROOT).verify(reference)
        run = lock_run(lease.tenant_id,lease.run_id)
        state_for(binding.research_version)
        usage = measured(run,meter)
        references: list[tuple[UUID,UUID | None]] = []
        registrations: list[SealRegistration] = []
        def commit() -> None:
            # 公有 DB 先落不透明封存登記，品質報告才能在原生防線下投影 READY。
            if attestation is not None:
                registrations.append(registration(actor,binding,run,attestation))
            references.append(results(binding,run,result,UUID(run.document["execution_manifest_id"]),attestation,remaining))
        def failed(_row: RuntimeRun,code: str) -> None:
            binding.error_code = code
            binding.save(update_fields=["error_code"])
        finish(lease,usage,commit,failed)
        report_usage(lease,usage_report(lease,usage),stopped=True)
        quality,structure = references[0] if references else (None,None)
        seal = registrations[0] if registrations else None
        close_state(binding,quality,structure,seal)
        Audit.objects.create(tenant_id=actor.tenant_id,actor_id=actor.id,action="PROFILE_FINISHED",code=result["quality"] if references else "BUDGET_EXHAUSTED")


def reject(binding: ProfileBinding, lease: Lease, meter: Meter, code: str) -> None:
    """child 已停止後仍如實入帳；取消／過期可拒收產物，不能因此丟掉實際成本。"""
    with transaction.atomic():
        run = lock_run(lease.tenant_id,lease.run_id)
        state_for(binding.research_version)
        usage = measured(run,meter)
        report_usage(lease,usage_report(lease,usage),stopped=True)
        run.refresh_from_db()
        if run.document["status"]=="CANCEL_REQUESTED":
            confirm_business_stopped(lease,usage)
        elif run.document["status"] not in {"SUCCEEDED","FAILED","CANCELLED"}:
            def failure(_row: RuntimeRun,error: str) -> None:
                binding.error_code = error
                binding.save(update_fields=["error_code"])
            try:
                finish(lease,usage,lambda:None,failure,code)
            except ControlError:
                recover(lease.tenant_id,lease.run_id)
        close_state(binding)


def profile_tick(tenant_id: str, run_id: str, generation: int) -> bool:
    """專用 worker 的唯一 PROFILE 入口；重複派送由 claim 拒絕，失敗經停止確認路徑結算。"""
    if not settings.PROFILE_ENABLED:
        return False
    binding = ProfileBinding.objects.filter(run_id=UUID(run_id),tenant_id=UUID(tenant_id)).first()
    if binding is None:
        return False
    with transaction.atomic():
        lock_run(binding.tenant_id,binding.run_id)
        lease = claim(binding.tenant_id,binding.run_id,generation,"profile:"+str(uuid4()))
        if lease is None:
            recover_profile(binding.tenant_id,binding.run_id)
            return False
    meter = Meter()
    try:
        content,format_name,limits,config = inputs(binding,lease)
        result = inspect_research(content,format_name,limits,config)
        submit(binding,lease,result,meter,content,format_name,limits,config)
    except (ApiError,ImportRejected,StorageRejected) as error:
        reject(binding,lease,meter,error.code)
    except (OSError,DatabaseError):
        reject(binding,lease,meter,"DEPENDENCY_UNAVAILABLE")
    except ControlError:
        reject(binding,lease,meter,"STALE_ATTEMPT")
    return True
