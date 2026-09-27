"""灶台看板的相位聚合 —— 图例计数、整页筛选、HTMX 局部网格三路共用。

唯一事实来源：
- 相位枚举：FireHearth.PHASE_CHOICES（不另建别名表，出胶 drawing 不再并入保温 holding）。
- 分组与计数：aggregate_hearths()，一次聚合同时产出 legend 计数与筛选分组，
  保证「图例上的数字」必然等于「点筛选后看到的瓦片数」。
"""
from collections import OrderedDict

from apps.kiln.models import FireHearth

PHASE_KEYS = [key for key, _ in FireHearth.PHASE_CHOICES]
PHASE_LABELS = OrderedDict(FireHearth.PHASE_CHOICES)


def normalize_phase(phase_raw):
    """把筛选参数归一化为合法相位 key；空值或非法值返回 ''（即不筛选）。"""
    if not phase_raw:
        return ""
    phase_raw = phase_raw.strip()
    return phase_raw if phase_raw in PHASE_LABELS else ""


def aggregate_hearths(hearths):
    """按相位枚举对灶台分组并计数。

    返回 (groups, counts)：
    - groups: OrderedDict，key 顺序与 PHASE_CHOICES 完全一致，值为灶台列表；
    - counts: 与 groups 同一份分组推导出的计数。

    未知相位（历史脏数据等）不静默塞进任何一组，归入 groups[""]，
    既不污染任何图例数字，也不会被任何合法筛选漏出来。
    """
    groups = OrderedDict((key, []) for key in PHASE_KEYS)
    groups[""] = []
    for h in hearths:
        groups.setdefault(h.phase if h.phase in PHASE_LABELS else "", []).append(h)

    counts = {key: len(groups[key]) for key in PHASE_KEYS}
    return groups, counts


def legend_items(counts):
    """由聚合计数生成图例 (key, label, count)，顺序跟随 PHASE_CHOICES。"""
    return [(key, PHASE_LABELS[key], counts.get(key, 0)) for key in PHASE_KEYS]


def board_view(hearths, phase_filter=""):
    """看板三路统一入口：聚合一一次，图例与筛选取自同一结果。"""
    phase = normalize_phase(phase_filter)
    groups, counts = aggregate_hearths(hearths)
    # 不筛选时展示全部（含历史脏相位灶）；筛选时只取该枚举组，
    # 因此出胶组绝不可能混进保温灶。
    visible = groups[phase] if phase else list(hearths)

    lanes = OrderedDict()
    for h in visible:
        lanes.setdefault(h.lane, []).append(h)

    return {
        "hearths": visible,
        "lanes": sorted(lanes.items()),
        "phase_legend": legend_items(counts),
        "phase_filter": phase,
    }
