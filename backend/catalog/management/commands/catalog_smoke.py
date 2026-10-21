"""Real loopback HTTP session, upload, tenant and revocation probe."""
from argparse import ArgumentParser
import hashlib
from http.cookiejar import CookieJar
import json
import secrets
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, OpenerDirector, Request
from uuid import UUID, uuid4
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import Account, StoredObject, Tenant, Upload
from catalog.services import actor_for, set_grant, verify_staged
from catalog.storage import LocalVersionStore
from catalog.validation import validate_api
from runtime.contracts import JsonObject

# 冒煙命令只在容器內的迴環埠與前端代理上呼叫，不經外部網路，故明文 HTTP 屬刻意選擇。
SCHEME = "http"
BASE = f"{SCHEME}://127.0.0.1:8000"
FRONTEND_BASE = f"{SCHEME}://frontend:5173"


class Browser:
    def __init__(self, base: str = BASE) -> None:
        self.base = base
        self.cookies = CookieJar()
        self.opener: OpenerDirector = build_opener(HTTPCookieProcessor(self.cookies))

    def request(self, path: str, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        current = {"Origin": self.base} | (headers or {})
        for cookie in self.cookies:
            if cookie.name == settings.CSRF_COOKIE_NAME and cookie.value is not None:
                current["X-CSRFToken"] = cookie.value
        request = Request(self.base + path, data=data, headers=current, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status, response.read(65536)
        except HTTPError as error:
            return error.code, error.read(65536)

    def login(self, username: str, password: str) -> None:
        status, _ = self.request("/auth/login")
        if status != 200:
            raise CommandError("Login form unavailable")
        data = urlencode({"username": username, "password": password}).encode("utf-8")
        status, _ = self.request("/auth/login", "POST", data, {"Content-Type": "application/x-www-form-urlencoded"})
        if status != 200:
            raise CommandError("Synthetic login failed")

    def post(self, path: str, document: JsonObject) -> tuple[int, JsonObject]:
        status, raw = self.request(path, "POST", json.dumps(document).encode("utf-8"), {"Content-Type": "application/json", "Idempotency-Key": uuid4().hex})
        result: JsonObject = json.loads(raw)
        return status, result


class Command(BaseCommand):
    help = "Exercise T05 over real loopback HTTP using private synthetic accounts"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--frontend", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        base = FRONTEND_BASE if options["frontend"] else BASE
        password = secrets.token_urlsafe(30)
        actors: list[Account] = []
        with transaction.atomic():
            for _ in range(2):
                tenant = Tenant.objects.create(name="smoke-" + uuid4().hex)
                user = User.objects.create_user(username="smoke-" + uuid4().hex, password=password)
                actors.append(Account.objects.create(user=user, tenant=tenant, role="ADMIN"))
        browser = Browser(base)
        browser.login(actors[0].user.get_username(), password)
        status, dataset = browser.post("/api/v2/datasets", {"name": "T05 synthetic HTTP probe"})
        if status != 201:
            raise CommandError("Dataset creation failed")
        validate_api(dataset, "Dataset")
        content = b"x,y\n1,3\n2,5\n"
        checksum = hashlib.sha256(content).hexdigest()
        status, upload = browser.post("/api/v2/datasets/" + dataset["id"] + "/uploads", {"filename": "../../synthetic.csv", "format": "CSV", "size_bytes": len(content), "sha256": checksum})
        if status != 201:
            raise CommandError("Upload session creation failed")
        validate_api(upload, "UploadSession")
        path = "/storage/uploads/" + upload["id"]
        put_status, _ = browser.request(path, "PUT", content, upload["required_headers"])
        if put_status != 204:
            raise CommandError("Synthetic upload failed")
        with transaction.atomic():
            reference = verify_staged(actor_for(actors[0].user_id), UUID(upload["id"]))
            if LocalVersionStore(settings.OBJECT_ROOT).read_verified(reference) != content:
                raise CommandError("Stored bytes differ")
        status, completion = browser.post("/api/v2/uploads/" + upload["id"] + "/complete", {"checksum": checksum})
        if status != 503 or completion["code"] != "DEPENDENCY_UNAVAILABLE":
            raise CommandError("INGEST dependency gate did not remain closed")
        other = Browser(base)
        other.login(actors[1].user.get_username(), password)
        hidden_status, _ = other.post("/api/v2/datasets/" + dataset["id"] + "/uploads", {})
        list_status, raw = other.request("/api/v2/datasets")
        page: JsonObject = json.loads(raw)
        if hidden_status != 404 or list_status != 200 or page["items"]:
            raise CommandError("Cross-tenant isolation failed")
        set_grant(actors[0].id, actors[0].id, UUID(dataset["id"]), None)
        revoked_status, _ = browser.request(path, "PUT", content, upload["required_headers"])
        if revoked_status != 404:
            raise CommandError("Revoked ACL still allows upload")
        row = Upload.objects.get(pk=UUID(upload["id"]))
        self.stdout.write(json.dumps({"status": "PASS", "scope": "T05_LOCAL_SYNTHETIC_HTTP", "via_frontend": bool(options["frontend"]), "upload_http": put_status, "cross_tenant_http": hidden_status, "revoked_token_http": revoked_status, "complete_http": status, "business_ingest_status": "NOT_RUN", "upload_id": str(row.id), "object_version": str(row.object_version), "registered_objects": StoredObject.objects.filter(upload=row).count(), "sha256": checksum}))
