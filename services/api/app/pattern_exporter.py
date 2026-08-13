from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as PdfImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


EXPORT_FORMAT = "perler-pattern-export"
EXPORT_VERSION = 1
CELL_PX = 34
MARGIN_PX = 54
LEGEND_PADDING_X = 54
LEGEND_PADDING_Y = 28
LEGEND_SWATCH_PX = 24
LEGEND_ITEM_WIDTH = 178
# Grid-navigation lines are deliberately rendered separately from the normal
# one-cell outlines.  This keeps every fifth line easy to find in a dense
# full-size pattern while reserving purple for the 10-cell landmarks.
GUIDE_LINE_5_COLOR = "#dd7777"
GUIDE_LINE_10_COLOR = "#805ad5"
GUIDE_LINE_WIDTH = 3


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", value).strip(" .")
    return cleaned[:80] or "perler-pattern"


def _contains_cjk(value: str) -> bool:
    """Return whether text needs a font with Chinese glyph coverage."""
    return any(
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        or "\u3000" <= character <= "\u303f"
        for character in value
    )


def _font_candidates(family: str = "sans", text: str = "") -> tuple[str, ...]:
    # The export process is server-side.  On macOS the old order selected
    # DejaVu first, which can paint “@” but has no Chinese glyphs; that left
    # the configured Chinese watermark text blank in the downloaded PNG/PDF.
    # Prefer native CJK fonts whenever the requested text needs them, while
    # retaining the selected style where a matching system font is available.
    cjk_by_family = {
        "sans": ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"),
        "serif": ("/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/STSong.ttc", "C:/Windows/Fonts/simsun.ttc"),
        "bold": ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf"),
        "mono": ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc", "C:/Windows/Fonts/msyh.ttc"),
        "rounded": ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc", "C:/Windows/Fonts/msyh.ttc"),
        "elegant": ("/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/STSong.ttc", "C:/Windows/Fonts/simsun.ttc"),
        "italic": ("/System/Library/Fonts/Supplemental/Kaiti.ttc", "/System/Library/Fonts/STKaiti.ttc", "C:/Windows/Fonts/simkai.ttf", "/System/Library/Fonts/PingFang.ttc"),
        "handwritten": ("/System/Library/Fonts/Supplemental/Kaiti.ttc", "/System/Library/Fonts/STKaiti.ttc", "C:/Windows/Fonts/simkai.ttf", "/System/Library/Fonts/PingFang.ttc"),
    }
    candidates_by_family = {
        "sans": ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Helvetica.ttc", "C:/Windows/Fonts/arial.ttf"),
        "serif": ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/Times.ttc", "C:/Windows/Fonts/times.ttf"),
        "bold": ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Helvetica.ttc", "C:/Windows/Fonts/arialbd.ttf"),
        "mono": ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/System/Library/Fonts/Menlo.ttc", "C:/Windows/Fonts/consola.ttf"),
        "rounded": ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", "/System/Library/Fonts/PingFang.ttc", "C:/Windows/Fonts/ARLRDBD.TTF"),
        "elegant": ("/usr/share/fonts/opentype/urw-base35/URWBookman-Demi.otf", "/System/Library/Fonts/Supplemental/Baskerville.ttc", "/System/Library/Fonts/Supplemental/Songti.ttc", "C:/Windows/Fonts/BOOKOS.TTF"),
        "italic": ("/usr/share/fonts/opentype/urw-base35/NimbusSans-Italic.otf", "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf", "/System/Library/Fonts/Supplemental/Kaiti.ttc", "C:/Windows/Fonts/timesi.ttf"),
        "handwritten": ("/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf", "/System/Library/Fonts/Supplemental/Kaiti.ttc", "/System/Library/Fonts/PingFang.ttc", "C:/Windows/Fonts/segoesc.ttf"),
    }
    candidates = candidates_by_family.get(family, candidates_by_family["sans"])
    if _contains_cjk(text):
        candidates = cjk_by_family.get(family, cjk_by_family["sans"]) + candidates
    return tuple(candidates)


def _font(size: int, family: str = "sans", text: str = "") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _font_candidates(family, text):
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _draw_watermark(image: Image.Image, watermark: dict | None) -> Image.Image:
    """Paint the exact export watermark onto an image.

    The UI positions a watermark by its centre as a percentage of the whole
    paper.  Keep that coordinate model here too: it is important that moving a
    label near an edge clips in the same direction as the preview instead of
    silently relocating it back into the page.
    """
    if not watermark or not watermark.get("enabled"):
        return image
    text = str(watermark.get("text") or "").strip()
    if not text:
        return image
    font = _font(
        max(12, min(1600, int(watermark.get("size", 72)))),
        str(watermark.get("font") or "sans"),
        text,
    )
    opacity = max(0, min(100, int(watermark.get("opacity", 55))))
    angle = float(watermark.get("rotation", 0)) % 360
    color = str(watermark.get("color") or "#526c7e")
    color_value = color.lstrip("#")
    try:
        rgb = tuple(int(color_value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        rgb = (82, 108, 126)
    stroke_width = max(1, round(font.size / 90))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = probe.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    if box[2] <= box[0] or box[3] <= box[1]:
        return image
    text_width, text_height = box[2] - box[0], box[3] - box[1]
    layer = Image.new("RGBA", (text_width + stroke_width * 6, text_height + stroke_width * 6), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    layer_draw.text(
        (stroke_width * 3 - box[0], stroke_width * 3 - box[1]), text, font=font,
        fill=(*rgb, round(255 * opacity / 100)), stroke_width=stroke_width,
        stroke_fill=(255, 255, 255, round(145 * opacity / 100)),
    )
    if angle:
        layer = layer.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
    center_x = image.width * float(watermark.get("x", 82)) / 100
    center_y = image.height * float(watermark.get("y", 94)) / 100
    x = round(center_x - layer.width / 2)
    y = round(center_y - layer.height / 2)

    # Composite through RGBA even when the source grid is RGB.  ``paste`` on an
    # RGB image has platform-dependent alpha behaviour for very transparent
    # rotated layers; this produces the same pixels in PNG and in the PDF image.
    canvas = image.convert("RGBA")
    canvas.alpha_composite(layer, (x, y))
    return canvas.convert(image.mode)


def _text_color(hex_value: str) -> str:
    value = hex_value.lstrip("#")
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    return "#17232c" if red * 299 + green * 587 + blue * 114 > 145000 else "#ffffff"


def _render_grid(
    pattern: dict,
    *,
    bounds: tuple[int, int, int, int] | None = None,
    show_codes: bool = True,
    show_coordinates: bool = True,
    show_seams: bool = True,
) -> Image.Image:
    start_x, start_y, end_x, end_y = bounds or (
        0, 0, int(pattern["width"]), int(pattern["height"])
    )
    width, height = end_x - start_x, end_y - start_y
    top = MARGIN_PX if show_coordinates else 18
    left = MARGIN_PX if show_coordinates else 18
    image = Image.new("RGB", (left + width * CELL_PX + 18, top + height * CELL_PX + 18), "white")
    draw = ImageDraw.Draw(image)
    code_font = _font(11)
    axis_font = _font(13)
    cells = {(int(cell["x"]), int(cell["y"])): cell for cell in pattern["cells"]}
    for local_y in range(height):
        for local_x in range(width):
            x, y = start_x + local_x, start_y + local_y
            x0, y0 = left + local_x * CELL_PX, top + local_y * CELL_PX
            cell = cells.get((x, y))
            fill = str(cell["colorValue"]) if cell else "#ffffff"
            draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX), fill=fill, outline="#a9b5bd", width=1)
            if cell and show_codes:
                code = str(cell["colorCode"])
                box = draw.textbbox((0, 0), code, font=code_font)
                draw.text(
                    (x0 + (CELL_PX - box[2]) / 2, y0 + (CELL_PX - box[3]) / 2 - 1),
                    code,
                    fill=_text_color(fill),
                    font=code_font,
                )
    if show_coordinates:
        for local_x in range(width):
            label = str(start_x + local_x + 1)
            draw.text((left + local_x * CELL_PX + 9, 20), label, fill="#536675", font=axis_font)
        for local_y in range(height):
            label = str(start_y + local_y + 1)
            draw.text((13, top + local_y * CELL_PX + 8), label, fill="#536675", font=axis_font)
    # Draw these on top of cell borders so the locator grid stays visible even
    # across dark filled cells. Ten-cell lines use the same width as five-cell
    # lines; colour, not thickness, distinguishes the two locator intervals.
    for local_x in range(1, width):
        grid_x = start_x + local_x
        if grid_x % 5:
            continue
        color = GUIDE_LINE_10_COLOR if grid_x % 10 == 0 else GUIDE_LINE_5_COLOR
        x = left + local_x * CELL_PX
        draw.line((x, top, x, top + height * CELL_PX), fill=color, width=GUIDE_LINE_WIDTH)
    for local_y in range(1, height):
        grid_y = start_y + local_y
        if grid_y % 5:
            continue
        color = GUIDE_LINE_10_COLOR if grid_y % 10 == 0 else GUIDE_LINE_5_COLOR
        y = top + local_y * CELL_PX
        draw.line((left, y, left + width * CELL_PX, y), fill=color, width=GUIDE_LINE_WIDTH)
    if show_seams and bounds is None:
        for seam in pattern["boardLayout"].get("seamsX", []):
            x = left + int(seam) * CELL_PX
            draw.line((x, top, x, top + height * CELL_PX), fill="#168ad5", width=5)
        for seam in pattern["boardLayout"].get("seamsY", []):
            y = top + int(seam) * CELL_PX
            draw.line((left, y, left + width * CELL_PX, y), fill="#168ad5", width=5)
    return image


def _render_overview_with_legend(pattern: dict, watermark: dict | None = None) -> Image.Image:
    """Render the full-grid PNG together with its colour-code usage legend.

    The export preview already presents this information below the grid.  Keep
    the PNG self-contained as well, so a printed or forwarded grid does not
    require the separate CSV to identify the required bead quantities.
    """
    grid = _render_grid(pattern)
    palette = list(pattern.get("palette", []))
    if not palette:
        return _draw_watermark(grid, watermark)

    available_width = max(1, grid.width - LEGEND_PADDING_X * 2)
    columns = max(1, available_width // LEGEND_ITEM_WIDTH)
    rows = (len(palette) + columns - 1) // columns
    title_font = _font(19)
    item_font = _font(16)
    title_height = 34
    row_height = max(LEGEND_SWATCH_PX, 23) + 16
    legend_height = LEGEND_PADDING_Y * 2 + title_height + rows * row_height + 18

    canvas = Image.new("RGB", (grid.width, grid.height + legend_height), "white")
    canvas.paste(grid, (0, 0))
    draw = ImageDraw.Draw(canvas)
    top = grid.height
    draw.line((LEGEND_PADDING_X, top + 1, grid.width - LEGEND_PADDING_X, top + 1), fill="#d5e0e7", width=2)
    draw.text(
        (LEGEND_PADDING_X, top + LEGEND_PADDING_Y),
        f"MARD COLOR USAGE · TOTAL {pattern['statistics']['totalBeads']:,} BEADS",
        fill="#405462",
        font=title_font,
    )
    items_top = top + LEGEND_PADDING_Y + title_height
    for index, item in enumerate(palette):
        row, column = divmod(index, columns)
        x = LEGEND_PADDING_X + column * LEGEND_ITEM_WIDTH
        y = items_top + row * row_height
        colour = str(item["value"])
        draw.rounded_rectangle(
            (x, y + 1, x + LEGEND_SWATCH_PX, y + LEGEND_SWATCH_PX + 1),
            radius=4,
            fill=colour,
            outline="#8ca0ad",
            width=1,
        )
        draw.text(
            (x + LEGEND_SWATCH_PX + 8, y + 3),
            f"{item['code']} · {int(item['count']):,}",
            fill="#293943",
            font=item_font,
        )
    draw.text(
        (LEGEND_PADDING_X, canvas.height - 28),
        "Legend format: COLOR CODE · QUANTITY",
        fill="#6f8290",
        font=_font(14),
    )
    return _draw_watermark(canvas, watermark)


def _mirrored_pattern(pattern: dict) -> dict:
    """Mirror a full pattern horizontally for reverse-side ironing."""
    mirrored = dict(pattern)
    width = int(pattern["width"])
    mirrored["cells"] = [{**cell, "x": width - 1 - int(cell["x"])} for cell in pattern.get("cells", [])]
    mirrored["cells"].sort(key=lambda cell: (int(cell["y"]), int(cell["x"])))
    layout = dict(pattern.get("boardLayout", {}))
    layout["seamsX"] = sorted(width - int(seam) for seam in layout.get("seamsX", []))
    mirrored["boardLayout"] = layout
    return mirrored


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    return output.getvalue()


def _color_csv(pattern: dict) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["brand", "color_code", "display_hex", "quantity"])
    for item in pattern["palette"]:
        writer.writerow([
            item.get("brand", "MARD"),
            item["code"],
            item["value"],
            item["count"],
        ])
    writer.writerow(["TOTAL", "", "", pattern["statistics"]["totalBeads"]])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _pdf_bytes(project_name: str, pattern: dict, overview: bytes, boards: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ExportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=18,
        leading=24, alignment=TA_CENTER, textColor=colors.HexColor("#243746"),
    )
    body = ParagraphStyle(
        "ExportBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9,
        leading=13, textColor=colors.HexColor("#405462"),
    )
    doc = SimpleDocTemplate(
        output, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title="Perler Pattern Package",
    )
    story = [
        Paragraph("Perler Pattern - Full Grid", title),
        Paragraph(
            f'{pattern["width"]} x {pattern["height"]} cells | '
            f'{pattern["statistics"]["colorCount"]} colors | '
            f'{pattern["statistics"]["totalBeads"]} beads | MARD {pattern["paletteVersion"]}',
            body,
        ),
        Spacer(1, 4 * mm),
        PdfImage(io.BytesIO(overview), width=230 * mm, height=150 * mm, kind="proportional"),
        PageBreak(),
        Paragraph("MARD Color Usage", title),
    ]
    table_data = [["Brand", "Color code", "Display hex", "Quantity"]]
    for item in pattern["palette"]:
        table_data.append([
            item.get("brand", "MARD"), item["code"], item["value"], str(item["count"])
        ])
    table_data.append(["", "TOTAL", "", str(pattern["statistics"]["totalBeads"])])
    table = Table(table_data, colWidths=[35 * mm, 35 * mm, 50 * mm, 35 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dff2ff")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#243746")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c5ce")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f6f9fb")]),
    ]))
    story.extend([Spacer(1, 4 * mm), table])
    for board_id, png in boards:
        story.extend([
            PageBreak(),
            Paragraph(f"Board {board_id} - {pattern['boardLayout'].get('boardWidth', 52)} x {pattern['boardLayout'].get('boardHeight', 52)} cells", title),
            Spacer(1, 3 * mm),
            PdfImage(io.BytesIO(png), width=155 * mm, height=155 * mm, kind="proportional"),
            Paragraph("Coordinates refer to the full pattern. Each occupied cell shows its MARD color code.", body),
        ])
    doc.build(story)
    return output.getvalue()


def build_export_package(
    *,
    project_name: str,
    project_id: str,
    pattern_id: str,
    pattern: dict,
    destination: Path,
    watermark: dict | None = None,
    include_mirrored_pattern: bool = False,
) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    overview = _png_bytes(_render_overview_with_legend(pattern, watermark))
    board_columns = int(pattern["boardLayout"]["columns"])
    board_rows = int(pattern["boardLayout"]["rows"])
    board_width = int(pattern["boardLayout"].get("boardWidth", 29))
    board_height = int(pattern["boardLayout"].get("boardHeight", 29))
    boards: list[tuple[str, bytes]] = []
    for row in range(board_rows):
        for column in range(board_columns):
            board_id = f"{chr(65 + row)}{column + 1}"
            bounds = (
                column * board_width,
                row * board_height,
                min((column + 1) * board_width, pattern["width"]),
                min((row + 1) * board_height, pattern["height"]),
            )
            boards.append((board_id, _png_bytes(_render_grid(pattern, bounds=bounds, show_seams=False))))
    color_csv = _color_csv(pattern)
    pdf = _pdf_bytes(project_name, pattern, overview, boards)
    pattern_json = json.dumps(pattern, ensure_ascii=False, indent=2).encode("utf-8")
    payloads: list[tuple[str, bytes]] = [
        ("完整图纸/完整图纸_带色号.png", overview),
        ("色号用量/MARD_色号用量.csv", color_csv),
        ("数据/pattern.json", pattern_json),
        ("拼豆图纸包.pdf", pdf),
        *[(f"分板图/{board_id}.png", data) for board_id, data in boards],
    ]
    if include_mirrored_pattern:
        mirrored = _mirrored_pattern(pattern)
        mirrored_overview = _png_bytes(_render_overview_with_legend(mirrored, watermark))
        payloads.extend([
            ("完整图纸/镜像完整图纸_带色号.png", mirrored_overview),
            ("镜像完整图纸.pdf", _pdf_bytes(project_name, mirrored, mirrored_overview, [])),
        ])
    files = [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in payloads
    ]
    manifest = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "project": {"id": project_id, "name": project_name},
        "pattern": {
            "id": pattern_id,
            "revision": int(pattern.get("revision", 0)),
            "schemaVersion": pattern.get("schemaVersion"),
            "width": pattern["width"],
            "height": pattern["height"],
            "paletteVersion": pattern["paletteVersion"],
            "totalBeads": pattern["statistics"]["totalBeads"],
            "colorCount": pattern["statistics"]["colorCount"],
        },
        "files": files,
    }
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads:
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {
        "filename": f"{_safe_name(project_name)}_拼豆图纸包.zip",
        "revision": manifest["pattern"]["revision"],
        "board_count": len(boards),
        "file_count": len(payloads) + 1,
        "total_beads": manifest["pattern"]["totalBeads"],
        "color_count": manifest["pattern"]["colorCount"],
        "size_bytes": destination.stat().st_size,
        "manifest": manifest,
    }
