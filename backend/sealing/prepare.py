"""固定封存擷取：只有 private child 處理觀測，普通報告與 stdout 不包含 final 值。"""
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence
from uuid import uuid4
from ingestion.limits import ImportLimits
from ingestion.parser import parse
from ingestion.research import scalar
from ingestion.dependencies import group_token, time_value
from ingestion.supervisor import run_sealing_worker
from runtime.budget_types import integer, object_fields
from runtime.contracts import canonical_bytes, identity_hash
from sealing.types import SealRejected, sequence, text
from sealing.vault import Vault

MAX_FINAL = 512


@dataclass(frozen=True)
class MappingRule:
    """將來源數值精確轉 canonical SI；欄名／來源單位不進 CONTENT 指紋。"""
    column: str
    scale: Fraction
    offset: Fraction
    unit: list[int]

    @classmethod
    def read(cls, value: object) -> "MappingRule":
        """未知 JSON 先逐欄檢查，不能直接將容器 cast 成語意模型。"""
        row = object_fields(value)
        conversion = object_fields(row['conversion'])
        units = sequence(row['unit'])
        if len(units)!=7 or any(type(item) is not int for item in units):
            raise SealRejected('INVALID_SCHEMA')
        dimensions = [int(text(str(item))) for item in units]
        return cls(text(row['source_column']),Fraction(text(conversion['scale'])),Fraction(text(conversion['offset'])),dimensions)

    def normalized(self, value: object) -> str:
        """有理數保留完整分子／分母；cm→m、攝氏→K 不因格式改變取得新資格。"""
        result = scalar(value)*self.scale+self.offset
        return f'{result.numerator}/{result.denominator}'


def private_payload(path: Path, format_name: str, limits: ImportLimits, config: dict[str,object]) -> bytes:
    """固定 child 執行：只保留 final 原順序，不洩露 labels 到公開報告。"""
    research = object_fields(config['research'])
    split = object_fields(research['observation_split'])
    indices = [integer(value) for value in sequence(split['final_test'])]
    if not 1<=len(indices)<=MAX_FINAL or len(set(indices))!=len(indices):
        raise SealRejected('IMPORT_LIMIT_EXCEEDED')
    profile = object_fields(research['semantic_profile'])
    source = MappingRule.read(sequence(profile['inputs'])[0])
    target = MappingRule.read(profile['target'])
    selected: dict[int,dict[str,object]] = {}
    wanted = set(indices)
    def observe(index: int, names: list[str], values: Sequence[object]) -> None:
        """每筆原觀測使用固定角色／SI 量綱；不將 row ID 加入 CONTENT payload。"""
        if index in wanted:
            time_column, group_column = split["time_column"], profile["group_column"]
            timestamp = None if time_column is None else str(time_value(values[names.index(text(time_column))]))
            group = None if group_column is None else group_token(values[names.index(text(group_column))])
            selected[index] = {'inputs':[source.normalized(values[names.index(source.column)])], 'target':target.normalized(values[names.index(target.column)]),
                'input_unit':source.unit,'target_unit':target.unit,'time':timestamp,'group':group}
    metadata = parse(path,format_name,limits,observe,exact_json=True)
    if metadata!=config['metadata'] or set(selected)!=wanted:
        raise SealRejected('INVALID_SCHEMA')
    return canonical_bytes({'rows':[{'row_id':index,'observation':selected[index]} for index in indices]})


def extract(content: bytes, format_name: str, limits: ImportLimits, config: object) -> bytes:
    """同既有 supervisor 施加 CPU／AS／wall／stdout 限制；labels 僅走 private 暫存檔。"""
    with TemporaryDirectory(prefix='axiom-seal-') as temporary:
        directory = Path(temporary)
        for name,data in [('input',content),('request',canonical_bytes(config))]:
            path = directory/name
            path.write_bytes(data)
            path.chmod(0o400)
        raw = object_fields(json.loads(run_sealing_worker(directory,format_name,limits)))
        if raw.get('status')!='PASS' or set(raw)!={'status','sha256','size_bytes'}:
            raise SealRejected('DEPENDENCY_UNAVAILABLE')
        result = (directory/'sealed_payload').read_bytes()
        if len(result)>524288 or len(result)!=integer(raw['size_bytes']) or hashlib.sha256(result).hexdigest()!=raw['sha256']:
            raise SealRejected('DEPENDENCY_UNAVAILABLE')
        return result


def register_payload(vault: Vault, content: bytes, format_name: str, limits: ImportLimits, config: object) -> dict[str,object]:
    """可信 worker 以固定快照擷取並登記；原始／token 不進 app DB 或普通 HTTP。"""
    fields = object_fields(config)
    research = object_fields(fields['research'])
    split = object_fields(research['observation_split'])
    tenant = text(research['tenant_id'])
    if hashlib.sha256(content).hexdigest()!=fields['source_sha256']:
        raise SealRejected('UPLOAD_OBJECT_CHANGED')
    final_bytes = extract(content,format_name,limits,config)
    rows = sequence(object_fields(json.loads(final_bytes))['rows'])
    contents,lineages = set[str](),set[str]()
    for value in rows:
        row = object_fields(value)
        contents.add(vault.token(tenant,'CONTENT',row['observation']))
        lineages.add(vault.token(tenant,'LINEAGE',['LOCAL_UNTRUSTED_SOURCE',fields['source_sha256'],row['row_id']]))
    document: dict[str,object] = {'kind':'SealedTest','id':str(uuid4()),'tenant_id':tenant,'schema_version':'2.0','created_at':research['created_at'],
        'dataset_version_id':research['dataset_version_id'],'observation_split_id':split['id'],'benchmark_partition_id':None,'benchmark_case_id':None,
        'source_content_sha256':fields['source_sha256'],'final_rows_hash':identity_hash(split['final_test']),
        'protocol_hash':identity_hash({'semantic_profile':research['semantic_profile'],'evaluation_policy':research['evaluation_policy']}),'state':'AVAILABLE','submission_id':None,
        'final_observation_tokens':sorted(contents),'final_lineage_tokens':sorted(lineages),'exposure_fingerprint_version':'1.0'}
    return vault.register(document,final_bytes).document()
