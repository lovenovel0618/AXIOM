"""私有研究的取消與有界 SSE；每次請求重新驗權，取消須等真正停止證明。

Authorized PROFILE cancellation and bounded, resumable SSE batches."""
import json
from uuid import UUID
from django.http import HttpRequest, HttpResponse, JsonResponse
from catalog.http import allowed_methods, api, body
from catalog.models import Account, ResearchEvent
from catalog.profile import recover_profile
from catalog.read_http import run_for
from catalog.research import available_version, version_for
from catalog.research_http import control_revision
from catalog.services import replay
from catalog.validation import ApiError
from runtime.control import cancel
from runtime.models import InputSnapshot, RunEvent
from runtime.records import TERMINAL, lock_run, public_run


@allowed_methods(["POST"])
@api
def cancel_run(request: HttpRequest, actor: Account, identity: UUID) -> JsonResponse:
    """公開取消只接受根任務；對子任務回 409 並揭露授權範圍內的 root_run_id。

    根路徑重新驗 owner 與租戶分區；冪等操作在 root 鎖內檢查 revision，再交取消／恢復裁決。"""
    run = run_for(actor,identity)
    if not run.document["is_root"]:
        root_id = UUID(run.document["root_run_id"])
        run_for(actor,root_id)
        raise ApiError("CHILD_RUN_NOT_CANCELLABLE",409,[{"field":"root_run_id","reason":str(root_id)}])
    if run.document["type"] not in {"PROFILE", "SEARCH", "FIT"}:
        raise ApiError("DEPENDENCY_UNAVAILABLE",503)
    if run.document["type"] in {"SEARCH", "FIT"} and not InputSnapshot.objects.filter(run=run).exists():
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    version = version_for(actor, UUID(run.document["research_version_id"]))
    available_version(actor,version.dataset_version_id)
    expected = control_revision(request)
    data = body(request,"Empty")
    def action() -> dict[str,object]:
        row = lock_run(actor.tenant_id,identity)
        if row.document["revision"]!=expected:
            raise ApiError("REVISION_CONFLICT",412)
        if row.document["status"] in TERMINAL:
            raise ApiError("INVALID_TRANSITION",409)
        cancel(actor.tenant_id,identity,expected)
        if run.document["type"] == "FIT":
            from catalog.fit import recover_fit
            recover_fit(actor.tenant_id, identity)
        elif run.document["type"] == "SEARCH":
            from catalog.search import recover_search
            recover_search(actor.tenant_id, identity)
        else:
            recover_profile(actor.tenant_id,identity)
        return public_run(actor.tenant_id,identity)
    def authorize(_previous: dict[str,object]) -> None:
        version_for(actor,version.id)
        available_version(actor,version.dataset_version_id)
    response = replay(actor,request.path,request.headers.get("Idempotency-Key",""),data,action,authorize)
    return JsonResponse(response,status=202)


def after(request: HttpRequest, scope: str, identity: UUID, maximum: int) -> int:
    """只接受相同 scope／UUID 的 Last-Event-ID；未發生的序號與 query 篩選均拒絕。"""
    if request.GET:
        raise ApiError("INVALID_SCHEMA",422)
    cursor = request.headers.get("Last-Event-ID",f"{scope}:{identity}:0")
    parts = cursor.split(":")
    if len(parts)!=3 or parts[:2]!=[scope,str(identity)] or not parts[2].isascii() or not parts[2].isdecimal() or len(parts[2])>16:
        raise ApiError("INVALID_CURSOR",400)
    sequence = int(parts[2])
    if sequence>maximum:
        raise ApiError("INVALID_CURSOR",400)
    return sequence


def stream(scope: str, identity: UUID, events: list[dict[str,object]]) -> HttpResponse:
    """產生最多一批已授權事件的 SSE 回應；關閉後由客戶端攜游標重新連線及驗權。"""
    frames = ["retry: 2000\n\n"]
    for event in events:
        cursor = f"{scope}:{identity}:{event['sequence']}"
        frames.append(f"id: {cursor}\nevent: {event['event_type']}\ndata: {json.dumps(event,ensure_ascii=True,allow_nan=False)}\n\n")
    if not events:
        frames.append(": keepalive\n\n")
    response = HttpResponse("".join(frames),content_type="text/event-stream")
    response["X-Accel-Buffering"] = "no"
    return response


@allowed_methods(["GET"])
@api
def run_events(request: HttpRequest, actor: Account, identity: UUID) -> HttpResponse:
    """每次請求驗目前 Run 存取權，依序回傳游標之後最多 100 筆事件。"""
    row = run_for(actor,identity)
    maximum = int(row.document["current_event_cursor"].rsplit(":",1)[1])
    sequence = after(request,"RUN",identity,maximum)
    events = list(RunEvent.objects.filter(run=row,sequence__gt=sequence).order_by("sequence")[:100])
    return stream("RUN",identity,[event.document for event in events])


@allowed_methods(["GET"])
@api
def research_events(request: HttpRequest, actor: Account, identity: UUID) -> HttpResponse:
    """研究事件只給 owner 與租戶分區的交集；不符時亦不可讀。"""
    version = version_for(actor,identity)
    latest = ResearchEvent.objects.filter(research_version=version).order_by("-sequence").first()
    maximum = 0 if latest is None else latest.sequence
    sequence = after(request,"RESEARCH",identity,maximum)
    events = list(ResearchEvent.objects.filter(research_version=version,sequence__gt=sequence).order_by("sequence")[:100])
    return stream("RESEARCH",identity,[event.document for event in events])
