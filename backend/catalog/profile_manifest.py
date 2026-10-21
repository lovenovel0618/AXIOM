"""Explicit, real PROFILE snapshots and the fixed local worker capacity."""
import json
import platform
from uuid import uuid4
from django.conf import settings
from catalog.budget import remaining, zero_usage
from catalog.ingest_manifest import code_digest, environment
from catalog.models import Account, ResearchBudget, ResearchVersion
from catalog.validation import ApiError
from ingestion.limits import ImportLimits
from runtime.contracts import JsonObject, identity_hash
from runtime.records import db_now, task_input_hash

MEMORY = 2 * 1024**3


def limits_for(version: ResearchVersion) -> ImportLimits:
    if not settings.PROFILE_ENABLED or platform.system()!="Linux":
        raise ApiError("DEPENDENCY_UNAVAILABLE",503)
    try:
        limits = ImportLimits(**json.loads(settings.PROFILE_LIMITS_JSON))
    except (TypeError,ValueError) as error:
        raise ApiError("DEPENDENCY_UNAVAILABLE",503) from error
    if version.dataset_version.document["row_count"]>min(limits.max_rows,4096):
        raise ApiError("IMPORT_LIMIT_EXCEEDED",413)
    return limits


def limit_for(account: ResearchBudget, requested: JsonObject | None, limits: ImportLimits) -> JsonObject:
    available = remaining(account)
    limit = requested if requested is not None else {"cpu_seconds":min(available["cpu_seconds"],limits.max_parse_seconds+15),"wall_seconds":min(available["wall_seconds"],limits.max_parse_seconds+30),
        "memory_bytes":MEMORY,"gpu_seconds":0,"tokens":0,"candidate_limit":0}
    if any(limit[key]>account.document["limit"][key] for key in limit):
        raise ApiError("RUN_BUDGET_EXHAUSTED",429)
    if limit["memory_bytes"]<MEMORY or limit["cpu_seconds"]<limits.max_parse_seconds+3 or limit["wall_seconds"]<limits.max_parse_seconds+10:
        raise ApiError("RESEARCH_BUDGET_EXHAUSTED" if requested is None else "RUN_BUDGET_EXHAUSTED",429)
    if limit["cpu_seconds"]>300 or limit["wall_seconds"]>300:
        raise ApiError("RUN_BUDGET_EXHAUSTED",429)
    return limit


def documents(actor: Account, version: ResearchVersion, account: ResearchBudget, limit: JsonObject, limits: ImportLimits, input_id: str, provenance_id: str) -> tuple[JsonObject,JsonObject,JsonObject,JsonObject]:
    run_id,execution_id,budget_id = (str(uuid4()) for _index in range(3))
    created = db_now().isoformat()
    document = version.document
    payload = {key:document[key] for key in ("dataset_version_id","semantic_profile","observation_split","domain","evaluation_policy")}
    task: JsonObject = {"kind":"TaskInput","schema_version":"2.0","run_id":run_id,"type":"PROFILE","research_version_id":str(version.id),
        "observation_split_id":payload["observation_split"]["id"],"execution_manifest_id":execution_id,"payload":payload}
    config = {"import_limits":limits.document(),"source_sha256":version.dataset_version.sha256,"source_object_version":str(version.dataset_version.raw.object_id),
        "capacity_policy":"local-profile-v1","source_policy":"LOCAL_OWN_SYNTHETIC_ONLY"}
    execution: JsonObject = {"kind":"ExecutionManifest","id":execution_id,"tenant_id":str(actor.tenant_id),"schema_version":"2.0","created_at":created,
        "environment_digest":environment(),"input_hash":task_input_hash(task),"semantic_profile_hash":identity_hash(payload["semantic_profile"]),"seed":payload["observation_split"]["seed"],
        "plugins":[{"plugin_id":"local-bounded-profile","version":"1","code_sha256":code_digest(),"config":config,"config_sha256":identity_hash(config)}],
        "retry_policy":{"max_attempts":1,"queue_timeout_seconds":60,"backoff_initial_seconds":1,"backoff_max_seconds":1}}
    budget: JsonObject = {"kind":"BudgetAccount","id":budget_id,"tenant_id":str(actor.tenant_id),"schema_version":"2.0","created_at":created,"root_run_id":run_id,
        "research_budget_account_id":str(account.id),"limit":limit,"usage":zero_usage(),"reservations":[],"status":"OPEN"}
    record: JsonObject = {"kind":"RunRecord","id":run_id,"tenant_id":str(actor.tenant_id),"schema_version":"2.0","created_at":created,
        "research_version_id":str(version.id),"dataset_id":None,"type":"PROFILE","status":"QUEUED","revision":0,"seed":execution["seed"],"environment_digest":execution["environment_digest"],
        "active_attempt_id":None,"lease_generation":0,"current_event_cursor":f"RUN:{run_id}:0","budget_usage":zero_usage(),"phase":None,"stop_reason":None,
        "evidence_bundle_ids":[],"child_run_ids":[],"is_root":True,"budget_reservations":[],"parent_run_id":None,"root_run_id":run_id,"budget_account_id":budget_id,
        "cancel_requested_at":None,"cancellation_epoch":0,"root_epoch_at_dispatch":0,"input_artifact_id":input_id,"outcome_status":None,"skipped_phases":[],"dispatch_stage":"SEARCH_OPEN",
        "diagnostic_artifact_ids":[],"research_budget_account_id":str(account.id),"provenance_id":provenance_id,"execution_manifest_id":execution_id,"research_trace_artifact_ids":[]}
    return record,task,execution,budget
