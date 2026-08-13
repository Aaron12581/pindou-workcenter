import io
import zipfile

from PIL import Image

from app.mard_palette import MARD_STANDARD_PALETTE
from app.pattern_engine import generate_pattern
from app.pattern_exporter import (
    CELL_PX,
    GUIDE_LINE_10_COLOR,
    GUIDE_LINE_5_COLOR,
    MARGIN_PX,
    _font_candidates,
    _render_grid,
    _render_overview_with_legend,
    _mirrored_pattern,
    build_export_package,
)


def _sample_pattern() -> dict:
    image = Image.new("RGBA", (90, 90), (0, 0, 0, 0))
    for x in range(16, 74):
        for y in range(16, 74):
            image.putpixel((x, y), (214 if x < 45 else 116, 74, 92, 255))
    source = io.BytesIO()
    image.save(source, "PNG")
    return generate_pattern(source.getvalue(), layout="single", color_mode="standard")


def test_full_pattern_png_includes_the_palette_usage_legend(tmp_path):
    pattern = _sample_pattern()
    grid = _render_grid(pattern)
    overview = _render_overview_with_legend(pattern)

    assert overview.width == grid.width
    assert overview.height > grid.height + 100

    archive_path = tmp_path / "pattern.zip"
    build_export_package(
        project_name="导出图例测试",
        project_id="project-1",
        pattern_id="pattern-1",
        pattern=pattern,
        destination=archive_path,
    )
    with zipfile.ZipFile(archive_path) as archive:
        with Image.open(io.BytesIO(archive.read("完整图纸/完整图纸_带色号.png"))) as exported:
            assert exported.height == overview.height
            lower_area = exported.crop((0, grid.height, exported.width, exported.height))
            assert any(pixel != (255, 255, 255) for pixel in lower_area.convert("RGB").getdata())


def test_palette_legend_wraps_all_30_supported_colours():
    palette = [
        {"brand": "MARD", "code": colour.code, "value": colour.hex, "count": index + 1}
        for index, colour in enumerate(MARD_STANDARD_PALETTE[:30])
    ]
    pattern = {
        "width": 52,
        "height": 52,
        "cells": [],
        "palette": palette,
        "statistics": {"totalBeads": sum(item["count"] for item in palette)},
        "boardLayout": {"seamsX": [], "seamsY": []},
    }
    grid = _render_grid(pattern)
    overview = _render_overview_with_legend(pattern)

    # A 30-colour export needs multiple rows but retains the full colour list.
    assert overview.height >= grid.height + 170
    swatch_colour = tuple(int(MARD_STANDARD_PALETTE[29].hex[index:index + 2], 16) for index in (1, 3, 5))
    assert swatch_colour in overview.crop((0, grid.height, overview.width, overview.height)).getdata()


def test_full_grid_uses_thick_five_cell_lines_and_purple_ten_cell_lines():
    pattern = {
        "width": 15,
        "height": 15,
        "cells": [],
        "boardLayout": {"seamsX": [], "seamsY": []},
    }
    grid = _render_grid(pattern)

    five_line = (MARGIN_PX + 5 * CELL_PX, MARGIN_PX + 2 * CELL_PX)
    ten_line = (MARGIN_PX + 10 * CELL_PX, MARGIN_PX + 2 * CELL_PX)
    horizontal_five = (MARGIN_PX + 2 * CELL_PX, MARGIN_PX + 5 * CELL_PX)
    horizontal_ten = (MARGIN_PX + 2 * CELL_PX, MARGIN_PX + 10 * CELL_PX)

    assert grid.getpixel(five_line) == tuple(int(GUIDE_LINE_5_COLOR[index:index + 2], 16) for index in (1, 3, 5))
    assert grid.getpixel(horizontal_five) == tuple(int(GUIDE_LINE_5_COLOR[index:index + 2], 16) for index in (1, 3, 5))
    assert grid.getpixel(ten_line) == tuple(int(GUIDE_LINE_10_COLOR[index:index + 2], 16) for index in (1, 3, 5))
    assert grid.getpixel(horizontal_ten) == tuple(int(GUIDE_LINE_10_COLOR[index:index + 2], 16) for index in (1, 3, 5))


def test_full_pattern_watermark_is_drawn_at_configured_position():
    pattern = _sample_pattern()
    plain = _render_overview_with_legend(pattern)
    marked = _render_overview_with_legend(pattern, {
        "enabled": True, "text": "MY SHOP", "color": "#e01464", "font": "bold", "x": 50, "y": 96,
    })

    assert marked.size == plain.size
    # The configured lower-centre area differs, while rendering remains a normal RGB PNG.
    area = (marked.width // 3, int(marked.height * .90), marked.width * 2 // 3, marked.height - 8)
    assert marked.crop(area).tobytes() != plain.crop(area).tobytes()


def test_full_pattern_watermark_supports_large_transparent_rotated_text():
    pattern = _sample_pattern()
    plain = _render_overview_with_legend(pattern)
    marked = _render_overview_with_legend(pattern, {
        "enabled": True, "text": "SHOP", "color": "#2076d2", "font": "elegant",
        "size": 520, "opacity": 40, "rotation": 315, "x": 50, "y": 50,
    })

    assert marked.mode == "RGB"
    assert marked.size == plain.size
    assert marked.tobytes() != plain.tobytes()


def test_chinese_watermark_prefers_native_cjk_font_before_latin_font():
    candidates = _font_candidates("handwritten", "@我的拼豆店")

    assert candidates[0] == "/System/Library/Fonts/Supplemental/Kaiti.ttc"
    assert "/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf" in candidates
    assert candidates.index("/System/Library/Fonts/Supplemental/Kaiti.ttc") < candidates.index("/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf")


def test_latin_watermark_keeps_selected_latin_font_priority():
    candidates = _font_candidates("handwritten", "@MY SHOP")

    assert candidates[0] == "/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf"


def test_full_pattern_watermark_respects_preview_edge_position_without_relocating():
    pattern = _sample_pattern()
    plain = _render_overview_with_legend(pattern)
    marked = _render_overview_with_legend(pattern, {
        "enabled": True, "text": "EDGE", "color": "#e01464", "font": "bold",
        "size": 420, "opacity": 80, "rotation": 28, "x": 96, "y": 96,
    })

    # The watermark is clipped at the requested bottom-right location rather
    # than being moved to a different position to fit the canvas.
    corner = (plain.width * 3 // 4, plain.height * 3 // 4, plain.width, plain.height)
    assert marked.crop(corner).tobytes() != plain.crop(corner).tobytes()


def test_export_package_embeds_watermark_in_png_and_pdf(tmp_path):
    pattern = _sample_pattern()
    plain_path = tmp_path / "plain.zip"
    marked_path = tmp_path / "marked.zip"
    common = dict(project_name="水印导出验证", project_id="project-1", pattern_id="pattern-1", pattern=pattern)
    build_export_package(**common, destination=plain_path)
    build_export_package(**common, destination=marked_path, watermark={
        "enabled": True, "text": "SHOP", "color": "#e01464", "font": "bold",
        "size": 240, "opacity": 65, "rotation": 35, "x": 50, "y": 50,
    })
    with zipfile.ZipFile(plain_path) as plain, zipfile.ZipFile(marked_path) as marked:
        plain_png = plain.read("完整图纸/完整图纸_带色号.png")
        marked_png = marked.read("完整图纸/完整图纸_带色号.png")
        assert plain_png != marked_png
        assert plain.read("拼豆图纸包.pdf") != marked.read("拼豆图纸包.pdf")


def test_optional_mirrored_full_pattern_reverses_cells_and_exports_png_pdf(tmp_path):
    pattern = _sample_pattern()
    original_cell = pattern["cells"][0]
    mirrored = _mirrored_pattern(pattern)
    assert any(cell["x"] == pattern["width"] - 1 - original_cell["x"] and cell["y"] == original_cell["y"] for cell in mirrored["cells"])
    archive_path = tmp_path / "mirrored.zip"
    build_export_package(project_name="镜像图纸", project_id="project-1", pattern_id="pattern-1", pattern=pattern, destination=archive_path, include_mirrored_pattern=True)
    with zipfile.ZipFile(archive_path) as archive:
        assert "完整图纸/镜像完整图纸_带色号.png" in archive.namelist()
        assert "镜像完整图纸.pdf" in archive.namelist()
        assert archive.read("完整图纸/镜像完整图纸_带色号.png") != archive.read("完整图纸/完整图纸_带色号.png")
