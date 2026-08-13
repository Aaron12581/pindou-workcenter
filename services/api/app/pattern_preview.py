from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw


def render_pattern_preview(pattern: dict) -> bytes:
    scale = max(3, min(8, 696 // max(pattern["width"], pattern["height"])))
    image = Image.new("RGB", (pattern["width"] * scale, pattern["height"] * scale), "white")
    draw = ImageDraw.Draw(image)
    for cell in pattern["cells"]:
        x, y = cell["x"] * scale, cell["y"] * scale
        draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill=cell["colorValue"])
    output = BytesIO()
    image.save(output, "PNG", optimize=True)
    return output.getvalue()
