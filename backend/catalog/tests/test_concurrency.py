"""Real transaction races for idempotency and immutable upload versions."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import connections, transaction
from django.test import TransactionTestCase
from runtime.contracts import JsonObject
from catalog.models import Account, Dataset, IdempotentResult, StoredObject, Tenant, Upload
from catalog.services import actor_for, create_dataset, create_upload, dataset_for, put_upload, replay, upload_for


class ConcurrencyTests(TransactionTestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = self.settings(OBJECT_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        tenant = Tenant.objects.create(name="concurrency")
        user = User.objects.create_user(username=uuid4().hex)
        self.actor = Account.objects.create(user=user, tenant=tenant)

    def test_same_key_parallel_creation_has_one_resource(self) -> None:
        def create(_index: int) -> str:
            try:
                with transaction.atomic():
                    actor = actor_for(self.actor.user_id)
                    data: JsonObject = {"name": "same"}
                    def authorize(previous: JsonObject) -> None:
                        dataset_for(actor, UUID(previous["id"]))
                    result = replay(actor, "/api/v2/datasets", "same", data, lambda: create_dataset(actor, data), authorize)
                    return result["id"]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            identities = list(pool.map(create, range(4)))
        self.assertEqual(len(set(identities)), 1)
        self.assertEqual(Dataset.objects.count(), 1)
        self.assertEqual(IdempotentResult.objects.count(), 1)

    def test_parallel_put_has_one_fixed_object(self) -> None:
        content = b"public synthetic content"
        with transaction.atomic():
            actor = actor_for(self.actor.user_id)
            dataset = create_dataset(actor, {"name": "same"})
            row = dataset_for(actor, UUID(dataset["id"]), write=True)
            upload = create_upload(actor, row, {"filename": "test.csv", "format": "CSV", "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}, "http://localhost")
        identity, token = UUID(upload["id"]), upload["required_headers"]["X-Upload-Token"]
        def put(_index: int) -> None:
            try:
                with transaction.atomic():
                    actor = actor_for(self.actor.user_id)
                    row = upload_for(actor, identity)
                    put_upload(actor, row, token, io.BytesIO(content))
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(put, range(2)))
        self.assertEqual(StoredObject.objects.count(), 1)
        self.assertEqual(Upload.objects.get().object_version, StoredObject.objects.get().id)
