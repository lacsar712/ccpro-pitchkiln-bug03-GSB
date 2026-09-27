"""图例计数 / 整页筛选 / HTMX 局部网格三路对齐测试。

任何一路（图例、整页、局部）对不齐，这些测试就会挂。
"""
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.kiln.models import CookRun, FireHearth, ResinLot, SoftPointProbe
from apps.kiln.services.board import aggregate_hearths, board_view, normalize_phase

PHASE_LABELS = dict(FireHearth.PHASE_CHOICES)


def tile_count(html, phase=None):
    """统计渲染出的瓦片数（可按相位 class 限定）。"""
    if phase:
        return len(re.findall(rb'class="hearth-tile phase-%s"' % phase.encode(), html))
    return html.count(b'class="hearth-tile')


def legend_count(html, phase):
    """从图例片段中抓「<中文标签> N」的数字。"""
    label = PHASE_LABELS[phase]
    m = re.search((label + r"\s+(\d+)").encode(), html)
    assert m, f"图例中找不到 {label}"
    return int(m.group(1))


class BoardAlignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tester", password="x")
        # 每个相位各放 2 个灶，共 10 个。
        for i, (key, _) in enumerate(FireHearth.PHASE_CHOICES):
            for n in range(2):
                FireHearth.objects.create(
                    lane=i + 1, tag=f"{key}-{n}", resinGrade="X", phase=key
                )

    def setUp(self):
        self.client.force_login(self.user)

    def test_aggregate_is_single_source_of_truth(self):
        # 服务层：每个图例计数必须等于该组的灶台数。
        groups, counts = aggregate_hearths(FireHearth.objects.all())
        for key, _ in FireHearth.PHASE_CHOICES:
            self.assertEqual(counts[key], len(groups[key]))
            self.assertEqual(counts[key], 2)

    def test_each_legend_count_matches_full_page_and_partial_grid(self):
        for key, _ in FireHearth.PHASE_CHOICES:
            with self.subTest(phase=key):
                page = self.client.get("/", {"phase": key}).content
                partial = self.client.get(
                    "/floor/grid/", {"phase": key}, HTTP_HX_REQUEST="true"
                ).content

                expected = legend_count(page, key)
                self.assertEqual(expected, 2)
                # 整页筛选后的瓦片数
                self.assertEqual(tile_count(page, key), expected)
                self.assertEqual(tile_count(page), expected)
                # HTMX 局部网格必须应用同一个筛选
                self.assertEqual(tile_count(partial, key), expected)
                self.assertEqual(tile_count(partial), expected)
                # 图例 partial 计数一致
                legend = self.client.get("/floor/legend/", {"phase": key}).content
                self.assertEqual(legend_count(legend, key), expected)

    def test_drawing_filter_never_includes_holding(self):
        page = self.client.get("/", {"phase": "drawing"}).content
        partial = self.client.get("/floor/grid/", {"phase": "drawing"}).content
        self.assertEqual(tile_count(page, "holding"), 0)
        self.assertEqual(tile_count(partial, "holding"), 0)
        self.assertEqual(tile_count(page, "drawing"), 2)
        self.assertEqual(tile_count(partial, "drawing"), 2)

    def test_legend_keeps_drawing_and_holding_separate(self):
        page = self.client.get("/").content
        self.assertEqual(legend_count(page, "drawing"), 2)
        self.assertEqual(legend_count(page, "holding"), 2)

    def test_invalid_phase_filter_is_ignored(self):
        self.assertEqual(normalize_phase("bogus"), "")
        page = self.client.get("/", {"phase": "bogus"}).content
        self.assertEqual(tile_count(page), FireHearth.objects.count())

    def test_unknown_phase_does_not_inflate_any_legend_bucket(self):
        FireHearth.objects.filter(phase=FireHearth.PHASE_COLD).update(
            phase="bogus-phase"
        )
        page = self.client.get("/").content
        self.assertEqual(legend_count(page, "cold"), 0)
        # 不筛选时脏数据灶仍然显示，但不会被任何合法筛选捞到
        self.assertEqual(tile_count(page), FireHearth.objects.count())
        self.assertEqual(tile_count(self.client.get("/", {"phase": "cold"}).content), 0)

    def test_full_board_view_shows_everything_unfiltered(self):
        ctx = board_view(list(FireHearth.objects.all()), "")
        self.assertEqual(len(ctx["hearths"]), 10)
        self.assertEqual(
            sum(c for _, _, c in ctx["phase_legend"]), 10
        )

    def test_legend_and_grid_refresh_after_phase_change(self):
        hearth = FireHearth.objects.get(tag="holding-0")
        lot = ResinLot.objects.create(
            lotCode="L1",
            originPlace="N",
            arrivalKg=Decimal("100"),
            receivedAt=timezone.now(),
        )
        run = CookRun.objects.create(
            hearth=hearth,
            resinLot=lot,
            openedAt=timezone.now(),
            targetSoftPointC=Decimal("90"),
        )
        SoftPointProbe.objects.create(
            run=run,
            sampledAt=timezone.now(),
            softPointC=Decimal("90"),
            samplerName="s",
        )

        resp = self.client.post(
            f"/hearth/{hearth.pk}/phase/",
            {"phase": FireHearth.PHASE_DRAWING},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["HX-Trigger"], "floor-refresh")
        hearth.refresh_from_db()
        self.assertEqual(hearth.phase, FireHearth.PHASE_DRAWING)

        # floor-refresh 后浏览器重拉的两个 partial：计数必须迁移
        legend = self.client.get("/floor/legend/").content
        grid = self.client.get("/floor/grid/").content
        self.assertEqual(legend_count(legend, "holding"), 1)
        self.assertEqual(legend_count(legend, "drawing"), 3)
        self.assertEqual(tile_count(grid, "holding"), 1)
        self.assertEqual(tile_count(grid, "drawing"), 3)
