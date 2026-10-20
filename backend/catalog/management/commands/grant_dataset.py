"""Local administrator-controlled grants; every change is audited."""
from argparse import ArgumentParser
from typing import Any
from uuid import UUID
from django.core.management.base import BaseCommand
from catalog.services import set_grant


class Command(BaseCommand):
    help = "Set or revoke a dataset ACL as a tenant ADMIN actor"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("administrator", type=UUID)
        parser.add_argument("target", type=UUID)
        parser.add_argument("dataset", type=UUID)
        parser.add_argument("permission", choices=["OWNER", "EDITOR", "READER", "REVOKE"])

    def handle(self, *args: Any, **options: Any) -> None:
        permission = None if options["permission"] == "REVOKE" else options["permission"]
        set_grant(options["administrator"], options["target"], options["dataset"], permission)
        self.stdout.write("Grant updated")
