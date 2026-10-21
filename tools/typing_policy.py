"""檢查型別規範：完整函式標註、動態型別額度及禁止忽略診斷。

既有 JSON／框架相容邊界以逐檔額度公開列管，新檔沒有自動豁免。
此檢查補足 Pyright strict 不會拒絕顯式 Any 的缺口，並非替代 Pyright。
"""
import ast
import json
from io import StringIO
import tokenize
from pathlib import Path
import re
from typing import cast
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("backend", "tools", "tests", "docs/企劃案/tools")
BASELINE = ROOT / "tools/typing-boundaries.json"


class BoundaryCount(TypedDict):
    """每檔允許的既有動態型別用量；不可新增型別逃生門。"""
    Any: int
    JsonObject: int


def type_aliases(tree: ast.AST) -> dict[str, str]:
    """辨識明示 import alias，別名不能擴大既有動態型別額度。"""
    names = {"Any":"Any", "JsonObject":"JsonObject"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for entry in node.names:
            if entry.name in {"Any", "JsonObject"}:
                names[entry.asname or entry.name] = entry.name
    return names


def referenced_name(node: ast.AST) -> str:
    """只計讀取型別名稱；TypedDict 欄位宣告等寫入目標不算 Any 引用。"""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def dynamic_counts(tree: ast.AST) -> BoundaryCount:
    """計算名稱引用與 import alias，避免把 Any 改名後躲過額度。"""
    names = type_aliases(tree)
    counts: BoundaryCount = {"Any":0, "JsonObject":0}
    for node in ast.walk(tree):
        canonical = names.get(referenced_name(node), "")
        if canonical == "Any":
            counts["Any"] += 1
        elif canonical == "JsonObject":
            counts["JsonObject"] += 1
    return counts


def inspect_source(source: str, name: str, allowed: BoundaryCount) -> list[str]:
    """回傳可定位的違規，不改檔、不替缺漏標註推導 Any。"""
    tree = ast.parse(source, filename=name)
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        arguments.extend(argument for argument in (node.args.vararg, node.args.kwarg) if argument is not None)
        missing = [arg.arg for arg in arguments if arg.annotation is None and arg.arg not in {"self", "cls"}]
        if missing or node.returns is None:
            problems.append(f"{name}:{node.lineno}: {node.name} 缺少型別標註 {missing}")
    counts = dynamic_counts(tree)
    for kind in ("Any", "JsonObject"):
        if counts[kind] > allowed[kind]:
            problems.append(f"{name}: {kind} {counts[kind]} 超過既有邊界額度 {allowed[kind]}")
    comments = [token.string for token in tokenize.generate_tokens(StringIO(source).readline) if token.type == tokenize.COMMENT]
    if any(re.search(r"#\s*(?:type:\s*ignore|pyright:\s*ignore)", comment) for comment in comments):
        problems.append(f"{name}: 不允許忽略型別診斷")
    return problems


def check(root: Path = ROOT) -> list[str]:
    """檢查所有追蹤來源範圍；額度檔只接受明確非負整數。"""
    raw: object = json.loads((root / "tools/typing-boundaries.json").read_text())
    if not isinstance(raw, dict):
        raise ValueError("Invalid typing boundary baseline")
    problems: list[str] = []
    for source_root in SOURCE_ROOTS:
        for path in sorted((root / source_root).rglob("*.py")):
            relative = str(path.relative_to(root))
            # json.loads 的 Any 只在這個設定解碼邊界取得，值須通過下方整數檢查。
            entry: object = cast(dict[str, object], raw).get(relative, {"Any":0, "JsonObject":0})
            if not isinstance(entry, dict):
                raise ValueError("Invalid typing boundary entry")
            any_count: object = cast(dict[str, object], entry).get("Any")
            json_count: object = cast(dict[str, object], entry).get("JsonObject")
            if type(any_count) is not int or type(json_count) is not int or any_count < 0 or json_count < 0:
                raise ValueError("Invalid typing boundary count")
            allowed: BoundaryCount = {"Any":any_count, "JsonObject":json_count}
            problems.extend(inspect_source(path.read_text(),relative,allowed))
    return problems


if __name__ == "__main__":
    errors = check()
    print(json.dumps({"status":"FAIL" if errors else "PASS", "errors":errors},ensure_ascii=False,indent=2))
    raise SystemExit(bool(errors))
