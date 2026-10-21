"""Actual loopback HTTP to dedicated PROFILE worker and paired budget ledgers."""
from io import BytesIO
import json
import secrets
from typing import Any
from uuid import UUID, uuid4
import polars as pl
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from catalog.management.commands.business_ingest_smoke import upload, wait_run
from catalog.management.commands.catalog_smoke import Browser
from catalog.management.commands.research_draft_smoke import check, configuration
from catalog.models import Account, ProfileBinding, ResearchBudget, Reservation, RootBudget, Tenant, UsageReceipt
from catalog.services import set_grant
from runtime.contracts import JsonObject, identity_hash

MEMORY = 2*1024**3


def start(browser: Browser, version: str, revision: int, key: str) -> tuple[int,JsonObject]:
    status,raw = browser.request(f'/api/v2/research-versions/{version}/validate',"POST",b'{}',{"Content-Type":"application/json","Idempotency-Key":key,"If-Control-Revision":str(revision)})
    return status,json.loads(raw)


def version_read(browser: Browser, identity: str) -> JsonObject:
    status,raw = browser.request('/api/v2/research-versions/'+identity)
    check(status==200,"Research unavailable")
    return json.loads(raw)


def draft(browser: Browser, dataset: str, content: bytes, format_name: str, *, tiny_budget: bool = False) -> JsonObject:
    checksum,run = upload(browser,dataset,content,format_name)
    check(run["status"]=="SUCCEEDED","INGEST failed")
    status,raw = browser.request(f'/api/v2/datasets/{dataset}/versions')
    check(status==200,"Dataset version unavailable")
    source = next(row for row in json.loads(raw)["items"] if row["sha256"]==checksum)
    status,research = browser.post('/api/v2/researches',{"name":"actual-profile"})
    check(status==201,"Research rejected")
    data = configuration(source["id"])
    data["budget"].update(memory_bytes=MEMORY,cpu_seconds=13 if tiny_budget else 100,wall_seconds=20 if tiny_budget else 300)
    status,version = browser.post(f'/api/v2/researches/{research["id"]}/versions',data)
    check(status==201,"Draft rejected")
    return version


def verified_profile(browser: Browser, version: JsonObject, revision: int, key: str, expected_quality: str) -> JsonObject:
    status,queued = start(browser,version["id"],revision,key)
    check(status==202,"PROFILE not queued")
    run = wait_run(browser,queued["id"])
    check(run["status"]=="SUCCEEDED","PROFILE worker failed")
    current = version_read(browser,version["id"])
    check(current["status"]=="DRAFT" and current["revision"]==revision+2,"Premature READY or invalid revision")
    status,raw = browser.request(f'/api/v2/artifacts/{current["quality_report_id"]}/content')
    report = json.loads(raw)
    check(status==200 and report["quality"]==expected_quality and report["readiness"]=="BLOCKED","Quality report mismatch")
    check("final_test" not in report and "private-final-marker" not in raw.decode(),"Final detail exposed")
    if expected_quality=="PASS":
        status,raw = browser.request(f'/api/v2/artifacts/{current["structure_assessment_artifact_id"]}/content')
        structure = json.loads(raw)
        check(status==200 and structure["analysis_scope"]=="FIT_ONLY" and structure["fit_rows_hash"]==identity_hash(version["observation_split"]["fit"]),"Fit assessment mismatch")
    else:
        check(report["fit_summary"] is None and current["structure_assessment_artifact_id"] is None,"Unmasked quality failure")
    root = RootBudget.objects.get(run_id=UUID(run["id"]))
    check(root.document["usage"]==run["budget_usage"] and root.document["status"]=="CLOSED","Root budget not settled")
    check(Reservation.objects.get(root=root).state=="RELEASED" and UsageReceipt.objects.filter(root=root).count()==1,"Receipt/reservation not settled once")
    status,repeated = start(browser,version["id"],revision,key)
    check(status==202 and repeated==queued,"Replay changed original operation")
    return {"run_id":run["id"],"research_version_id":version["id"],"quality_report_id":current["quality_report_id"],"structure_assessment_artifact_id":current["structure_assessment_artifact_id"],
        "quality":expected_quality,"revision":current["revision"],"run_usage":run["budget_usage"],"research_usage":current["research_budget_usage"],"report":report}


class Command(BaseCommand):
    help = "Verify real PROFILE queue/worker, artifacts, paired ledgers, quota and revoked reads"

    def handle(self,*args: Any,**options: Any) -> None:
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="profile-"+uuid4().hex,password=password)
        actor = Account.objects.create(user=user,tenant=Tenant.objects.create(name="profile-synthetic"),role="ADMIN")
        browser = Browser()
        browser.login(user.get_username(),password)
        status,dataset = browser.post('/api/v2/datasets',{"name":"profile-three-formats"})
        check(status==201,"Dataset rejected")
        rows = [(i,2*i+1) for i in range(10)]
        csv = ('時間（秒）,位移（公分）\n'+''.join(f'{x},{y}\n' for x,y in rows)).encode()
        records = json.dumps([{"時間（秒）":x,"位移（公分）":y} for x,y in rows]).encode()
        buffer = BytesIO()
        pl.DataFrame({"時間（秒）":[x for x,_y in rows],"位移（公分）":[y for _x,y in rows]}).write_parquet(buffer)
        results: list[JsonObject] = []
        versions: list[JsonObject] = []
        for name,content in (("CSV",csv),("JSON",records),("PARQUET",buffer.getvalue())):
            version = draft(browser,dataset["id"],content,name)
            versions.append(version)
            results.append(verified_profile(browser,version,0,"profile-"+name,"PASS") | {"format":name})
        second = verified_profile(browser,versions[0],2,"second-root","PASS")
        expected_cpu = results[0]["run_usage"]["cpu_seconds"]+second["run_usage"]["cpu_seconds"]
        check(second["research_usage"]["cpu_seconds"]==expected_cpu,"New root reset or double-charged research budget")
        invalid = ('時間（秒）,位移（公分）\n'+''.join(f'{x},{y if x<9 else "private-final-marker"}\n' for x,y in rows)).encode()
        bad = verified_profile(browser,draft(browser,dataset["id"],invalid,"CSV"),0,"invalid","BLOCKED")
        tiny = draft(browser,dataset["id"],csv,"CSV",tiny_budget=True)
        tiny_result = verified_profile(browser,tiny,0,"tiny-first","PASS")
        status,error = start(browser,tiny["id"],2,"tiny-second")
        check(status==429 and error["code"]=="RESEARCH_BUDGET_EXHAUSTED","Insufficient remaining capacity was reused")
        check(ProfileBinding.objects.filter(research_version_id=UUID(tiny["id"])).count()==1,"Rejected root left side effects")
        account = ResearchBudget.objects.get(research_version_id=UUID(tiny["id"]))
        check(account.document["usage"]==tiny_result["run_usage"] and not account.document["reservations"],"Quota denial modified ledger")
        status,events = browser.request(f'/api/v2/research-versions/{versions[0]["id"]}/events',headers={"Last-Event-ID":f'RESEARCH:{versions[0]["id"]}:1'})
        check(status==200 and b'ResearchVersionStateChanged' in events,"Research event replay failed")
        set_grant(actor.id,actor.id,UUID(dataset["id"]),None)
        for path in (f'/api/v2/runs/{second["run_id"]}',f'/api/v2/artifacts/{second["quality_report_id"]}/content',f'/api/v2/research-versions/{versions[0]["id"]}/events'):
            status,_raw = browser.request(path)
            check(status==404,"Revoked research remained readable")
        status,_response = start(browser,versions[0]["id"],0,"profile-CSV")
        check(status==404,"Cached operation bypassed revoked grant")
        self.stdout.write(json.dumps({"scope":"T07_ACTUAL_PROFILE","status":"PASS","results":results,"second_root":second,"masked":bad,"quota_case":tiny_result,
            "quota_denial_status":429,"revoked_status":404,"research_status":"DRAFT","formal_seal":"NOT_IMPLEMENTED","product_gate_status":"NOT_RUN"},indent=2))
