"""Trusted local research preflight, persisted without enabling PROFILE Run."""
from argparse import ArgumentParser
import json
from typing import Any
from uuid import UUID
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from catalog.inspection import parameters_from, preflight, read_model
from catalog.storage import StorageRejected
from catalog.validation import ApiError
from ingestion.limits import ImportLimits, ImportRejected
from mathematics.syntax import DslError


class Command(BaseCommand):
    help = "Inspect a fixed DRAFT with bounded quality and optional fit/development-only known DSL"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("actor", type=UUID)
        parser.add_argument("research_version", type=UUID)
        parser.add_argument("--dsl-file")
        parser.add_argument("--parameters", default="{}")
        for name in ("rows", "columns", "cell-utf8-bytes", "decoded-bytes", "parse-seconds"):
            parser.add_argument("--max-" + name, required=True, type=int)

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            limits = ImportLimits(options["max_rows"], options["max_columns"], options["max_cell_utf8_bytes"], options["max_decoded_bytes"], options["max_parse_seconds"])
            result = preflight(options["actor"], options["research_version"], limits, read_model(options["dsl_file"]), parameters_from(options["parameters"]))
        except (ApiError, StorageRejected, ImportRejected, DslError) as error:
            raise CommandError(error.code) from error
        except (OSError, DatabaseError):
            raise CommandError("DEPENDENCY_UNAVAILABLE") from None
        self.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))
