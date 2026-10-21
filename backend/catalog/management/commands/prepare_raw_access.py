"""升級既有 raw 物件：目錄 0750（setgid）、物件 0440，只給 Evaluator 專用群組讀取。

Migration for pre-existing raw objects: the writer keeps ownership, the shared group
gains read-only access, and world access is never granted."""
import json
import os
from pathlib import Path
from typing import Any
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Grant the sealed Evaluator group read-only access to existing raw objects"

    def handle(self,*args: Any,**options: Any) -> None:
        root = Path(settings.OBJECT_ROOT)
        if not root.is_dir():
            raise CommandError("Raw object root is unavailable")
        objects = sorted(root.glob("*.blob"))
        try:
            os.chown(root,-1,settings.RAW_GID)
            os.chmod(root,0o2750)
            for path in objects:
                os.chown(path,-1,settings.RAW_GID)
                os.chmod(path,0o440)
        except OSError as error:
            raise CommandError("Raw object permissions could not be prepared") from error
        self.stdout.write(json.dumps({"scope":"T07_RAW_ACCESS","group":settings.RAW_GID,"objects":len(objects)}))
