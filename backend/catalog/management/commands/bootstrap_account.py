"""重建後的本機帳號 bootstrap：環境變數驅動、冪等、不覆寫既有密碼。

Idempotent local account bootstrap for a rebuilt development database: absent accounts are
created from AXIOM_BOOTSTRAP_ACCOUNTS, an existing Django user without a catalog account is
repaired, and an existing password is never reset. Every configured account shares the one
local tenant named by AXIOM_BOOTSTRAP_TENANT, so the human and the agent see the same data.
Without a configured account list the command writes nothing and reports SKIPPED."""
import json
import os
from typing import Any, cast
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import Account, Audit, Tenant

ACCOUNTS_VARIABLE = "AXIOM_BOOTSTRAP_ACCOUNTS"
TENANT_VARIABLE = "AXIOM_BOOTSTRAP_TENANT"
DEFAULT_TENANT = "local"
MINIMUM_PASSWORD_LENGTH = 12


def environment_value(name: str) -> str:
    """本機設定只作啟動輸入；空白值一律視為未設定，不建立預設帳號。"""
    return os.environ.get(name, "").strip()


def configured_accounts() -> list[tuple[str, str]]:
    """解析 `AXIOM_BOOTSTRAP_ACCOUNTS` 的 JSON 陣列；每個項目只允許 user 與 password。

    設定缺失視為「不引導」；一旦提供就必須完整合法，不以部分預設值補齊或略過壞項目。"""
    raw = environment_value(ACCOUNTS_VARIABLE)
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except ValueError as error:
        raise CommandError(f"{ACCOUNTS_VARIABLE} must be a JSON array") from error
    if not isinstance(decoded, list) or not decoded:
        raise CommandError(f"{ACCOUNTS_VARIABLE} must be a non-empty JSON array")
    entries = cast(list[object], decoded)
    accounts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise CommandError("Each bootstrap account must be a JSON object")
        fields = cast(dict[str, object], entry)
        if set(fields) != {"user", "password"}:
            raise CommandError("Each bootstrap account must contain exactly user and password")
        username = fields["user"]
        password = fields["password"]
        if not isinstance(username, str) or not username.strip():
            raise CommandError("Bootstrap username must be a non-empty string")
        if not isinstance(password, str) or len(password) < MINIMUM_PASSWORD_LENGTH:
            raise CommandError(f"Bootstrap password must be at least {MINIMUM_PASSWORD_LENGTH} characters")
        normalized_username = username.strip()
        if normalized_username in seen:
            raise CommandError("Duplicate bootstrap username")
        seen.add(normalized_username)
        accounts.append((normalized_username, password))
    return accounts


def provision(tenant: Tenant, username: str, password: str) -> dict[str, object]:
    """建立或修復單一帳號；已存在的使用者不改密碼，已存在的帳號不動其租戶歸屬。"""
    existing_user = User.objects.filter(username=username).first()
    user = existing_user if existing_user is not None else User.objects.create_user(username=username, password=password)
    account = Account.objects.filter(user=user).first()
    status = "EXISTS"
    if account is None:
        account = Account.objects.create(user=user, tenant=tenant)
        status = "REPAIRED" if existing_user is not None else "CREATED"
    if status != "EXISTS":
        Audit.objects.create(tenant_id=tenant.id, actor_id=account.id, action="BOOTSTRAP_ACCOUNT", code="OK")
    return {"username": username, "status": status, "actor": str(account.id), "user_active": user.is_active, "account_enabled": account.enabled}


class Command(BaseCommand):
    help = "Create the configured local accounts when they are absent, without resetting an existing password"

    def handle(self, *args: Any, **options: Any) -> None:
        accounts = configured_accounts()
        if not accounts:
            self.stdout.write(json.dumps({"scope": "BOOTSTRAP_ACCOUNT", "status": "SKIPPED", "reason": f"{ACCOUNTS_VARIABLE} is not set"}))
            return
        tenant_name = environment_value(TENANT_VARIABLE) or DEFAULT_TENANT
        with transaction.atomic():
            matches = list(Tenant.objects.filter(name=tenant_name)[:2])
            if len(matches) > 1:
                raise CommandError("Ambiguous tenant name; use a unique local tenant name")
            tenant = matches[0] if matches else Tenant.objects.create(name=tenant_name)
            results = [provision(tenant, username, password) for username, password in accounts]
        self.stdout.write(json.dumps({"scope": "BOOTSTRAP_ACCOUNT", "status": "APPLIED", "tenant": str(tenant.id), "accounts": results}))
