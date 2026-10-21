"""型別政策反例與真正 Pyright 負向測試；不只驗證合法程式能通過。"""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from tools.typing_policy import ROOT, inspect_source


class TypingPolicyTests(unittest.TestCase):
    def test_missing_annotations_fail(self) -> None:
        result = inspect_source("def example(value):\n return value\n", "case.py", {"Any":0,"JsonObject":0})
        self.assertTrue(result)

    def test_new_any_and_alias_fail(self) -> None:
        source = "from typing import Any as Value\ndef example(value: Value) -> Value:\n return value\n"
        self.assertTrue(inspect_source(source,"case.py",{"Any":0,"JsonObject":0}))

    def test_type_ignore_fails(self) -> None:
        self.assertTrue(inspect_source("value = 1 # type: ignore\n","case.py",{"Any":0,"JsonObject":0}))

    def test_typed_function_passes(self) -> None:
        self.assertFalse(inspect_source("def example(value: int) -> int:\n return value+1\n","case.py",{"Any":0,"JsonObject":0}))

    def test_pyright_rejects_wrong_value_missing_field_and_typo(self) -> None:
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            valid = 'from runtime.budget_types import BudgetUsage, zero_usage\nusage: BudgetUsage = zero_usage()\nusage["cpu_seconds"] = 2\n'
            (folder/"valid.py").write_text(valid)
            invalid = valid+'usage["cpu_seconds"] = "two"\nusage["cpu_second"] = 2\nincomplete: BudgetUsage = {"cpu_seconds":1}\n'
            (folder/"invalid.py").write_text(invalid)
            config = {"include":["valid.py","invalid.py"],"extraPaths":[str(ROOT/"backend")],"pythonVersion":"3.13","typeCheckingMode":"strict","venvPath":str(ROOT),"venv":".venv-backend"}
            (folder/"pyrightconfig.json").write_text(json.dumps(config))
            process = subprocess.run([str(ROOT/".venv-backend/bin/pyright"),"--project",str(folder),"--outputjson"],capture_output=True,text=True,check=False)
            self.assertEqual(process.returncode,1,process.stdout+process.stderr)
            result = json.loads(process.stdout)
            diagnostics = result["generalDiagnostics"]
            self.assertEqual(len(diagnostics),3,diagnostics)
            self.assertTrue(all(Path(row["file"]).name=="invalid.py" and row["severity"]=="error" for row in diagnostics),diagnostics)
            self.assertEqual({row["range"]["start"]["line"] for row in diagnostics},{3,4,5})
