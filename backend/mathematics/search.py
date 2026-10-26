"""T07 SEARCH 執行器（離線策略核心）：以 fit 列擬合三族基線，development 只評分，final_test 不進介面。
插件只負責提出候選；等價 AST 依 AX-10 去重並保留全部生成來源，公式身分由 canonical DSL 決定。
本模組不建立 run、不寫 DB、不產生 EvidenceBundle，也不以牆鐘時間參與排序。

Deterministic offline baseline search over linear, polynomial and fixed-harmonic dictionaries."""
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
import json
import math
from typing import Callable, cast
from mathematics.compiler import UNIT_ERROR, Plan, compile_dsl
from mathematics.linalg import solve
from mathematics.metrics import score
from mathematics.normalization import encoded
from mathematics.syntax import LIMIT, OPERATORS, DslError, require
from runtime.contracts import JsonObject, canonical_bytes

Unit = tuple[int, ...]
Row = tuple[float, float]
POLICY = "local-search-execution-v1"
USAGE_SCOPE = "LOCAL_SEARCH_EXECUTION_ONLY"
PRODUCT_STATUS = "NOT_RUN"
PRECISION_BITS = 53
MAX_ROWS = 4096
VERSION = "1.0"
INPUT_SCHEMA_VERSION = "dsl-v1/1.0"
OUTPUT_SCHEMA_VERSION = "dsl-v1/1.0"
COEFFICIENT_DIGITS = 17
FREQUENCY_DIGITS = 12
UNIT_BOUND = 32
MIN_DEGREE = 2
MAX_DEGREE = 3
LINEAR = "LINEAR"
POLYNOMIAL = "POLYNOMIAL"
HARMONIC = "HARMONIC"
EXECUTED = "EXECUTED"
NOT_APPLICABLE = "NOT_APPLICABLE"
MANIFEST_FIELDS = frozenset({"plugin_id", "version", "input_schema_version", "output_schema_version", "input_types",
    "output_types", "operators", "resource_class", "precision_support", "determinism", "seed_support", "timeout_seconds",
    "memory_bytes", "checkpoint_version"})
RESOURCE_CLASSES = frozenset({"CPU_LOCAL"})
PRECISION_SUPPORT = frozenset({PRECISION_BITS})
DETERMINISM_VALUES = frozenset({"DETERMINISTIC"})


@dataclass(frozen=True)
class Variable:
    name: str
    unit: Unit


@dataclass(frozen=True)
class Domain:
    """x 的精確有理數定義域；SEARCH 沿用既有研究版本，不自行縮域。"""
    lower: Fraction
    upper: Fraction
    lower_closed: bool
    upper_closed: bool


@dataclass(frozen=True)
class Request:
    """離線搜尋輸入；只有 fit／development 兩區，沒有 final_test 欄位，頻率因此不能由 final 選擇。"""
    variable: Variable
    target_unit: Unit
    domain: Domain
    fit: tuple[Row, ...]
    development: tuple[Row, ...]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    detail: str

    def document(self) -> JsonObject:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class Manifest:
    """AX-38 插件 manifest；欄位與值域都封閉，插件無法以宣告取得額外權限。"""
    plugin_id: str
    version: str
    input_schema_version: str
    output_schema_version: str
    input_types: tuple[str, ...]
    output_types: tuple[str, ...]
    operators: tuple[str, ...]
    resource_class: str
    precision_support: tuple[int, ...]
    determinism: str
    seed_support: bool
    timeout_seconds: int
    memory_bytes: int
    checkpoint_version: str

    def document(self) -> JsonObject:
        return {"plugin_id": self.plugin_id, "version": self.version, "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version, "input_types": list(self.input_types),
            "output_types": list(self.output_types), "operators": list(self.operators), "resource_class": self.resource_class,
            "precision_support": list(self.precision_support), "determinism": self.determinism,
            "seed_support": self.seed_support, "timeout_seconds": self.timeout_seconds, "memory_bytes": self.memory_bytes,
            "checkpoint_version": self.checkpoint_version}


@dataclass(frozen=True)
class Proposal:
    """一個策略變體提出的候選；參數值即 AST 內 lower=upper 的綁定，擬合不再另外注入係數。"""
    source: str
    plan: Plan
    parameters: dict[str, str]
    fit_rows: int
    unknowns: int
    pivots: int


@dataclass(frozen=True)
class Strategy:
    """AX-38 共用策略介面：LINEAR／POLYNOMIAL／HARMONIC 共用同一個提出候選入口與 manifest。"""
    family: str
    manifest: Manifest
    variants: tuple[tuple[int, str], ...]
    propose: Callable[[Request, int], tuple[list[Proposal], list[Diagnostic]]]


def _text(document: JsonObject, name: str) -> str:
    value = document[name]
    require(isinstance(value, str) and 0 < len(value) <= 64, "INVALID_SCHEMA")
    return value


def _strings(document: JsonObject, name: str) -> tuple[str, ...]:
    items = document[name]
    require(isinstance(items, list), "INVALID_SCHEMA")
    listed = cast(list[object], items)
    require(0 < len(listed) <= 32, "INVALID_SCHEMA")
    result: list[str] = []
    for item in listed:
        require(isinstance(item, str) and 0 < len(item) <= 64, "INVALID_SCHEMA")
        result.append(cast(str, item))
    return tuple(result)


def _integers(document: JsonObject, name: str, low: int, high: int) -> tuple[int, ...]:
    items = document[name]
    require(isinstance(items, list), "INVALID_SCHEMA")
    listed = cast(list[object], items)
    require(0 < len(listed) <= 32, "INVALID_SCHEMA")
    result: list[int] = []
    for item in listed:
        require(isinstance(item, int) and not isinstance(item, bool) and low <= item <= high, "INVALID_SCHEMA")
        result.append(cast(int, item))
    return tuple(result)


def manifest(document: JsonObject) -> Manifest:
    """只接受已列舉欄位；未知欄位、缺欄位與越界值都拒絕，不替插件補預設權限。"""
    require(set(document) == set(MANIFEST_FIELDS), "INVALID_SCHEMA")
    operators = _strings(document, "operators")
    require(set(operators) <= OPERATORS, "UNSUPPORTED_OPERATOR")
    resource_class = _text(document, "resource_class")
    require(resource_class in RESOURCE_CLASSES, "INVALID_SCHEMA")
    determinism = _text(document, "determinism")
    require(determinism in DETERMINISM_VALUES, "INVALID_SCHEMA")
    require(set(_integers(document, "precision_support", 1, 64)) <= PRECISION_SUPPORT, "INVALID_SCHEMA")
    require(document["seed_support"] is False, "INVALID_SCHEMA")
    require(type(document["timeout_seconds"]) is int and 1 <= document["timeout_seconds"] <= 3600, "INVALID_SCHEMA")
    require(type(document["memory_bytes"]) is int and 1024 <= document["memory_bytes"] <= 2**40, "INVALID_SCHEMA")
    return Manifest(_text(document, "plugin_id"), _text(document, "version"), _text(document, "input_schema_version"),
        _text(document, "output_schema_version"), _strings(document, "input_types"), _strings(document, "output_types"),
        operators, resource_class, _integers(document, "precision_support", 1, 64), determinism, False,
        document["timeout_seconds"], document["memory_bytes"], _text(document, "checkpoint_version"))


def _manifest_document(plugin_id: str, operators: tuple[str, ...]) -> JsonObject:
    return {"plugin_id": plugin_id, "version": VERSION, "input_schema_version": INPUT_SCHEMA_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION, "input_types": ["numeric_rows", "dsl_declarations"],
        "output_types": ["dsl_expression", "identity_hash"], "operators": list(operators), "resource_class": "CPU_LOCAL",
        "precision_support": [PRECISION_BITS], "determinism": "DETERMINISTIC", "seed_support": False,
        "timeout_seconds": 30, "memory_bytes": 268435456, "checkpoint_version": "1"}


MANIFESTS: tuple[Manifest, ...] = (manifest(_manifest_document("linear-fit", ("add", "mul"))),
    manifest(_manifest_document("polynomial-fit", ("add", "mul", "pow"))),
    manifest(_manifest_document("harmonic-fit", ("add", "mul", "sin", "cos"))))


def _decimal(value: float, digits: int) -> str:
    """把 float 收斂成 DSL 接受的十進位字串；不接受指數記號與非有限值。"""
    require(math.isfinite(value), "DOMAIN_VIOLATION")
    with localcontext() as context:
        context.prec = digits
        context.rounding = ROUND_HALF_EVEN
        rounded = +Decimal(value)
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    require(len(text) <= 128, LIMIT)
    return "0" if float(text) == 0 else text


def _unit(value: Sequence[int]) -> list[int]:
    require(len(value) == 7 and all(abs(component) <= UNIT_BOUND for component in value), UNIT_ERROR)
    return list(value)


def _coefficient_unit(target: Unit, power: int, variable: Unit) -> list[int]:
    return _unit(tuple(target[index] - power * variable[index] for index in range(7)))


def _frequency_unit(variable: Unit) -> list[int]:
    return _unit(tuple(-component for component in variable))


def _parameter(name: str, unit: Sequence[int], text: str) -> JsonObject:
    return {"name": name, "unit": _unit(unit), "lower": text, "upper": text}


def _term(name: str, power: int, variable: str) -> JsonObject:
    if power == 0:
        return {"op": "param", "name": name}
    base: JsonObject = {"op": "var", "name": variable}
    if power > 1:
        base = {"op": "pow", "args": [base, {"op": "const", "value": {"numerator": str(power), "denominator": "1"}}]}
    return {"op": "mul", "args": [{"op": "param", "name": name}, base]}


def _root(terms: list[JsonObject]) -> JsonObject | None:
    if not terms:
        return None
    return terms[0] if len(terms) == 1 else {"op": "add", "args": terms}


def _compile(request: Request, parameters: list[JsonObject], root: JsonObject) -> Plan:
    document: JsonObject = {"dsl_version": VERSION,
        "variables": [{"name": request.variable.name, "unit": list(request.variable.unit)}], "parameters": parameters,
        "domain": [{"name": request.variable.name, "lower": encoded(request.domain.lower), "upper": encoded(request.domain.upper),
                    "lower_closed": request.domain.lower_closed, "upper_closed": request.domain.upper_closed}], "root": root}
    return compile_dsl(canonical_bytes(document))


def _summary(request: Request) -> tuple[float, float, float, float]:
    """fit 的均值／尺度；尺度為 0 時退化為 1，避免除以 0 又不用牆鐘或隨機決定。"""
    xs = [row[0] for row in request.fit]
    ys = [row[1] for row in request.fit]
    return math.fsum(xs) / len(xs), max(xs) - min(xs) or 1.0, math.fsum(ys) / len(ys), max(ys) - min(ys) or 1.0


def _expand(coefficients: tuple[float, ...], xbar: float, xscale: float) -> list[float]:
    """把 t=(x-xbar)/xscale 的係數展開回原始 x 的冪次，結果 AST 因此對回原始變數。"""
    degree = len(coefficients) - 1
    scaled = [coefficients[k] / xscale**k for k in range(degree + 1)]
    return [math.fsum(scaled[k] * math.comb(k, j) * (-xbar) ** (k - j) for k in range(j, degree + 1))
            for j in range(degree + 1)]


def _proposal(request: Request, source: str, parameters: list[JsonObject], values: dict[str, str], root: JsonObject,
              unknowns: int, pivots: int) -> Proposal:
    return Proposal(source, _compile(request, parameters, root), values, len(request.fit), unknowns, pivots)


def _linear(request: Request) -> tuple[list[Proposal], list[Diagnostic]]:
    """常數零、fit 均值與含截距最小平方；前兩者不需要額外樣本，因此一定有紀錄。"""
    proposals: list[Proposal] = []
    diagnostics: list[Diagnostic] = []
    mean = _decimal(math.fsum(row[1] for row in request.fit) / len(request.fit), COEFFICIENT_DIGITS)
    for variant, text in (("zero", "0"), ("mean", mean)):
        parameters = [_parameter("c0", request.target_unit, text)]
        proposals.append(_proposal(request, f"linear-fit:{variant}", parameters, {"c0": text},
            {"op": "param", "name": "c0"}, 1, 0))
    distinct = {row[0] for row in request.fit}
    if len(distinct) < 2:
        diagnostics.append(Diagnostic("INSUFFICIENT_DISTINCT_X", "linear least squares needs two distinct x"))
        return proposals, diagnostics
    xbar, xscale, ybar, yscale = _summary(request)
    result = solve([[1.0, (row[0] - xbar) / xscale] for row in request.fit],
                   [(row[1] - ybar) / yscale for row in request.fit])
    if result.coefficients is None:
        diagnostics.append(Diagnostic("RANK_DEFICIENT", f"rank {result.rank} of {result.columns}"))
        return proposals, diagnostics
    intercept, slope = result.coefficients
    # 常數項必須由中心化的 t 逆變換回原始 x 軸，否則 x 均值不為 0 時截距會偏掉。
    expanded = _expand((intercept, slope), xbar, xscale)
    terms: list[JsonObject] = []
    parameters: list[JsonObject] = []
    values: dict[str, str] = {}
    for power in range(2):
        value = ybar + yscale * expanded[power] if power == 0 else yscale * expanded[power]
        text = _decimal(value, COEFFICIENT_DIGITS)
        if text == "0":
            continue
        name = f"c{power}"
        parameters.append(_parameter(name, _coefficient_unit(request.target_unit, power, request.variable.unit), text))
        values[name] = text
        terms.append(_term(name, power, request.variable.name))
    root = _root(terms)
    if root is None:
        diagnostics.append(Diagnostic("DEGENERATE_MODEL", "linear least squares collapsed to zero"))
        return proposals, diagnostics
    proposals.append(_proposal(request, "linear-fit:least-squares", parameters, values, root, result.columns, result.pivots))
    return proposals, diagnostics


def _polynomial(request: Request, degree: int) -> tuple[list[Proposal], list[Diagnostic]]:
    """degree 2／3 多項式；超出註冊度數上限或不同 x 不足都留拒用紀錄，不硬給更高次擬合。"""
    if not MIN_DEGREE <= degree <= MAX_DEGREE:
        return [], [Diagnostic("UNSUPPORTED_DEGREE", f"degree {degree} outside {MIN_DEGREE}..{MAX_DEGREE}")]
    if len({row[0] for row in request.fit}) < degree + 1:
        return [], [Diagnostic("INSUFFICIENT_DISTINCT_X", f"degree {degree} needs {degree + 1} distinct x")]
    xbar, xscale, ybar, yscale = _summary(request)
    result = solve([[(row[0] - xbar) ** k / xscale**k for k in range(degree + 1)] for row in request.fit],
                   [(row[1] - ybar) / yscale for row in request.fit])
    if result.coefficients is None:
        return [], [Diagnostic("RANK_DEFICIENT", f"degree {degree} rank {result.rank} of {result.columns}")]
    expanded = _expand(result.coefficients, xbar, xscale)
    terms: list[JsonObject] = []
    parameters: list[JsonObject] = []
    values: dict[str, str] = {}
    for power in range(degree + 1):
        value = ybar + yscale * expanded[power] if power == 0 else yscale * expanded[power]
        text = _decimal(value, COEFFICIENT_DIGITS)
        if text == "0":
            continue
        name = f"c{power}"
        parameters.append(_parameter(name, _coefficient_unit(request.target_unit, power, request.variable.unit), text))
        values[name] = text
        terms.append(_term(name, power, request.variable.name))
    root = _root(terms)
    if root is None:
        return [], [Diagnostic("DEGENERATE_MODEL", f"degree {degree} collapsed to zero")]
    return [_proposal(request, f"polynomial-fit:degree-{degree}", parameters, values, root, result.columns, result.pivots)], []


def _harmonic(request: Request, index: int) -> tuple[list[Proposal], list[Diagnostic]]:
    """固定字典 omega=2*pi*k/T：頻率只由 fit 決定，寫入 AST 的是與評估一致的取整值。"""
    xs = [row[0] for row in request.fit]
    if len(set(xs)) < 4:
        return [], [Diagnostic("INSUFFICIENT_DISTINCT_X", f"harmonic k={index} needs four distinct x")]
    span = max(xs) - min(xs)
    if span <= 0:
        return [], [Diagnostic("DEGENERATE_SPAN", f"harmonic k={index} needs a positive span")]
    raw = 2 * math.pi * index / span
    text = _decimal(raw, FREQUENCY_DIGITS)
    omega = float(text)
    spacing = span / (len(xs) - 1)
    diagnostics = [Diagnostic("FIXED_PRECISION_FREQUENCY",
        f"k={index} T={span!r} omega_raw={raw!r} omega={text} digits={FREQUENCY_DIGITS}")]
    if omega * spacing >= math.pi:
        diagnostics.append(Diagnostic("ALIASING_RISK", f"omega*spacing={omega * spacing!r} reaches pi"))
    _, _, ybar, yscale = _summary(request)
    # 頻率字典定義在原始 x 軸，相位不再中心化，擬合與 AST 的 `sin(param omega * var x)` 必須是同一條式子。
    result = solve([[1.0, math.sin(omega * row[0]), math.cos(omega * row[0])] for row in request.fit],
                   [(row[1] - ybar) / yscale for row in request.fit])
    if result.coefficients is None:
        diagnostics.append(Diagnostic("RANK_DEFICIENT", f"harmonic k={index} rank {result.rank} of {result.columns}"))
        return [], diagnostics
    intercept, sine, cosine = result.coefficients
    terms: list[JsonObject] = []
    parameters: list[JsonObject] = []
    values: dict[str, str] = {}
    for power, value in ((0, ybar + yscale * intercept), (1, yscale * sine), (2, yscale * cosine)):
        coefficient = _decimal(value, COEFFICIENT_DIGITS)
        if coefficient == "0":
            continue
        name = f"c{power}"
        parameters.append(_parameter(name, _coefficient_unit(request.target_unit, 0, request.variable.unit), coefficient))
        values[name] = coefficient
        if power == 0:
            terms.append({"op": "param", "name": name})
        else:
            unary = "sin" if power == 1 else "cos"
            terms.append({"op": "mul", "args": [{"op": "param", "name": name},
                {"op": unary, "args": [{"op": "mul", "args": [{"op": "param", "name": "omega"}, {"op": "var", "name": request.variable.name}]}]}]})
    root = _root(terms)
    if root is None:
        diagnostics.append(Diagnostic("DEGENERATE_MODEL", f"harmonic k={index} collapsed to zero"))
        return [], diagnostics
    parameters.append(_parameter("omega", _frequency_unit(request.variable.unit), text))
    values["omega"] = text
    return [_proposal(request, f"harmonic-fit:k={index}", parameters, values, root, result.columns, result.pivots)], diagnostics


# 三家族共用同一介面；LINEAR 只有單一變體，propose 依約定忽略 variant index。
STRATEGIES: tuple[Strategy, ...] = (
    Strategy(LINEAR, MANIFESTS[0], ((0, "linear-fit"),), lambda request, _index: _linear(request)),
    Strategy(POLYNOMIAL, MANIFESTS[1], ((2, "degree-2"), (3, "degree-3")), _polynomial),
    Strategy(HARMONIC, MANIFESTS[2], ((1, "k=1"), (2, "k=2"), (3, "k=3")), _harmonic))


def _cost(manifest_value: Manifest, proposal: Proposal, development_rows: int) -> JsonObject:
    return {"fit_rows": proposal.fit_rows, "unknowns": proposal.unknowns, "pivots": proposal.pivots,
        "nodes": proposal.plan.node_count, "development_rows": development_rows,
        "timeout_seconds": manifest_value.timeout_seconds, "memory_bytes": manifest_value.memory_bytes,
        "resource_class": manifest_value.resource_class}


def _cost_key(cost: JsonObject) -> tuple[int, int, int, int, int, int, int, str]:
    return (cost["fit_rows"], cost["unknowns"], cost["pivots"], cost["nodes"], cost["development_rows"],
            cost["timeout_seconds"], cost["memory_bytes"], cost["resource_class"])


def propose_family(request: Request, registered: Strategy) -> tuple[list[Proposal], list[Diagnostic]]:
    """同一族變體依 registry 原序提出候選；拒用診斷與數值順序保持不變。"""
    diagnostics: list[Diagnostic] = []
    selected: list[Proposal] = []
    for index, _label in registered.variants:
        try:
            produced, notes = registered.propose(request, index)
        except DslError as error:
            diagnostics.extend([Diagnostic(error.code, f"{registered.family} variant {index} rejected")])
            continue
        selected.extend(produced)
        diagnostics.extend(notes)
    return selected, diagnostics


def development_score(request: Request, plan: Plan, parameters: dict[str, str]) -> JsonObject | None:
    """development 只評分，不參與擬合；空分區沿用明確的無分數輸出。"""
    return None if not request.development else score(plan, parameters, request.variable.name, list(request.development))


def search(request: Request, families: tuple[str, ...] | None = None) -> JsonObject:
    """在 fit 上擬合、只在 development 上評分，回傳帶診斷與成本形狀的確定性候選順序。"""
    require(len(request.variable.unit) == 7 and len(request.target_unit) == 7, UNIT_ERROR)
    require(bool(request.fit), LIMIT)
    require(len(request.fit) + len(request.development) <= MAX_ROWS, LIMIT)
    strategies: list[JsonObject] = []
    origins: dict[str, list[tuple[str, JsonObject]]] = {}
    plans: dict[str, Plan] = {}
    bindings: dict[str, dict[str, str]] = {}
    proposed = 0
    for registered in STRATEGIES:
        if families is not None and registered.family not in families:
            continue
        selected, diagnostics = propose_family(request, registered)
        proposed += len(selected)
        for proposal in selected:
            identity = proposal.plan.identity_hash
            plans.setdefault(identity, proposal.plan)
            bindings.setdefault(identity, proposal.parameters)
            # 成本帳共用同一個 _cost 出口，三個家族不各自複製欄位形狀。
            origins.setdefault(identity, []).append((proposal.source,
                _cost(registered.manifest, proposal, len(request.development))))
        strategies.append(registered.manifest.document() | {"family": registered.family,
            "status": EXECUTED if selected else NOT_APPLICABLE, "proposed_count": len(selected),
            "diagnostics": [note.document() for note in diagnostics]})
    ranking: list[tuple[tuple[object, ...], JsonObject]] = []
    for identity, sources in origins.items():
        development = development_score(request, plans[identity], bindings[identity])
        ordered = sorted(sources, key=lambda entry: (entry[0], _cost_key(entry[1])))
        cost = min((entry[1] for entry in ordered), key=_cost_key)
        entry: JsonObject = {"identity_hash": identity, "dsl": json.loads(plans[identity].canonical),
            "node_count": plans[identity].node_count, "cost_shape": cost, "development": development,
            "origins": [{"source": source, "cost_shape": shape} for source, shape in ordered]}
        error = development["mae"] if development is not None and development["mae"] is not None else math.inf
        ranking.append(((float(error), plans[identity].node_count, _cost_key(cost), identity), entry))
    ranking.sort(key=lambda item: item[0])
    report: JsonObject = {"policy_version": POLICY, "usage_scope": USAGE_SCOPE, "product_status": PRODUCT_STATUS,
        "precision_bits": PRECISION_BITS, "fit_rows": len(request.fit), "development_rows": len(request.development),
        "proposed_count": proposed, "duplicate_count": proposed - len(origins),
        "strategies": strategies, "candidates": [entry for _, entry in ranking]}
    if not request.development:
        return report | {"diagnostics": [Diagnostic("EMPTY_DEVELOPMENT",
            "development partition is empty; candidates carry no score and keep the deterministic tie-break").document()]}
    return report | {"diagnostics": []}


def merge_reports(reports: Sequence[dict[str, object]]) -> dict[str, object]:
    """合併已完成策略的持久報告，跨族去重與排序完全沿用完整搜尋口徑。"""
    require(bool(reports), "INVALID_SCHEMA")
    # 報告僅由本模組產生並經 checkpoint checksum 保護；重新編譯仍驗 DSL 身分。
    merged = json.loads(canonical_bytes(reports[0]))
    unique: dict[str, dict[str, object]] = {}
    for report in reports:
        entries = json.loads(canonical_bytes(report))["candidates"]
        for entry in entries:
            plan = compile_dsl(canonical_bytes(entry["dsl"]))
            require(plan.identity_hash == entry["identity_hash"], "INVALID_SCHEMA")
            identity = plan.identity_hash
            if identity in unique:
                combined = json.loads(canonical_bytes(unique[identity]))
                combined["origins"].extend(entry["origins"])
                unique[identity] = combined
            else:
                unique[identity] = json.loads(canonical_bytes(entry))
    for identity, value in unique.items():
        entry = json.loads(canonical_bytes(value))
        entry["origins"] = sorted(entry["origins"], key=lambda origin: (origin["source"], _cost_key(origin["cost_shape"])))
        entry["cost_shape"] = min((origin["cost_shape"] for origin in entry["origins"]), key=_cost_key)
        unique[identity] = entry
    def ranking(entry: dict[str, object]) -> tuple[object, ...]:
        value = json.loads(canonical_bytes(entry))
        development = value["development"]
        error = development["mae"] if development is not None and development["mae"] is not None else math.inf
        return (float(error), value["node_count"], _cost_key(value["cost_shape"]), value["identity_hash"])
    merged["candidates"] = sorted(unique.values(), key=ranking)
    merged["strategies"] = [strategy for report in reports for strategy in json.loads(canonical_bytes(report))["strategies"]]
    merged["proposed_count"] = sum(int(json.loads(canonical_bytes(report))["proposed_count"]) for report in reports)
    merged["duplicate_count"] = merged["proposed_count"] - len(unique)
    return merged
