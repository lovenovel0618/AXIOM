"""可信解析程序中的時間／群組防洩漏檢查；不向公開報告輸出 final 欄位。"""
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from collections.abc import Sequence
from ingestion.limits import require
from sealing.types import sequence
from runtime.budget_types import integer, object_fields
from runtime.contracts import identity_hash


def group_token(value: object) -> str:
    """字串識別不猜數字含義；數值用精確有理數跨格式正規化。"""
    if isinstance(value, str):
        require(bool(value) and len(value) <= 4096)
        return "s:" + value
    require(type(value) is int or isinstance(value, (float, Decimal)))
    number = Fraction(str(value))
    return f"n:{number.numerator}/{number.denominator}"


def time_value(value: object) -> Fraction:
    """有限數值時間或 ISO 日期／帶時區時間轉精確座標，拒絕不明時區 timestamp。"""
    require(not isinstance(value, bool) and isinstance(value, (str, int, float, Decimal)))
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        require(isinstance(value, str) and len(value) <= 256)
        text = str(value)
        if len(text) == 10:
            timestamp = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        else:
            timestamp = datetime.fromisoformat(text)
            require(timestamp.tzinfo is not None)
        delta = timestamp.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1000000)


class DependencyGuard:
    """固定列集合與逐列相依性驗證；bad 只作遮罩，不洩漏錯誤的 final row。"""
    def __init__(self, profile: object, split: object, count: int) -> None:
        self.profile, self.split = object_fields(profile), object_fields(split)
        self.kind = str(self.split["kind"])
        self.members = {integer(row): role for role in ("fit", "development", "final_test") for row in sequence(self.split[role])}
        total = sum(len(sequence(self.split[role])) for role in ("fit", "development", "final_test"))
        require(total == len(self.members) and all(0 <= row < count for row in self.members))
        self.groups: dict[str, str] = {}
        self.assignments: list[list[int | str]] = []
        self.previous: Fraction | None = None
        self.bad = False
        if self.kind == "TIME_ORDERED":
            gap = integer(self.split["gap_rows"])
            require(gap >= integer(self.split["lookback_rows"]) + integer(self.split["horizon_rows"]))
            previous_end = -gap - 1
            for role in ("fit", "development", "final_test"):
                rows = [integer(row) for row in sequence(self.split[role])]
                require(bool(rows) and rows == list(range(rows[0], rows[-1] + 1)))
                require(rows[0] == previous_end + gap + 1)
                previous_end = rows[-1]
            require(previous_end == count - 1 and total + 2 * gap == count)
        else:
            require(total == count and set(self.members) == set(range(count)))

    def observe(self, index: int, names: list[str], values: Sequence[object]) -> None:
        """全部來源列都經檢查；gap 列只檢查時間，不參與學習或評分。"""
        try:
            if self.kind == "TIME_ORDERED":
                column = str(self.split["time_column"])
                require(column in names)
                current = time_value(values[names.index(column)])
                require(self.previous is None or current > self.previous)
                self.previous = current
            elif self.kind == "GROUPED_ROWS":
                column = str(self.profile["group_column"])
                require(column in names and index in self.members)
                group = group_token(values[names.index(column)])
                role = self.members[index]
                require(group not in self.groups or self.groups[group] == role)
                self.groups[group] = role
                self.assignments.append([index, group, role])
        except (ValueError, TypeError, OverflowError):
            self.bad = True

    def valid(self) -> bool:
        """群組 digest 只有完整掃描後才可判定；公開結果只保留 PASS／BLOCKED。"""
        return not self.bad and (self.kind != "GROUPED_ROWS" or identity_hash(self.assignments) == self.split["group_assignment_digest"])
