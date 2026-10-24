"""凍結評估政策的離線比較：決定性配對 bootstrap 區間與實務等效邊界。

Offline comparison for a frozen evaluation policy: a deterministic paired bootstrap interval
over matched per-row losses, plus the practical-equivalence margin that turns the interval
into `outcome_status`.

本模組只做純計算，不讀資料庫也不碰曝光。重抽樣索引由 `RESAMPLING`、`bootstrap_seed`、replicate
與 draw 的雜湊導出，與直譯器 PRNG 版本無關，因此同一政策與同一批列在任何環境都得到同一組索引、
同一區間與同一結論；判定不必另存他處即可重算。"""
import math
from collections.abc import Sequence
from fractions import Fraction
from typing import Literal
from mathematics.metrics import quantile
from runtime.contracts import identity_hash

RESAMPLING = "axiom-paired-bootstrap-sha256-v1"
LOWER_QUANTILE = Fraction(1, 40)
UPPER_QUANTILE = Fraction(39, 40)
Outcome = Literal["SUPPORTED", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE", "FALSIFIED"]


def scale(iqr: Fraction, resolution: Fraction, override: str | None) -> Fraction | None:
    """實務尺度取 max(IQR(y_fit), 量測解析度)；兩者皆零時只認預先註冊的正覆寫值。

    量測解析度不自動當成誤差上界，只在此處參與尺度；零尺度無覆寫即無可比較的尺度。"""
    value = max(iqr, resolution)
    if value > 0:
        return value
    return None if override is None else Fraction(override)


def bound(scale_value: Fraction, ratio: Fraction) -> Fraction:
    """實務邊界為尺度乘上政策比例；比例已於建立版本時限定在 (0,1]。"""
    return scale_value * ratio


def baseline_losses(prediction: Fraction, targets: Sequence[float]) -> list[float]:
    """baseline 模型的逐列絕對誤差：以固定預測值（零或 fit 均值）對每列目標評分。"""
    value = float(prediction)
    return [abs(value - target) for target in targets]


def interval(candidate: Sequence[float], baseline: Sequence[float], seed: int, replicates: int) -> tuple[Fraction, Fraction]:
    """對逐列 loss 差做有放回配對重抽樣，回 95% 百分位區間。

    候選與 baseline 使用同一組索引，因此統計量是配對差而非兩組獨立平均；索引由 `RESAMPLING`
    與 seed、replicate、draw 的雜湊決定，故不依賴直譯器 PRNG，也不受抽樣呼叫順序影響。"""
    differences = [candidate_value - baseline_value for candidate_value, baseline_value in zip(candidate, baseline, strict=True)]
    count = len(differences)
    means: list[Fraction] = []
    for replicate in range(replicates):
        drawn = [differences[int(identity_hash([RESAMPLING, seed, replicate, draw]), 16) % count] for draw in range(count)]
        means.append(Fraction(math.fsum(drawn) / count))
    ordered = sorted(means)
    return quantile(ordered, LOWER_QUANTILE), quantile(ordered, UPPER_QUANTILE)


def classify(lower: Fraction, upper: Fraction, margin: Fraction) -> Outcome:
    """區間對 [-margin, +margin] 的位置決定結論；跨越邊界即無法下結論。

    區間全低於 -margin 才算候選損失較低；全高於 +margin 反證候選較差；全落在帶內只能稱在指定
    容差內等效。含 0 但超出帶外的區間不足以下任何結論，因為帶寬才是實務尺度。"""
    if upper < -margin:
        return "SUPPORTED"
    if lower > margin:
        return "FALSIFIED"
    if lower >= -margin and upper <= margin:
        return "AMBIGUOUS"
    return "INSUFFICIENT_EVIDENCE"
