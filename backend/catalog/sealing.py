"""PROFILE 的正式封存接入：品質 PASS 後才由專用 child 固定 final 觀測並登記。

只有可信 PROFILE 程序載入 Evaluator 私有 volume 與 journal 憑證；web／frontend 均不載入。
"""
from uuid import UUID
from django.conf import settings
from catalog.models import Account, ProfileBinding, SealRegistration
from ingestion.limits import ImportLimits, ImportRejected
from runtime.models import RuntimeRun
from sealing.prepare import register_payload
from sealing.rpc import JournalClient
from sealing.types import Attestation, SealRejected
from sealing.vault import Vault


def authority() -> Vault:
    """每次操作取得目前 journal 水位；缺憑證、截短或 epoch 不符一律封閉失敗。"""
    return Vault(settings.SEALING_DATA,settings.SEALING_KEYS,JournalClient(settings.JOURNAL_SOCKET,settings.JOURNAL_TOKEN))


def attach(content: bytes, format_name: str, limits: ImportLimits, config: object) -> tuple[Attestation | None, str]:
    """成功回不透明登記；失敗只回遮罩代碼，呼叫端不得因此投影 READY 或消耗曝光。"""
    try:
        return Attestation.read(register_payload(authority(),content,format_name,limits,config)),""
    except (SealRejected,ImportRejected) as error:
        return None,error.code


def registration(actor: Account, binding: ProfileBinding, run: RuntimeRun, attestation: Attestation) -> SealRegistration:
    """公開 DB 只存不含 tokens／labels 的登記；私有 tokens 與 final 檔留在 Evaluator 域。"""
    return SealRegistration.objects.create(tenant_id=actor.tenant_id,research_version=binding.research_version,run=run,
        sealed_test_id=UUID(attestation.sealed_test_id),source_sha256=attestation.source_sha256,protocol_hash=attestation.protocol_hash,
        authority_epoch=UUID(attestation.authority_epoch),authority_sequence=attestation.authority_sequence,attestation_hash=attestation.attestation_hash)
