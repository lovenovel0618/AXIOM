"""Recover expired leases and repeatedly publish outstanding probes."""
import logging
import time
from typing import Any
from argparse import ArgumentParser
from django.core.management.base import BaseCommand
from kombu.exceptions import OperationalError
from foundation.dispatch import relay
from foundation.tasks import publish_probe
from runtime.tasks import relay_control

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Dispatch synthetic foundation probes (no research tasks)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            try:
                relay_control()
                relay(publish_probe)
            except OperationalError:
                if options["once"]:
                    raise
                logger.warning("Broker unavailable; pending probes retained")
            if options["once"]:
                return
            time.sleep(2)
