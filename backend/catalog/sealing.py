"""catalog 對正式封存的唯一接入：PROFILE 登記與最終評估的預留／消耗／退役。

只有可信 PROFILE／Evaluator 程序載入私有 volume 與 journal 憑證；web／frontend 均不載入，
故這裡的每個函式都只能由持有該憑證的協調器呼叫，缺憑證一律封閉失敗。
"""
from uuid import UUID
from django.conf import settings
from catalog.models import Account, FrozenSubmission, ProfileBinding, SealRegistration
from catalog.validation import ApiError
from ingestion.limits import ImportLimits, ImportRejected
from runtime.models import RuntimeRun
from sealing.prepare import register_payload
from sealing.rpc import JournalClient
from sealing.types import Attestation, SealRejected
from sealing.vault import Vault

MASKED_STATUS = {"NOT_FOUND": 404}


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


def _transition(action: str, submission: FrozenSubmission) -> str:
    """把遮罩代碼轉成穩定 API 代碼；未登記狀態碼一律 409，不以 503 誤報可重試。

    退役不帶提交身分：`RETIRE` 只需保守關閉曝光，不應覆寫既有綁定。其餘動作以凍結提交與其
    `snapshot_hash` 呼叫原語，故同一提交重播讀回現狀，別的提交或別的快照一律拒絕。"""
    identity,tenant = str(submission.sealed_test_id),str(submission.tenant_id)
    selected,snapshot = (str(submission.id),submission.snapshot_hash) if action!="RETIRE" else (None,None)
    try:
        return authority().transition(tenant,identity,action,selected,snapshot)
    except SealRejected as error:
        raise ApiError(error.code,MASKED_STATUS.get(error.code,409)) from error


def reserve(submission: FrozenSubmission) -> str:
    """派送最終評估時把封存包綁到唯一提交；已消耗的封存不再重新取得資格。"""
    return _transition("RESERVE",submission)


def consume(submission: FrozenSubmission) -> str:
    """結果落庫前先消耗曝光資格；崩潰後維持 CONSUMED，不為其他提交重新開放。"""
    return _transition("CONSUME",submission)


def retire(submission: FrozenSubmission) -> str:
    """尚未讀取即永久失敗或取消時保守退役；不回 AVAILABLE，既有結果仍留帳本。"""
    return _transition("RETIRE",submission)
