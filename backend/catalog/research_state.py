"""Mutable state projection beside the immutable research configuration."""
from uuid import uuid4
from catalog.models import EvidenceBundle, FrozenSubmission, ResearchBudget, ResearchEvent, ResearchState, ResearchVersion
from runtime.contracts import JsonObject, validate
from runtime.records import db_now, detached


def state_for(version: ResearchVersion) -> ResearchState:
    """取得版本唯一狀態投影並加列鎖；呼叫端須先持相關 root 鎖。"""
    state,_created = ResearchState.objects.get_or_create(research_version=version,defaults={"tenant_id":version.tenant_id})
    return ResearchState.objects.select_for_update().get(pk=state.pk)


def transition(state: ResearchState, status: str) -> None:
    """控制狀態每次加一 revision，並在同交易保存不可變研究事件；用量更新不走此路徑。"""
    state.status = status
    state.revision += 1
    state.save()
    identity = uuid4()
    event: JsonObject = {"event_id":str(identity),"schema_version":"2.0","event_type":"ResearchVersionStateChanged","tenant_id":str(state.tenant_id),
        "research_version_id":str(state.research_version_id),"run_id":None,"stream_scope":"RESEARCH","stream_id":str(state.research_version_id),"sequence":state.revision,
        "occurred_at":db_now().isoformat(),"trace_id":str(state.research_version_id),"producer_version":"t07-profile-v1","payload":{"status":status,"revision":state.revision}}
    validate(event,"event-v2.schema.json")
    ResearchEvent.objects.create(id=identity,research_version_id=state.research_version_id,sequence=state.revision,document=event)


def document_for(version: ResearchVersion) -> JsonObject:
    """合成不可變配置、最新用量與狀態；不改寫原草稿，封存只投影至 split 的引用欄。"""
    document = detached(version.document)
    account = ResearchBudget.objects.get(research_version=version)
    document["research_budget_usage"] = account.document["usage"]
    document["frozen_submission_ids"] = [str(value) for value in FrozenSubmission.objects.filter(research_version=version).order_by("created_at","id").values_list("id",flat=True)]
    document["evidence_bundle_ids"] = [str(value) for value in EvidenceBundle.objects.filter(research_version=version).order_by("created_at","id").values_list("id",flat=True)]
    state = ResearchState.objects.filter(research_version=version).first()
    if state is not None:
        seal = state.seal
        split = dict(document["observation_split"])
        split["sealed_test_id"] = None if seal is None else str(seal.sealed_test_id)
        document.update(status=state.status,revision=state.revision,current_event_cursor=f"RESEARCH:{version.id}:{state.revision}",
            quality_report_id=None if state.quality_id is None else str(state.quality_id),structure_assessment_artifact_id=None if state.structure_id is None else str(state.structure_id),
            observation_split=split)
    validate(document,"research-v2.schema.json","ResearchVersion")
    return document
