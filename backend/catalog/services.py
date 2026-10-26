"""租戶業務邊界：每次讀寫重驗租戶分區；物件固定版本後不可覆寫。
冪等回放仍重驗租戶歸屬；資源被刪除或隔離後一律 404。

Authenticated catalog operations; callers hold the current actor row lock."""
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from django.conf import settings
from django.core import signing
from django.db.models import Q, QuerySet
from runtime.contracts import JsonObject, identity_hash, validate
from runtime.records import db_now
from catalog.models import Account, Audit, Dataset, IdempotentResult, Provenance, StoredObject, Upload
from catalog.storage import LocalVersionStore, ObjectRef, StorageRejected, Readable
from catalog.validation import ApiError, validate_api


def actor_for(user_id: int) -> Account:
    actor = Account.objects.select_for_update().filter(user_id=user_id, enabled=True).first()
    if actor is None:
        raise ApiError("FORBIDDEN", 403)
    return actor


def dataset_for(actor: Account, identity: UUID) -> Dataset:
    row = Dataset.objects.select_for_update().filter(pk=identity, tenant_id=actor.tenant_id).first()
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    return row


def dataset_dto(row: Dataset) -> JsonObject:
    value: JsonObject = {"kind": "Dataset", "id": str(row.id), "tenant_id": str(row.tenant_id), "schema_version": "2.0", "created_at": row.created_at.isoformat(), "name": row.name, "owner_id": str(row.owner_id)}
    validate(value, "research-v2.schema.json", "Dataset")
    return value


def provenance(actor: Account, resource_type: str, resource_id: UUID, identity: UUID, source: Provenance | None = None) -> None:
    responsible = {str(actor.id)}
    if source is not None:
        responsible.update(source.document["responsible_human_ids"])
    document: JsonObject = {
        "kind": "ResourceProvenance", "id": str(identity), "tenant_id": str(actor.tenant_id), "schema_version": "2.0", "created_at": db_now().isoformat(),
        "resource_type": resource_type, "resource_id": str(resource_id), "creator_actor_id": str(actor.id), "responsible_human_ids": sorted(responsible),
        "root_provenance_id": None if source is None else str(source.id), "source_provenance_ids": [] if source is None else [str(source.id)],
    }
    validate(document, "runtime-v2.schema.json", "ResourceProvenance")
    Provenance.objects.create(id=identity, tenant_id=actor.tenant_id, resource_type=resource_type, resource_id=resource_id, document=document)


def create_dataset(actor: Account, data: JsonObject) -> JsonObject:
    identity, source = uuid4(), uuid4()
    provenance(actor, "Dataset", identity, source)
    row = Dataset.objects.create(id=identity, tenant_id=actor.tenant_id, owner=actor, name=data["name"], provenance_id=source)
    Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="CREATE_DATASET", code="OK")
    return dataset_dto(row)


def require_key(key: str) -> None:
    if not key or len(key) > 128 or any(ord(character) < 32 or ord(character) > 126 for character in key):
        raise ApiError("INVALID_SCHEMA", 422)


def replay(actor: Account, path: str, key: str, data: JsonObject, action: Callable[[], JsonObject], authorize_cached: Callable[[JsonObject], None]) -> JsonObject:
    require_key(key)
    scope = identity_hash(["POST", path, key])
    digest = identity_hash(data)
    previous = IdempotentResult.objects.filter(actor=actor, scope=scope).first()
    now = db_now()
    if previous is not None and previous.expires_at > now:
        if previous.request_hash != digest:
            raise ApiError("IDEMPOTENCY_CONFLICT", 409)
        authorize_cached(previous.response)
        return previous.response
    response = action()
    IdempotentResult.objects.update_or_create(actor=actor, scope=scope, defaults={"request_hash": digest, "response": response, "expires_at": now + timedelta(hours=24)})
    return response


def upload_record(row: Upload) -> JsonObject:
    result: JsonObject = {
        "kind": "UploadRecord", "id": str(row.id), "tenant_id": str(row.tenant_id), "schema_version": "2.0", "created_at": row.created_at.isoformat(),
        "dataset_id": str(row.dataset_id), "expected_sha256": row.sha256, "object_key": f"uploads/{row.tenant_id}/{row.id}",
        "object_version": None if row.object_version is None else str(row.object_version), "status": row.status,
        "ingest_run_id": None if row.ingest_run_id is None else str(row.ingest_run_id), "expires_at": row.expires_at.isoformat(),
    }
    validate(result, "runtime-v2.schema.json", "UploadRecord")
    return result


def upload_session(row: Upload, origin: str) -> JsonObject:
    upload_record(row)
    token = signing.dumps({"actor": str(row.actor_id), "tenant": str(row.tenant_id), "upload": str(row.id), "sha256": row.sha256, "size": row.size_bytes, "expires": row.expires_at.isoformat()}, salt="axiom-upload-v1")
    result: JsonObject = {"id": str(row.id), "dataset_id": str(row.dataset_id), "put_url": origin + "/storage/uploads/" + str(row.id), "expires_at": row.expires_at.isoformat(), "required_headers": {"X-Upload-Token": token, "Content-Type": "application/octet-stream"}}
    validate_api(result, "UploadSession")
    return result


def create_upload(actor: Account, dataset: Dataset, data: JsonObject, origin: str) -> JsonObject:
    row = Upload.objects.create(tenant_id=actor.tenant_id, dataset=dataset, actor=actor, filename=data["filename"], format=data["format"], size_bytes=data["size_bytes"], sha256=data["sha256"], expires_at=db_now() + timedelta(minutes=15))
    Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="CREATE_UPLOAD", code="OK")
    return upload_session(row, origin)


def upload_for(actor: Account, identity: UUID) -> Upload:
    candidate = Upload.objects.filter(pk=identity, tenant_id=actor.tenant_id).first()
    if candidate is None:
        raise ApiError("NOT_FOUND", 404)
    dataset_for(actor, candidate.dataset_id)
    return Upload.objects.select_for_update().get(pk=identity, tenant_id=actor.tenant_id)


def verify_capability(actor: Account, row: Upload, token: str) -> None:
    try:
        supplied: JsonObject = signing.loads(token, salt="axiom-upload-v1", max_age=900)
    except signing.BadSignature as error:
        raise ApiError("FORBIDDEN", 403) from error
    expected: JsonObject = {"actor": str(actor.id), "tenant": str(actor.tenant_id), "upload": str(row.id), "sha256": row.sha256, "size": row.size_bytes, "expires": row.expires_at.isoformat()}
    if supplied != expected:
        raise ApiError("FORBIDDEN", 403)
    if row.expires_at <= db_now() or row.status != "OPEN":
        raise ApiError("INVALID_TRANSITION", 409)


def put_upload(actor: Account, row: Upload, token: str, source: Readable) -> None:
    verify_capability(actor, row, token)
    version = row.object_version or uuid4()
    reference = ObjectRef(actor.tenant_id, row.id, version, row.sha256, row.size_bytes)
    store = LocalVersionStore(settings.OBJECT_ROOT)
    try:
        store.create(reference, source)
    except StorageRejected as error:
        code = "UPLOAD_OBJECT_CHANGED" if row.object_version is not None else error.code
        status = {"CHECKSUM_MISMATCH": 422, "UPLOAD_TOO_LARGE": 413, "UPLOAD_OBJECT_CHANGED": 409}[code]
        raise ApiError(code, status) from error
    if row.object_version is None:
        source_provenance = Provenance.objects.get(pk=row.dataset.provenance_id, tenant_id=actor.tenant_id)
        provenance_id = uuid4()
        provenance(actor, "StoredObject", version, provenance_id, source_provenance)
        StoredObject.objects.create(id=version, tenant_id=actor.tenant_id, dataset_id=row.dataset_id, upload=row, sha256=row.sha256, size_bytes=row.size_bytes, provenance_id=provenance_id)
        row.object_version = version
        row.save(update_fields=["object_version"])
    upload_record(row)
    Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="PUT_UPLOAD", code="OK")


def verify_staged(actor: Account, upload_id: UUID) -> ObjectRef:
    row = upload_for(actor, upload_id)
    if row.object_version is None:
        raise ApiError("INVALID_TRANSITION", 409)
    stored = StoredObject.objects.get(pk=row.object_version, tenant_id=actor.tenant_id, upload=row)
    reference = ObjectRef(actor.tenant_id, row.id, stored.id, stored.sha256, stored.size_bytes)
    try:
        LocalVersionStore(settings.OBJECT_ROOT).verify(reference)
    except StorageRejected as error:
        raise ApiError("UPLOAD_OBJECT_CHANGED", 409) from error
    return reference


def list_datasets(actor: Account, cursor: str, limit: int) -> JsonObject:
    rows: QuerySet[Dataset] = Dataset.objects.filter(tenant_id=actor.tenant_id).order_by("-created_at", "-id")
    if cursor:
        rows = _after_cursor(rows, actor, cursor)
    page = list(rows[:limit + 1])
    next_cursor = None
    if len(page) > limit:
        last = page[limit - 1]
        next_cursor = signing.dumps({"actor": str(actor.id), "tenant": str(actor.tenant_id), "sort": "created-id-desc-v1", "created": last.created_at.isoformat(), "id": str(last.id)}, salt="axiom-dataset-page-v1")
    return {"items": [dataset_dto(row) for row in page[:limit]], "next_cursor": next_cursor}


def _after_cursor(rows: QuerySet[Dataset], actor: Account, cursor: str) -> QuerySet[Dataset]:
    try:
        value: JsonObject = signing.loads(cursor, salt="axiom-dataset-page-v1", max_age=900)
        if value["actor"] != str(actor.id) or value["tenant"] != str(actor.tenant_id) or value["sort"] != "created-id-desc-v1":
            raise ValueError("Cursor scope mismatch")
        created, identity = datetime.fromisoformat(value["created"]), UUID(value["id"])
        return rows.filter(Q(created_at__lt=created) | Q(created_at=created, id__lt=identity))
    except (signing.BadSignature, ValueError, KeyError, TypeError) as error:
        raise ApiError("INVALID_CURSOR", 400) from error
