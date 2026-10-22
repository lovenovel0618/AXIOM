"""重建後的本機帳號 bootstrap：環境變數驅動、冪等、不覆寫既有密碼。

Idempotent local account bootstrap for a rebuilt development database: an absent
account is created from AXIOM_BOOTSTRAP_* variables, an existing Django user
without a catalog account is repaired, and an existing password is never reset.
Without AXIOM_BOOTSTRAP_USER the command writes nothing and reports SKIPPED."""
import json
import os
from typing import Any
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import Account, Audit, Tenant

USER_VARIABLE = "AXIOM_BOOTSTRAP_USER"
PASSWORD_VARIABLE = "AXIOM_BOOTSTRAP_PASSWORD"
TENANT_VARIABLE = "AXIOM_BOOTSTRAP_TENANT"
DEFAULT_TENANT = "local"
MINIMUM_PASSWORD_LENGTH = 12


def environment_value(name: str) -> str:
    """本機設定只作啟動輸入；空白值一律視為未設定，不建立預設帳號。"""
    return os.environ.get(name, "").strip()


class Command(BaseCommand):
    help = "Create the configured local account when it is absent, without resetting an existing password"

    def handle(self, *args: Any, **options: Any) -> None:
        username = environment_value(USER_VARIABLE)
        if not username:
            self.stdout.write(json.dumps({"scope": "BOOTSTRAP_ACCOUNT", "status": "SKIPPED", "reason": f"{USER_VARIABLE} is not set"}))
            return
        password = os.environ.get(PASSWORD_VARIABLE, "")
        if len(password) < MINIMUM_PASSWORD_LENGTH:
            raise CommandError(f"{PASSWORD_VARIABLE} must be at least {MINIMUM_PASSWORD_LENGTH} characters")
        tenant_name = environment_value(TENANT_VARIABLE) or DEFAULT_TENANT
        with transaction.atomic():
            matches = list(Tenant.objects.filter(name=tenant_name)[:2])
            if len(matches) > 1:
                raise CommandError("Ambiguous tenant name; use a unique local tenant name")
            tenant = matches[0] if matches else Tenant.objects.create(name=tenant_name)
            existing_user = User.objects.filter(username=username).first()
            user = existing_user if existing_user is not None else User.objects.create_user(username=username, password=password)
            account = Account.objects.filter(user=user).first()
            status = "EXISTS"
            if account is None:
                account = Account.objects.create(user=user, tenant=tenant)
                status = "REPAIRED" if existing_user is not None else "CREATED"
            if status != "EXISTS":
                Audit.objects.create(tenant_id=tenant.id, actor_id=account.id, action="BOOTSTRAP_ACCOUNT", code="OK")
        self.stdout.write(json.dumps({"scope": "BOOTSTRAP_ACCOUNT", "status": status, "username": username, "actor": str(account.id), "tenant": str(tenant.id), "user_active": user.is_active, "account_enabled": account.enabled}))
