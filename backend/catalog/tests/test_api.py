"""Real PostgreSQL, cookie/CSRF and private filesystem authorization tests."""
from collections.abc import Callable
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import connection, IntegrityError, transaction
from typing import Protocol
from django.test import Client, TestCase
from runtime.contracts import JsonObject
from runtime.records import db_now
from catalog.models import Account, Audit, Dataset, Grant, LoginThrottle, Provenance, StoredObject, Tenant, Upload
from catalog.services import actor_for, create_dataset, set_grant
from catalog.storage import LocalVersionStore, ObjectRef
from catalog.validation import validate_api

PASSWORD = secrets.token_urlsafe(24)
PASSWORD_HASH = make_password(PASSWORD)
CONTENT = b"x,y\n1,3\n2,5\n"
CHECKSUM = hashlib.sha256(CONTENT).hexdigest()


class ResponseBody(Protocol):
    @property
    def content(self) -> bytes: ...
    @property
    def status_code(self) -> int: ...


def document(response: ResponseBody) -> JsonObject:
    value: JsonObject = json.loads(response.content)
    return value


def enforce(action: Callable[[], object]) -> None:
    with transaction.atomic():
        action()
        connection.check_constraints()


class CatalogTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(self.directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(name="A")
        self.other_tenant = Tenant.objects.create(name="B")
        self.owner = self.account(self.tenant, "RESEARCHER")
        self.other = self.account(self.other_tenant, "RESEARCHER")
        self.reader = self.account(self.tenant, "VIEWER")
        self.admin = self.account(self.tenant, "ADMIN")
        with transaction.atomic():
            self.dataset = UUID(create_dataset(actor_for(self.owner.user_id), {"name": "公開合成資料"})["id"])
        self.client = self.as_actor(self.owner)

    def account(self, tenant: Tenant, role: str) -> Account:
        user = User.objects.create(username=uuid4().hex, password=PASSWORD_HASH)
        return Account.objects.create(user=user, tenant=tenant, role=role)

    def as_actor(self, actor: Account) -> Client:
        client = Client(enforce_csrf_checks=True)
        client.force_login(actor.user)
        client.get("/auth/login")
        return client

    def headers(self, client: Client | None = None, key: str = "key") -> dict[str, str]:
        client = client or self.client
        return {"X-CSRFToken": client.cookies[settings.CSRF_COOKIE_NAME].value, "Idempotency-Key": key}

    def post(self, path: str, data: JsonObject, client: Client | None = None, key: str = "key") -> ResponseBody:
        client = client or self.client
        return client.post(path, data=json.dumps(data), content_type="application/json", headers=self.headers(client, key))

    def upload(self, client: Client | None = None, key: str = "upload") -> JsonObject:
        response = self.post(f"/api/v2/datasets/{self.dataset}/uploads", {"filename": "../../private.csv", "format": "CSV", "size_bytes": len(CONTENT), "sha256": CHECKSUM}, client, key)
        self.assertEqual(response.status_code, 201)
        result = document(response)
        validate_api(result, "UploadSession")
        return result

    def put(self, upload: JsonObject, data: bytes = CONTENT, client: Client | None = None) -> ResponseBody:
        client = client or self.client
        headers = self.headers(client) | upload["required_headers"]
        return client.put("/storage/uploads/" + upload["id"], data=data, content_type="application/octet-stream", headers=headers)

    def test_authentication_and_csrf_are_required(self) -> None:
        anonymous = Client()
        response = anonymous.get("/api/v2/datasets")
        self.assertEqual(response.status_code, 401)
        validate_api(document(response), "Error")
        response = self.client.post("/api/v2/datasets", data='{"name":"x"}', content_type="application/json")
        self.assertEqual((response.status_code, document(response)["code"]), (403, "CSRF_FAILED"))

    def test_login_rotates_session_and_logout_requires_post(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.get("/auth/login")
        session = client.session
        session["before_login"] = True
        session.save()
        previous = session.session_key
        response = client.post("/auth/login", {"username": self.owner.user.get_username(), "password": PASSWORD}, headers=self.headers(client))
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(client.session.session_key, previous)
        self.assertEqual(client.get("/auth/logout").status_code, 405)
        self.assertEqual(client.post("/auth/logout", headers=self.headers(client)).status_code, 200)
        self.assertEqual(client.get("/api/v2/datasets").status_code, 401)
        self.assertTrue(Audit.objects.filter(action="LOGOUT", actor_id=self.owner.id).exists())

    def test_login_failure_is_generic_and_persistently_throttled(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.get("/auth/login")
        data = {"username": self.owner.user.get_username(), "password": secrets.token_urlsafe(16)}
        for _ in range(5):
            response = client.post("/auth/login", data, headers=self.headers(client))
            self.assertEqual(response.status_code, 401)
        response = client.post("/auth/login", {"username": self.owner.user.get_username(), "password": PASSWORD}, headers=self.headers(client))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(LoginThrottle.objects.get().failures, 5)
        self.assertNotIn(self.owner.user.get_username().encode(), response.content)

    def test_dataset_creation_replay_and_conflict(self) -> None:
        first = self.post("/api/v2/datasets", {"name": "new"})
        replay = self.post("/api/v2/datasets", {"name": "new"})
        conflict = self.post("/api/v2/datasets", {"name": "changed"})
        self.assertEqual((first.status_code, replay.status_code, conflict.status_code), (201, 201, 409))
        self.assertEqual(document(first), document(replay))
        self.assertEqual(Dataset.objects.count(), 2)
        validate_api(document(first), "Dataset")

    def test_missing_idempotency_key_and_unknown_fields_rejected(self) -> None:
        response = self.client.post("/api/v2/datasets", data='{"name":"new"}', content_type="application/json", headers={"X-CSRFToken": self.client.cookies[settings.CSRF_COOKIE_NAME].value})
        self.assertEqual(response.status_code, 422)
        response = self.post("/api/v2/datasets", {"name": "new", "tenant_id": str(self.other_tenant.id)})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(Dataset.objects.count(), 1)

    def test_strict_json_rejects_duplicate_nonfinite_surrogate_and_depth(self) -> None:
        inputs = [b'{"name":"a","name":"b"}', b'{"name":NaN}', b'{"name":1e400}', b'{"name":"\\ud800"}', b'[' * 33 + b'0' + b']' * 33]
        for raw in inputs:
            with self.subTest(raw=raw[:50]):
                response = self.client.post("/api/v2/datasets", data=raw, content_type="application/json", headers=self.headers())
                self.assertEqual(document(response)["code"], "INVALID_JSON")
        self.assertEqual(Dataset.objects.count(), 1)

    def test_cross_tenant_and_hidden_same_tenant_ids_return_404(self) -> None:
        for actor in [self.other, self.admin]:
            client = self.as_actor(actor)
            response = self.post(f"/api/v2/datasets/{self.dataset}/uploads", {}, client)
            self.assertEqual((response.status_code, document(response)["code"]), (404, "NOT_FOUND"))
            page = document(client.get("/api/v2/datasets"))
            self.assertEqual(page["items"], [])

    def test_viewer_cannot_create_or_upload(self) -> None:
        set_grant(self.admin.id, self.reader.id, self.dataset, "READER")
        client = self.as_actor(self.reader)
        self.assertEqual(self.post("/api/v2/datasets", {"name": "no"}, client).status_code, 403)
        self.assertEqual(self.post(f"/api/v2/datasets/{self.dataset}/uploads", {}, client).status_code, 403)
        self.assertEqual(len(document(client.get("/api/v2/datasets"))["items"]), 1)

    def test_headers_cannot_select_tenant_or_role(self) -> None:
        headers = self.headers() | {"X-Tenant-ID": str(self.other_tenant.id), "X-Role": "ADMIN"}
        response = self.client.get("/api/v2/datasets", headers=headers)
        self.assertEqual(document(response)["items"][0]["tenant_id"], str(self.tenant.id))

    def test_disabled_account_cannot_replay(self) -> None:
        self.post("/api/v2/datasets", {"name": "new"})
        Account.objects.filter(pk=self.owner.id).update(enabled=False)
        self.assertEqual(self.post("/api/v2/datasets", {"name": "new"}).status_code, 403)
        self.assertTrue(Audit.objects.filter(action="API_DENY", actor_id=self.owner.id, code="FORBIDDEN").exists())

    def test_revocation_blocks_cached_response_and_put(self) -> None:
        upload = self.upload()
        set_grant(self.admin.id, self.owner.id, self.dataset, None)
        response = self.post(f"/api/v2/datasets/{self.dataset}/uploads", {"filename": "../../private.csv", "format": "CSV", "size_bytes": len(CONTENT), "sha256": CHECKSUM}, key="upload")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.put(upload).status_code, 404)
        self.assertEqual(StoredObject.objects.count(), 0)

    def test_upload_is_private_versioned_and_idempotent(self) -> None:
        upload = self.upload()
        self.assertEqual(self.put(upload).status_code, 204)
        first = StoredObject.objects.get()
        self.assertEqual(self.put(upload).status_code, 204)
        self.assertEqual(StoredObject.objects.get().id, first.id)
        self.assertEqual(Upload.objects.get().status, "OPEN")
        self.assertEqual(Upload.objects.get().object_version, first.id)
        files = list(Path(self.directory.name).iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o440)
        self.assertNotIn("private.csv", files[0].name)
        self.assertNotIn("?", upload["put_url"])
        self.assertEqual(self.client.get("/storage/uploads/" + upload["id"]).status_code, 405)

    def test_wrong_checksum_or_size_does_not_register_object(self) -> None:
        upload = self.upload()
        response = self.put(upload, b"z" * len(CONTENT))
        self.assertEqual((response.status_code, document(response)["code"]), (422, "CHECKSUM_MISMATCH"))
        self.assertEqual(self.put(upload, CONTENT + b"x").status_code, 413)
        self.assertEqual(StoredObject.objects.count(), 0)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_late_changed_put_is_rejected(self) -> None:
        upload = self.upload()
        self.put(upload)
        response = self.put(upload, b"z" * len(CONTENT))
        self.assertEqual((response.status_code, document(response)["code"]), (409, "UPLOAD_OBJECT_CHANGED"))
        self.assertEqual(StoredObject.objects.count(), 1)

    def test_token_cannot_move_between_actors_or_uploads(self) -> None:
        upload = self.upload()
        editor = self.account(self.tenant, "RESEARCHER")
        set_grant(self.admin.id, editor.id, self.dataset, "EDITOR")
        self.assertEqual(self.put(upload, client=self.as_actor(editor)).status_code, 403)
        another = self.upload(key="another")
        another["required_headers"] = upload["required_headers"]
        self.assertEqual(self.put(another).status_code, 403)
        upload["required_headers"]["X-Upload-Token"] += "tampered"
        self.assertEqual(self.put(upload).status_code, 403)

    def test_expired_upload_rejected_even_with_valid_signature(self) -> None:
        upload = self.upload()
        future = db_now() + timedelta(minutes=16)
        with patch("catalog.services.db_now", return_value=future):
            response = self.put(upload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(StoredObject.objects.count(), 0)

    def test_transmission_limits_have_stable_error_codes(self) -> None:
        path = f"/api/v2/datasets/{self.dataset}/uploads"
        data: JsonObject = {"filename": "test.csv", "format": "CSV", "size_bytes": 52428801, "sha256": CHECKSUM}
        response = self.post(path, data)
        self.assertEqual((response.status_code, document(response)["code"]), (413, "UPLOAD_TOO_LARGE"))
        data.update(format="EXECUTABLE", size_bytes=len(CONTENT))
        response = self.post(path, data)
        self.assertEqual((response.status_code, document(response)["code"]), (415, "UNSUPPORTED_MEDIA_TYPE"))

    def test_role_downgrade_overrides_existing_editor_grant(self) -> None:
        upload = self.upload()
        Account.objects.filter(pk=self.owner.id).update(role="VIEWER")
        self.assertEqual(self.put(upload).status_code, 403)
        self.assertEqual(StoredObject.objects.count(), 0)

    def test_complete_never_fabricates_ingest(self) -> None:
        upload = self.upload()
        self.put(upload)
        with self.settings(INGEST_ENABLED=False):
            response = self.post("/api/v2/uploads/" + upload["id"] + "/complete", {"checksum": CHECKSUM})
        self.assertEqual((response.status_code, document(response)["code"]), (503, "DEPENDENCY_UNAVAILABLE"))
        self.assertIsNone(Upload.objects.get().ingest_run_id)
        self.assertEqual(Upload.objects.get().status, "OPEN")

    def test_complete_detects_replaced_object(self) -> None:
        upload = self.upload()
        self.put(upload)
        stored = StoredObject.objects.get()
        path = LocalVersionStore(Path(self.directory.name)).path(ObjectRef(self.tenant.id, UUID(upload["id"]), stored.id, stored.sha256, stored.size_bytes))
        path.chmod(0o600)
        path.write_bytes(b"z" * len(CONTENT))
        response = self.post("/api/v2/uploads/" + upload["id"] + "/complete", {"checksum": CHECKSUM})
        self.assertEqual((response.status_code, document(response)["code"]), (409, "UPLOAD_OBJECT_CHANGED"))

    def test_cursor_is_scoped_and_rechecks_current_acl(self) -> None:
        self.post("/api/v2/datasets", {"name": "new"})
        page = document(self.client.get("/api/v2/datasets?limit=1"))
        self.assertIsNotNone(page["next_cursor"])
        other = self.as_actor(self.other)
        response = other.get("/api/v2/datasets", {"cursor": page["next_cursor"], "limit": 1})
        self.assertEqual((response.status_code, document(response)["code"]), (400, "INVALID_CURSOR"))
        set_grant(self.admin.id, self.owner.id, self.dataset, None)
        response = self.client.get("/api/v2/datasets", {"cursor": page["next_cursor"], "limit": 1})
        self.assertEqual(document(response)["items"], [])

    def test_database_blocks_cross_tenant_grant_and_upload(self) -> None:
        row = Dataset.objects.get(pk=self.dataset)
        with self.assertRaises(IntegrityError):
            enforce(lambda: Grant.objects.create(actor=self.other, dataset=row, tenant=self.tenant, permission="EDITOR"))
        with self.assertRaises(IntegrityError):
            enforce(lambda: Upload.objects.create(tenant=self.other_tenant, dataset=row, actor=self.other, filename="x", format="CSV", size_bytes=1, sha256="0" * 64, expires_at=db_now() + timedelta(minutes=15)))

    def test_database_protects_provenance_and_actor_identity(self) -> None:
        rows = Provenance.objects.all()
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.update(resource_type="changed"))
        actors = Account.objects.filter(pk=self.owner.id)
        with self.assertRaises(IntegrityError):
            enforce(lambda: actors.update(tenant=self.other_tenant))
        self.assertTrue(Provenance.objects.exists())

    def test_database_protects_stored_version_and_metadata(self) -> None:
        upload = self.upload()
        self.put(upload)
        objects = StoredObject.objects.all()
        with self.assertRaises(IntegrityError):
            enforce(lambda: objects.update(sha256="f" * 64))
        uploads = Upload.objects.all()
        version = uuid4()
        with self.assertRaises(IntegrityError):
            enforce(lambda: uploads.update(object_version=version))

    def test_method_and_unknown_route_errors_use_contract_envelope(self) -> None:
        response = self.client.get("/auth/logout")
        self.assertEqual((response.status_code, document(response)["code"]), (405, "METHOD_NOT_ALLOWED"))
        validate_api(document(response), "Error")
        response = self.client.get("/api/v2/unknown")
        self.assertEqual((response.status_code, document(response)["code"]), (404, "NOT_FOUND"))
        validate_api(document(response), "Error")

    def test_unexpected_error_hides_private_details(self) -> None:
        client = self.as_actor(self.owner)
        client.raise_request_exception = False
        with patch("catalog.http.list_datasets", side_effect=RuntimeError("private marker")):
            response = client.get("/api/v2/datasets")
        self.assertEqual((response.status_code, document(response)["code"]), (500, "INTERNAL_ERROR"))
        self.assertNotIn(b"private marker", response.content)
        validate_api(document(response), "Error")

    def test_audit_contains_no_password_token_or_content(self) -> None:
        upload = self.upload()
        self.put(upload)
        text = str(list(Audit.objects.values()))
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn(upload["required_headers"]["X-Upload-Token"], text)
        self.assertNotIn(CONTENT.decode(), text)

    def test_storage_failure_keeps_upload_open(self) -> None:
        upload = self.upload()
        with patch("catalog.services.LocalVersionStore.create", side_effect=OSError("private root")):
            response = self.put(upload)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"private root", response.content)
        self.assertEqual(StoredObject.objects.count(), 0)
        self.assertIsNone(Upload.objects.get().object_version)
