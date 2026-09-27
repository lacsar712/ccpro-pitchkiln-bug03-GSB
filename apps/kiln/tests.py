import pathlib
import re

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.kiln.models import FireHearth
from apps.kiln.seed import ensure_seed_data
from apps.kiln.services.phases import (
    PHASE_ALIASES,
    build_legend,
    group_hearths_by_phase,
    normalize_phase,
)

TILE_RE = re.compile(r'class="hearth-tile phase-(\w+)"')
LEG_RE = re.compile(r'class="leg phase-(\w+)[^"]*"[^>]*>\s*<i></i>([^<]*)</a>')


def tile_phases(html):
    return TILE_RE.findall(html)


def legend_counts(html):
    """从渲染后的图例抓 {phase_key: count}。"""
    counts = {}
    for key, body in LEG_RE.findall(html):
        m = re.search(r"(\d+)\s*$", body.strip())
        counts[key] = int(m.group(1)) if m else 0
    return counts


class PhaseAlignmentTests(TestCase):
    """图例计数 / 整页筛选 / HTMX 局部网格必须三路对齐。"""

    @classmethod
    def setUpTestData(cls):
        ensure_seed_data()
        cls.user = get_user_model().objects.get(username="admin")

    def setUp(self):
        self.client.force_login(self.user)

    # —— 聚合函数本身：计数 == 分桶长度，出胶/保温互不混入 ——

    def test_aggregation_buckets_match_legend(self):
        hearths = list(FireHearth.objects.all())
        buckets = group_hearths_by_phase(hearths)
        legend = dict((k, c) for k, _label, c in build_legend(buckets))
        for key, _label in FireHearth.PHASE_CHOICES:
            self.assertEqual(legend[key], len(buckets[key]))
        self.assertEqual(sum(legend.values()), len(hearths))

    def test_drawing_and_holding_are_distinct_buckets(self):
        buckets = group_hearths_by_phase(FireHearth.objects.all())
        drawing = {h.tag for h in buckets["drawing"]}
        holding = {h.tag for h in buckets["holding"]}
        self.assertIn("坑火-西一", drawing)
        self.assertFalse(drawing & holding)

    def test_normalize_phase_accepts_keys_and_chinese_labels(self):
        for key, label in FireHearth.PHASE_CHOICES:
            self.assertEqual(normalize_phase(key), key)
            self.assertEqual(normalize_phase(label), key)
            self.assertEqual(PHASE_ALIASES[key], key)
        self.assertIsNone(normalize_phase(""))
        self.assertIsNone(normalize_phase("bogus"))

    # —— 三路对齐：每个相位，图例数 == 整页瓦片数 == 局部网格瓦片数 ——

    def test_three_paths_stay_aligned_for_every_phase(self):
        full = self.client.get("/").content.decode()
        expected = legend_counts(full)

        for key, _label in FireHearth.PHASE_CHOICES:
            page = self.client.get(f"/?phase={key}").content.decode()
            partial = self.client.get(
                f"/floor/grid/?phase={key}", HTTP_HX_REQUEST="true"
            ).content.decode()

            page_tiles = tile_phases(page)
            partial_tiles = tile_phases(partial)

            # 筛出胶不能混进保温灶：出现的瓦片相位必须全部等于所选相位
            wanted = {key} if expected[key] else set()
            self.assertEqual(set(page_tiles), wanted)
            self.assertEqual(set(partial_tiles), wanted)
            # 三路张数相等
            self.assertEqual(len(page_tiles), expected[key], key)
            self.assertEqual(len(partial_tiles), expected[key], key)
            # 局部响应里的图例计数也必须与整页一致
            self.assertEqual(legend_counts(partial), expected)

    def test_chinese_label_filter_aligns(self):
        for key, label in FireHearth.PHASE_CHOICES:
            page = self.client.get(f"/?phase={label}").content.decode()
            tiles = tile_phases(page)
            self.assertEqual(set(tiles), {key} if tiles else set())

    def test_unknown_filter_is_empty_but_legend_keeps_full_counts(self):
        html = self.client.get("/?phase=bogus").content.decode()
        self.assertEqual(tile_phases(html), [])
        self.assertEqual(
            sum(legend_counts(html).values()), FireHearth.objects.count()
        )

    # —— 图例随 floor-refresh 在局部响应中 OOB 刷新 ——

    def test_partial_carries_oob_legend_full_page_does_not(self):
        partial = self.client.get(
            "/floor/grid/", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn('id="phase-legend"', partial)
        self.assertIn('hx-swap-oob="true"', partial)

        full = self.client.get("/").content.decode()
        self.assertIn('id="phase-legend"', full)
        self.assertNotIn("hx-swap-oob", full)

    def test_legend_refreshes_after_phase_change(self):
        ramping = FireHearth.objects.get(tag="坳火-乙")
        before = self.client.get(
            "/floor/grid/", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertEqual(legend_counts(before)["ramping"], 1)

        resp = self.client.post(
            f"/hearth/{ramping.pk}/phase/",
            {"phase": FireHearth.PHASE_HOLDING},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp["HX-Trigger"], "floor-refresh")

        # floor-refresh 触发的局部刷新（在保温筛选下同样对齐）
        after = self.client.get(
            "/floor/grid/?phase=holding", HTTP_HX_REQUEST="true"
        ).content.decode()
        counts = legend_counts(after)
        self.assertEqual(counts["holding"], 2)
        self.assertEqual(counts["ramping"], 0)
        self.assertEqual(set(tile_phases(after)), {"holding"})
        self.assertEqual(len(tile_phases(after)), counts["holding"])

    # —— 模板不得写死计数 ——

    def test_templates_have_no_hardcoded_counts(self):
        tpl_dir = pathlib.Path(__file__).resolve().parents[2] / "templates"
        for path in tpl_dir.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                text,
                r"(出胶|保温|升温|装料|冷灶)\s*\d",
                f"{path} 里疑似写死了图例数字",
            )
