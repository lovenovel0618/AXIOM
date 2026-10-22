"""Metadata-only draft checks; no observations or final labels are read here."""
from fractions import Fraction
from uuid import UUID, uuid4
from runtime.contracts import JsonObject, identity_hash
from catalog.validation import ApiError

PARTITIONS = ("fit", "development", "final_test")
HASH_FIELDS = PARTITIONS + ("gap_rows", "lookback_rows", "horizon_rows")
INVALID_POLICY = "EVALUATION_POLICY_INVALID"


def require(condition: bool, code: str = "INVALID_SCHEMA") -> None:
    """把語意確認的失敗統一轉為穩定 API 錯誤，不回傳來源細節。"""
    if not condition:
        raise ApiError(code, 422)


def decimal(value: str, code: str) -> Fraction:
    # Bound work before int conversion; the HTTP envelope is also bounded at 64 KiB.
    """精確解析有界十進位宣告，避免先轉 float 丟失單位或邊界精度。"""
    require(len(value) <= 256, code)
    return Fraction(value)


def mappings(profile: JsonObject, columns: set[str]) -> None:
    """確認欄位角色、來源名稱及單位宣告一致，不自行猜測時間／特徵語意。"""
    source, target = profile["inputs"][0], profile["target"]
    for item in (source, target):
        require(item["source_column"] in columns, "SOURCE_COLUMN_NOT_FOUND")
        conversion = item["conversion"]
        require(bool(conversion["source_unit"].strip()), "UNIT_CONVERSION_INVALID")
        require(decimal(conversion["scale"], "UNIT_CONVERSION_INVALID") > 0, "UNIT_CONVERSION_INVALID")
        decimal(conversion["offset"], "UNIT_CONVERSION_INVALID")
    require(source["source_column"] != target["source_column"] and source["name"] != target["name"], "SOURCE_COLUMN_CONFLICT")
    require(bool(profile["resolution_reason"].strip()))
    if profile["measurement_resolution"] is not None:
        require(decimal(profile["measurement_resolution"], "UNIT_CONVERSION_INVALID") > 0, "UNIT_CONVERSION_INVALID")
    if profile["group_column"] is not None:
        require(profile["group_column"] in columns, "SOURCE_COLUMN_NOT_FOUND")


def domain_check(data: JsonObject) -> None:
    """核對 canonical 域、輸入及輸出量綱；宣告不能與語意映射矛盾。"""
    domain = data["domain"][0]
    require(domain["name"] == data["semantic_profile"]["inputs"][0]["name"])
    endpoints: list[Fraction] = []
    for name in ("lower", "upper"):
        bound = domain[name]
        value = Fraction(int(bound["numerator"]), int(bound["denominator"]))
        require(str(value.numerator) == bound["numerator"] and str(value.denominator) == bound["denominator"])
        endpoints.append(value)
    require(endpoints[0] < endpoints[1] or (endpoints[0] == endpoints[1] and domain["lower_closed"] and domain["upper_closed"]))


def policy_check(policy: JsonObject, profile: JsonObject, split: JsonObject) -> None:
    """驗證評估政策與研究配置一致，未支援的正式能力不得偷偷啟用。"""
    for name in ("absolute_error_bound", "practical_scale_override"):
        if policy[name] is not None:
            require(decimal(policy[name], INVALID_POLICY) > 0, INVALID_POLICY)
    require(0 < decimal(policy["practical_margin_ratio"], INVALID_POLICY) <= 1, INVALID_POLICY)
    if policy["practical_scale_reason"] is not None:
        require(bool(policy["practical_scale_reason"].strip()), INVALID_POLICY)
    method = policy["comparison_method"]
    if profile["group_column"] is not None:
        require(method == "NONE", INVALID_POLICY)
    elif profile["time_ordered"]:
        require(method != "IID_PAIRED_BOOTSTRAP", INVALID_POLICY)
    else:
        require(method != "BLOCK_BOOTSTRAP", INVALID_POLICY)
    if method == "BLOCK_BOOTSTRAP":
        require(policy["block_length"] < len(split["development"]), INVALID_POLICY)


def dependencies(profile: JsonObject, split: JsonObject) -> None:
    """檢查時間／群組與 refit 依賴；當期未實作能力以明確拒絕維持邊界。"""
    grouped, timed = profile["group_column"] is not None, profile["time_ordered"]
    require(not (grouped and timed))
    require(timed == (split["kind"] == "TIME_ORDERED"))
    require(grouped == (split["kind"] == "GROUPED_ROWS"))
    require(split["group_column"] == profile["group_column"])
    if not timed:
        require(split["time_column"] is None)
    if not grouped:
        require(split["group_assignment_digest"] is None)
    if grouped or timed:
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    require(all(split[name] == 0 for name in ("gap_rows", "lookback_rows", "horizon_rows")))


def iid_rows(count: int, seed: int) -> JsonObject:
    """依固定 seed 與雜湊重算 IID 切分，不能把任意列集合冒充隨機切分。"""
    require(count >= 5, "INSUFFICIENT_DATA")
    # Public deterministic partitioning, independent of interpreter PRNG versions.
    rows = sorted(range(count), key=lambda row: (identity_hash(["axiom-iid-sha256-v1", seed, row]), row))
    fit_end, dev_end = count * 3 // 5, count * 4 // 5
    return {"fit": sorted(rows[:fit_end]), "development": sorted(rows[fit_end:dev_end]), "final_test": sorted(rows[dev_end:])}


def split_check(data: JsonObject, count: int) -> JsonObject:
    """每列恰好屬於一區且完整覆蓋，不交疊、不丟列，也不以重編列號隱藏資料。"""
    split = dict(data["observation_split"])
    require(UUID(split["dataset_version_id"]) == UUID(data["dataset_version_id"]))
    split["dataset_version_id"] = str(UUID(split["dataset_version_id"]))
    rows: list[int] = [row for name in PARTITIONS for row in split[name]]
    require(len(rows) == len(set(rows)) and all(row < count for row in rows))
    # Non-temporal drafts have no gap: every source observation must be assigned.
    if split["kind"] in {"IID_ROWS", "EXPLICIT"}:
        require(len(rows) == count)
    for name in PARTITIONS:
        split[name] = sorted(split[name])
    if split["kind"] == "IID_ROWS":
        require(split["splitter_version"] == "axiom-iid-sha256-v1")
        expected = iid_rows(count, split["seed"])
        require(all(split[name] == expected[name] for name in PARTITIONS))
    else:
        require(bool(split["splitter_version"].strip()))
    split.update(id=str(uuid4()), row_ids_hash=identity_hash({name: split[name] for name in HASH_FIELDS}), sealed_test_id=None, benchmark_partition_id=None, benchmark_case_id=None)
    return split


def confirm(data: JsonObject, metadata: JsonObject) -> JsonObject:
    """將人工設定與來源 metadata 對照，固定可重現切分，無需讀取觀測值。"""
    profile, split = data["semantic_profile"], data["observation_split"]
    mappings(profile, {column["name"] for column in metadata["columns"]})
    domain_check(data)
    policy_check(data["evaluation_policy"], profile, split)
    dependencies(profile, split)
    if data.get("refit_policy") is not None:
        raise ApiError("DEPENDENCY_UNAVAILABLE", 503)
    return split_check(data, metadata["row_count"])
