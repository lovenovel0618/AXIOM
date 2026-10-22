"""Real HTTP source/draft creation followed by the trusted local inspection CLI."""
from io import BytesIO, StringIO
import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4
import polars as pl
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand
from catalog.inspection import preflight
from catalog.management.commands.business_ingest_smoke import upload
from catalog.management.commands.catalog_smoke import Browser
from catalog.management.commands.research_draft_smoke import check, configuration
from catalog.models import Account, Tenant
from ingestion.limits import ImportLimits
from runtime.contracts import JsonObject, identity_hash

LIMITS = ImportLimits(100,8,4096,65536,10)


def known_model(domain: list[JsonObject]) -> JsonObject:
    return {"dsl_version":"1.0","variables":[{"name":"x","unit":[0]*7}],"parameters":[],"domain":domain,
        "root":{"op":"add","args":[{"op":"mul","args":[{"op":"const","value":{"numerator":"2","denominator":"1"}},{"op":"var","name":"x"}]},{"op":"const","value":{"numerator":"1","denominator":"1"}}]}}


def inspect_version(browser: Browser, actor: Account, dataset: str, content: bytes, format_name: str, expected: str) -> JsonObject:
    checksum, run = upload(browser,dataset,content,format_name)
    check(run["status"]=="SUCCEEDED","INGEST failed")
    status, raw = browser.request(f'/api/v2/datasets/{dataset}/versions')
    check(status==200,"Versions unavailable")
    version = next(row for row in json.loads(raw)["items"] if row["sha256"]==checksum)
    status, research = browser.post('/api/v2/researches',{"name":"known-linear-inspection"})
    check(status==201,"Research unavailable")
    data = configuration(version["id"])
    source,target = data["semantic_profile"]["inputs"][0],data["semantic_profile"]["target"]
    source.update(source_column="觀測值",unit=[0]*7,conversion={"source_unit":"1","scale":"1","offset":"0"})
    target.update(source_column="量測值",unit=[0]*7,conversion={"source_unit":"scaled synthetic count","scale":"0.01","offset":"0"})
    status, draft = browser.post(f'/api/v2/researches/{research["id"]}/versions',data)
    check(status==201,"Draft unavailable")
    model = known_model(draft["domain"])
    with TemporaryDirectory() as directory:
        path = Path(directory)/"model.json"
        path.write_text(json.dumps(model))
        output = StringIO()
        call_command('research_inspect',str(actor.id),draft["id"],max_rows=100,max_columns=8,max_cell_utf8_bytes=4096,max_decoded_bytes=65536,max_parse_seconds=10,dsl_file=str(path),parameters="{}",stdout=output)
        report: JsonObject = json.loads(output.getvalue())
    check(report["result"]["quality"]==expected,"Unexpected quality")
    repeated = preflight(actor.id,UUID(draft["id"]),LIMITS,json.dumps(model).encode())
    check(report==repeated,"Inspection replay failed")
    if expected=="PASS":
        scores = report["result"]["model_evaluation"]
        check(set(scores)=={"fit","development"},"Final evaluation exposed")
        check(all(score["coverage"]=="1" and score["mae"]=="0" and score["rmse"]=="0" for score in scores.values()),"Known formula mismatch")
    else:
        check(report["result"]["fit_summary"] is None and report["result"]["model_evaluation"] is None,"Quality diagnostics exposed")
    status, raw = browser.request(f'/api/v2/research-versions/{draft["id"]}')
    check(status==200 and json.loads(raw)==draft,"Inspection changed immutable draft")
    return {"format":format_name,"quality":expected,"inspection_id":report["id"],"report_hash":identity_hash(report),"research_version_id":draft["id"],"model":model}


class Command(BaseCommand):
    help = "Verify three actual INGEST/draft formats, known formula inspection and final masking"

    def handle(self,*args: Any,**options: Any) -> None:
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="inspection-"+uuid4().hex,password=password)
        actor = Account.objects.create(user=user,tenant=Tenant.objects.create(name="inspection-synthetic"))
        browser = Browser()
        browser.login(user.get_username(),password)
        status,dataset = browser.post('/api/v2/datasets',{"name":"three-format-inspection"})
        check(status==201,"Dataset unavailable")
        rows = [(i,100*(2*i+1)) for i in range(10)]
        csv = ('觀測值,量測值\n'+''.join(f'{x},{y}\n' for x,y in rows)).encode()
        records = json.dumps([{"觀測值":x,"量測值":y} for x,y in rows]).encode()
        buffer = BytesIO()
        pl.DataFrame({"觀測值":[row[0] for row in rows],"量測值":[row[1] for row in rows]}).write_parquet(buffer)
        results = [inspect_version(browser,actor,dataset["id"],content,name,"PASS") for name,content in (("CSV",csv),("JSON",records),("PARQUET",buffer.getvalue()))]
        invalid = ('觀測值,量測值\n'+''.join(f'{x},{y if x<9 else "private-final-marker"}\n' for x,y in rows)).encode()
        masked = inspect_version(browser,actor,dataset["id"],invalid,"CSV","BLOCKED")
        check("private-final-marker" not in json.dumps(masked),"Raw value exposed")
        for result in [*results,masked]: result.pop("model")
        self.stdout.write(json.dumps({"scope":"T07_LOCAL_RESEARCH_INSPECTION","status":"PASS","results":results,"masked":masked,"final_evaluation":"NOT_RUN","profile_run":"NOT_EXECUTED_BY_CLI","research_status":"DRAFT","product_gate_status":"NOT_RUN"},indent=2))
