"""Trusted local administration; no public registration or password arguments."""
from argparse import ArgumentParser
import getpass
import sys
from typing import Any
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import Account, Tenant, Audit


class Command(BaseCommand):
    help = "Create a local account bound to exactly one tenant"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("username")
        parser.add_argument("tenant")
        parser.add_argument("--role", choices=["VIEWER", "RESEARCHER", "ADMIN"], default="RESEARCHER")
        parser.add_argument("--password-stdin", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        password = sys.stdin.readline().rstrip("\r\n") if options["password_stdin"] else getpass.getpass("Password: ")
        if len(password) < 12:
            raise CommandError("Use at least 12 characters")
        with transaction.atomic():
            if User.objects.filter(username=options["username"]).exists():
                raise CommandError("Username already exists")
            matches = list(Tenant.objects.filter(name=options["tenant"])[:2])
            if len(matches) > 1:
                raise CommandError("Ambiguous tenant name; use a unique local tenant name")
            tenant = matches[0] if matches else Tenant.objects.create(name=options["tenant"])
            user = User.objects.create_user(username=options["username"], password=password)
            account = Account.objects.create(user=user, tenant=tenant, role=options["role"])
            Audit.objects.create(tenant_id=tenant.id, actor_id=account.id, action="PROVISION_ACCOUNT", code="OK")
        self.stdout.write(f"actor={account.id} tenant={tenant.id}")
