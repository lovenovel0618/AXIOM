"""Synthetic upload HTTP → authorized local preview for all supported formats."""
from io import BytesIO
import hashlib
import json
import secrets
from typing import Any
from uuid import UUID, uuid4
import polars as pl
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from catalog.management.commands.catalog_smoke import Browser
from catalog.management.commands.ingest_preview import preview
from catalog.models import Account, Tenant
from ingestion.limits import ImportLimits


class Command(BaseCommand):
    help = "Exercise real uploads and metadata parsing in a disposable Linux environment"

    def handle(self, *args: Any, **options: Any) -> None:
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="preview-" + uuid4().hex, password=password)
        actor = Account.objects.create(user=user, tenant=Tenant.objects.create(name="synthetic-preview-" + uuid4().hex), role="RESEARCHER")
        browser = Browser()
        browser.login(user.get_username(), password)
        status, dataset = browser.post("/api/v2/datasets", {"name": "公開合成匯入預覽"})
        if status != 201:
            raise CommandError("Synthetic dataset unavailable")
        buffer = BytesIO()
        pl.DataFrame({"x": [1, 2], "y": [3, 5]}).write_parquet(buffer, compression="zstd")
        fixtures = [("CSV", b'x,y\n1,3\n2,5\n'), ("JSON", b'[{"x":1,"y":3},{"x":2,"y":5}]'), ("PARQUET", buffer.getvalue())]
        results: list[dict[str, Any]] = []
        for format_name, content in fixtures:
            status, upload = browser.post(f"/api/v2/datasets/{dataset['id']}/uploads", {"filename": "synthetic", "format": format_name, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
            if status != 201:
                raise CommandError("Synthetic upload unavailable")
            status, _ = browser.request("/storage/uploads/" + upload["id"], "PUT", content, upload["required_headers"])
            if status != 204:
                raise CommandError("Synthetic bytes rejected")
            result = preview(actor.id, UUID(upload["id"]), ImportLimits(100, 8, 4096, 65536, 10))
            if result["metadata"]["row_count"] != 2 or [c["name"] for c in result["metadata"]["columns"]] != ["x", "y"]:
                raise CommandError("Synthetic structure mismatch")
            results.append(result)
        self.stdout.write(json.dumps({"scope": "T07_AUTHORIZED_METADATA_PREVIEW", "status": "PASS", "business_ingest_status": "NOT_RUN", "results": results}, indent=2))
