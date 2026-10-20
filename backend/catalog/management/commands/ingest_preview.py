"""Authorized local inspection; does not complete an upload or publish a version."""
from argparse import ArgumentParser
import json
from typing import Any
from uuid import UUID
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from catalog.models import Account, Audit, Upload
from catalog.services import actor_for, verify_staged
from catalog.storage import LocalVersionStore, StorageRejected
from catalog.validation import ApiError
from runtime.records import db_now
from ingestion.limits import ImportLimits, ImportRejected
from ingestion.supervisor import inspect_bytes


def preview(actor_id: UUID, upload_id: UUID, limits: ImportLimits) -> dict[str, Any]:
    with transaction.atomic():
        account = Account.objects.filter(pk=actor_id).first()
        if account is None:
            raise ApiError("FORBIDDEN", 403)
        actor = actor_for(account.user_id)
        if not actor.user.is_active:
            raise ApiError("FORBIDDEN", 403)
        reference = verify_staged(actor, upload_id)
        try:
            content = LocalVersionStore(settings.OBJECT_ROOT).read_verified(reference)
        except StorageRejected as error:
            raise ApiError("UPLOAD_OBJECT_CHANGED", 409) from error
        upload = Upload.objects.get(pk=upload_id, tenant_id=actor.tenant_id)
        if upload.status != "OPEN" or upload.expires_at <= db_now():
            raise ApiError("INVALID_TRANSITION", 409)
        result = inspect_bytes(content, upload.format, limits)
        Audit.objects.create(tenant_id=actor.tenant_id, actor_id=actor.id, action="INSPECT_UPLOAD", code="OK")
        return result | {"tenant_id": str(actor.tenant_id), "upload_id": str(upload_id), "object_version": str(reference.version)}


class Command(BaseCommand):
    help = "Inspect an authorized staged upload with explicit limits (Linux only; no business completion)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("actor", type=UUID)
        parser.add_argument("upload", type=UUID)
        for name in ("rows", "columns", "cell-utf8-bytes", "decoded-bytes", "parse-seconds"):
            parser.add_argument("--max-" + name, required=True, type=int)

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            limits = ImportLimits(options["max_rows"], options["max_columns"], options["max_cell_utf8_bytes"], options["max_decoded_bytes"], options["max_parse_seconds"])
            result = preview(options["actor"], options["upload"], limits)
        except (ApiError, ImportRejected) as error:
            raise CommandError(error.code) from error
        except (OSError, DatabaseError) as error:
            raise CommandError("DEPENDENCY_UNAVAILABLE") from error
        self.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))
