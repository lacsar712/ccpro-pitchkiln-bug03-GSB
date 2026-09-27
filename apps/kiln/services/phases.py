"""相位枚举与聚合的唯一出口。

图例计数、整页筛选、HTMX 局部网格三路都必须经过本模块：
枚举只认 ``FireHearth.PHASE_CHOICES``，聚合只有 :func:`group_hearths_by_phase`，
任何一路都不得自行维护「某入参映射到某相位」的表。
"""
from collections import OrderedDict

from apps.kiln.models import FireHearth

# 入参（枚举键或中文标签）→ 枚举键。由 PHASE_CHOICES 派生，不另写映射。
PHASE_ALIASES = {
    **{key: key for key, _ in FireHearth.PHASE_CHOICES},
    **{label: key for key, label in FireHearth.PHASE_CHOICES},
}


def normalize_phase(phase_raw):
    """把筛选入参规范化为合法枚举键；空值或无法识别时返回 None。"""
    if not phase_raw:
        return None
    return PHASE_ALIASES.get(phase_raw.strip())


def group_hearths_by_phase(hearths):
    """把灶台按当前相位分桶。

    返回 OrderedDict，键与顺序完全取自 ``FireHearth.PHASE_CHOICES``，
    每个键都保证存在（空桶为空列表）。图例计数与筛选瓦片都从这里取，
    因此三路天然对齐、不可能跨桶（出胶不会混进保温）。
    """
    buckets = OrderedDict(
        (key, []) for key, _ in FireHearth.PHASE_CHOICES
    )
    for hearth in hearths:
        bucket = buckets.get(hearth.phase)
        if bucket is not None:
            bucket.append(hearth)
    return buckets


def build_legend(buckets):
    """从同一分桶结果生成图例 (key, label, count)。"""
    return [
        (key, label, len(buckets[key]))
        for key, label in FireHearth.PHASE_CHOICES
    ]
