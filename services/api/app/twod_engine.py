from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat, PngImagePlugin


VARIANTS = {
    # These are ceilings rather than palette targets.  A character with fewer
    # meaningful regions should naturally use fewer colours.
    "simplified": {"label": "方案 A", "detail": "简化", "colors": 16, "targetBoard": "52×52"},
    "standard": {"label": "方案 B", "detail": "标准", "colors": 30, "targetBoard": "104×104"},
    "rich": {"label": "方案 C", "detail": "丰富", "colors": 42, "targetBoard": "104×104 及以上"},
}

MIN_SUBJECT_COVERAGE = 0.12
MIN_BBOX_SPAN = 0.34
SUBJECT_ALPHA_THRESHOLD = 64


def _meaningful_subject_geometry(alpha: Image.Image) -> tuple[tuple[int, int, int, int] | None, dict, bool]:
    """Measure the visible subject without treating translucent cleanup pixels as content.

    Image-model outputs often retain a one- or two-pixel, almost transparent
    halo at the canvas boundary.  That halo is not a cropped subject.  Use a
    conservative alpha threshold for the actionable subject bounds and expose
    the resulting margins so the UI never needs to guess why it warned.
    """
    meaningful = alpha.point(lambda value: 255 if value >= SUBJECT_ALPHA_THRESHOLD else 0)
    bbox = meaningful.getbbox()
    if not bbox:
        return None, {"left": None, "top": None, "right": None, "bottom": None}, False
    left, top, right, bottom = bbox
    margins = {
        "left": left,
        "top": top,
        "right": max(0, alpha.width - right),
        "bottom": max(0, alpha.height - bottom),
    }
    safe_margin = max(4, round(min(alpha.size) * 0.006))
    touches_edge = min(margins.values()) < safe_margin
    return bbox, margins, touches_edge


def analyze_material_complexity(image_bytes: bytes) -> dict:
    """Estimate how hard an image is to translate to a bead grid.

    The score intentionally describes structural density, not artistic quality.
    It is deterministic and cheap enough to run before any model request.
    """
    image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert("RGBA")
    analysis = image.copy()
    analysis.thumbnail((256, 256), Image.Resampling.LANCZOS)
    rgb = analysis.convert("RGB")
    gray = rgb.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_ratio = sum(1 for value in edges.getdata() if value >= 42) / max(1, edges.width * edges.height)
    quantized = rgb.quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    histogram = quantized.histogram()
    active_colors = sum(value >= max(2, rgb.width * rgb.height * .0015) for value in histogram)
    color_density = min(1.0, active_colors / 42)
    entropy = min(1.0, ImageStat.Stat(gray).stddev[0] / 72)
    alpha = analysis.getchannel("A")
    coverage = sum(alpha.histogram()[32:]) / max(1, analysis.width * analysis.height)
    # An opaque flat background is common in simple cartoons and is not itself
    # complexity. Only penalize a full-frame image when its structure is dense.
    full_frame_penalty = .10 if coverage > .88 and edge_ratio > .11 and active_colors > 24 else 0
    score = round(100 * min(1.0, edge_ratio * 2.4 + color_density * .34 + entropy * .22 + full_frame_penalty))
    level = "simple" if score < 38 else "medium" if score < 65 else "complex"
    recommendation = {
        "simple": ("simplified", "52×52", "轮廓与色块清晰，可先用小图板验证。"),
        "medium": ("standard", "104×104", "需要适度 Q 化并保护局部辨识特征。"),
        "complex": ("standard", "104×104 及以上", "应先由模型重构为适合落针的标准 2D；直接缩放质量风险高。"),
    }[level]
    return {
        "complexityScore": score,
        "complexityLevel": level,
        "edgeDensity": round(edge_ratio, 4),
        "significantColorCount": active_colors,
        "toneVariation": round(entropy, 3),
        "sourceCoverage": round(coverage, 3),
        "recommendedVariant": recommendation[0],
        "recommendedBoard": recommendation[1],
        "recommendationReason": recommendation[2],
        "route": "local-shape" if level == "simple" else "model-semantic-2d",
        "analysisVersion": "material-router-v1",
    }


def _subject_mask(image: Image.Image) -> tuple[Image.Image, dict]:
    rgb = image.convert("RGB")
    corners = [
        rgb.getpixel((0, 0)),
        rgb.getpixel((rgb.width - 1, 0)),
        rgb.getpixel((0, rgb.height - 1)),
        rgb.getpixel((rgb.width - 1, rgb.height - 1)),
    ]
    background = tuple(sum(pixel[channel] for pixel in corners) // 4 for channel in range(3))
    bg = Image.new("RGB", rgb.size, background)
    difference = ImageChops.difference(rgb, bg).convert("L")
    difference = ImageEnhance.Contrast(difference).enhance(2.4)
    mask = difference.point(lambda value: 255 if value > 28 else 0)
    mask = mask.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(1.1))

    # If corner sampling would erase most of a complex/full-frame image, preserve it.
    occupied = mask.getbbox()
    coverage = sum(mask.histogram()[32:]) / max(1, image.width * image.height)
    corner_delta = sum(sum(abs(pixel[channel] - background[channel]) for channel in range(3)) for pixel in corners) / 12
    bbox_width = (occupied[2] - occupied[0]) if occupied else 0
    bbox_height = (occupied[3] - occupied[1]) if occupied else 0
    width_span = bbox_width / max(1, image.width)
    height_span = bbox_height / max(1, image.height)
    # A thin strip is never a safe automatic subject crop. This was the source
    # of portrait artwork being collapsed into a horizontal band.
    suspicious_geometry = (
        not occupied
        or coverage < MIN_SUBJECT_COVERAGE
        or width_span < MIN_BBOX_SPAN
        or height_span < MIN_BBOX_SPAN
    )
    fallback = suspicious_geometry
    if fallback:
        mask = Image.new("L", image.size, 255)
        coverage = 1.0
    border = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(border)
    draw.rectangle((0, 0, image.width - 1, image.height - 1), outline=255, width=max(2, min(image.size) // 80))
    touches_edge = ImageChops.multiply(mask, border).getbbox() is not None
    score = max(0, min(100, round(100 - corner_delta * 1.2 - (25 if fallback else 0) - (12 if touches_edge else 0))))
    quality = {
        "score": score,
        "coverage": round(coverage, 3),
        "complexBackground": fallback or corner_delta > 24,
        "touchesEdge": touches_edge,
        "geometryFallback": fallback,
        "subjectWidthRatio": round(width_span, 3),
        "subjectHeightRatio": round(height_span, 3),
        "generationMode": "offline_stylized_preview",
        "confirmable": False,
        "warnings": [
            *([{"code": "COMPLEX_BACKGROUND", "message": "背景与主体颜色接近，建议检查蒙版。"}] if fallback or corner_delta > 24 else []),
            *([{
                "code": "UNSAFE_SUBJECT_GEOMETRY",
                "message": "自动主体范围不可靠，已回退为完整原图并保持比例，未执行危险裁切。",
            }] if suspicious_geometry else []),
            {
                "code": "PREVIEW_NOT_FINAL_2D",
                "message": "当前离线结果仅为色彩与轮廓预处理参考稿，不是重新绘制的成品 2D，不能确认为正式资产。",
            },
            *([{"code": "SUBJECT_TOUCHES_EDGE", "message": "主体接近画面边缘，建议检查裁切。"}] if touches_edge else []),
        ],
    }
    return mask, quality


def _apply_settings(image: Image.Image, mask: Image.Image, settings: dict) -> tuple[Image.Image, Image.Image]:
    width, height = image.size
    boxes = settings.get("subject_boxes") or []
    if boxes:
        selected = Image.new("L", image.size, 0)
        for box in boxes:
            x1 = int(max(0, min(1, box.get("x", 0))) * width)
            y1 = int(max(0, min(1, box.get("y", 0))) * height)
            x2 = int(max(0, min(1, box.get("x", 0) + box.get("width", 1))) * width)
            y2 = int(max(0, min(1, box.get("y", 0) + box.get("height", 1))) * height)
            ImageDraw.Draw(selected).rectangle((x1, y1, x2, y2), fill=255)
        mask = ImageChops.multiply(mask, selected)
    if settings.get("mask_strokes"):
        draw = ImageDraw.Draw(mask)
        for stroke in settings["mask_strokes"]:
            x = int(max(0, min(1, stroke.get("x", 0))) * width)
            y = int(max(0, min(1, stroke.get("y", 0))) * height)
            radius = int(max(2, min(width, height) * max(0.005, min(0.2, stroke.get("radius", 0.04)))))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255 if stroke.get("mode") == "keep" else 0)
    crop = settings.get("crop") or {}
    if crop:
        x = int(max(0, min(1, crop.get("x", 0))) * width)
        y = int(max(0, min(1, crop.get("y", 0))) * height)
        right = int(max(0, min(1, crop.get("x", 0) + crop.get("width", 1))) * width)
        bottom = int(max(0, min(1, crop.get("y", 0) + crop.get("height", 1))) * height)
        if right - x >= 16 and bottom - y >= 16:
            image, mask = image.crop((x, y, right, bottom)), mask.crop((x, y, right, bottom))
    return image, mask


def _fit_subject(image: Image.Image, mask: Image.Image, size: int = 768, composition: str = "full") -> Image.Image:
    bbox = mask.getbbox() or (0, 0, image.width, image.height)
    subject = image.crop(bbox)
    subject_mask = mask.crop(bbox)
    scale = {"full": 0.84, "half": 1.02, "head": 1.18}.get(composition, 0.84)
    subject.thumbnail((int(size * scale), int(size * scale)), Image.Resampling.LANCZOS)
    subject_mask = subject_mask.resize(subject.size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    position = ((size - subject.width) // 2, (size - subject.height) // 2)
    canvas.paste(subject.convert("RGBA"), position, subject_mask)
    return canvas


def prepare_model_source(image_bytes: bytes, settings: dict | None = None) -> bytes:
    """Create the actual reference sent to an image model.

    Automatic background removal is deliberately *not* part of this path.
    Dark cinematic material often has a subject, hat, armour and background
    with similar corner colours; deriving an alpha mask from those colours can
    destroy the very visual anchors that an image model needs to keep identity.

    With no explicit user selection we therefore send the complete, unmasked
    original image.  When a subject box or crop is explicitly provided, we use
    that geometry to crop original pixels -- never an inferred colour mask.
    """
    try:
        source = Image.open(BytesIO(image_bytes))
        source.load()
    except Exception as exc:
        raise ValueError("INVALID_IMAGE") from exc
    source = ImageOps.exif_transpose(source).convert("RGBA")
    settings = settings or {}
    width, height = source.size
    crop = settings.get("crop") or {}
    if crop:
        x = int(max(0, min(1, crop.get("x", 0))) * width)
        y = int(max(0, min(1, crop.get("y", 0))) * height)
        right = int(max(0, min(1, crop.get("x", 0) + crop.get("width", 1))) * width)
        bottom = int(max(0, min(1, crop.get("y", 0) + crop.get("height", 1))) * height)
        if right - x >= 16 and bottom - y >= 16:
            source = source.crop((x, y, right, bottom))
            width, height = source.size

    boxes = settings.get("subject_boxes") or []
    if boxes:
        # The crop itself is the selection: all pixel data within it remains
        # available to the model, including dark hats, armour and weapons.
        left = min(int(max(0, min(1, box.get("x", 0))) * width) for box in boxes)
        top = min(int(max(0, min(1, box.get("y", 0))) * height) for box in boxes)
        right = max(int(max(0, min(1, box.get("x", 0) + box.get("width", 1))) * width) for box in boxes)
        bottom = max(int(max(0, min(1, box.get("y", 0) + box.get("height", 1))) * height) for box in boxes)
        if right - left >= 16 and bottom - top >= 16:
            source = source.crop((left, top, right, bottom))

    # Keep source aspect ratio and pixels intact.  No auto mask, alpha cutout,
    # posterization, or fitting canvas is allowed before the model request.
    max_edge = 2048
    if max(source.size) > max_edge:
        scale = max_edge / max(source.size)
        source = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS)
    prepared = source.convert("RGBA")
    output = BytesIO()
    prepared.save(output, "PNG", optimize=True)
    return output.getvalue()


def _posterize(image: Image.Image, colors: int) -> Image.Image:
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    quantized = rgb.quantize(
        colors=colors,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    ).convert("RGB")
    quantized = ImageEnhance.Color(quantized).enhance(1.08)
    quantized = ImageEnhance.Contrast(quantized).enhance(1.06)
    result = quantized.convert("RGBA")
    result.putalpha(alpha)
    return result


def _add_adaptive_outline(image: Image.Image, strength: int) -> Image.Image:
    alpha = image.getchannel("A")
    expanded = alpha.filter(ImageFilter.MaxFilter(strength))
    edge = ImageChops.subtract(expanded, alpha)
    # Deep blue-gray is intentionally softer than fixed black.
    outline = Image.new("RGBA", image.size, (42, 57, 70, 0))
    outline.putalpha(edge)
    return Image.alpha_composite(outline, image)


def generate_2d_candidates(image_bytes: bytes, settings: dict | None = None) -> tuple[dict[str, bytes], dict]:
    try:
        source = Image.open(BytesIO(image_bytes))
        source.load()
    except Exception as exc:  # Pillow exposes several decoder exceptions.
        raise ValueError("INVALID_IMAGE") from exc
    if source.width < 16 or source.height < 16:
        raise ValueError("IMAGE_TOO_SMALL")

    source = ImageOps.exif_transpose(source).convert("RGBA")
    settings = settings or {}
    mask, quality = _subject_mask(source)
    source, mask = _apply_settings(source, mask, settings)
    if settings.get("mask_strokes") or settings.get("subject_boxes"):
        quality["score"] = min(100, quality["score"] + 12)
        quality["manuallyAdjusted"] = True
    prepared = _fit_subject(source, mask, composition=settings.get("composition", "full"))
    outputs: dict[str, bytes] = {}
    for key, config in VARIANTS.items():
        candidate = _posterize(prepared, config["colors"])
        if key == "simplified":
            candidate = candidate.filter(ImageFilter.SMOOTH_MORE)
            candidate = _add_adaptive_outline(candidate, 7)
        elif key == "standard":
            candidate = _add_adaptive_outline(candidate, 5)
        else:
            candidate = ImageEnhance.Sharpness(candidate).enhance(1.18)
            candidate = _add_adaptive_outline(candidate, 3)
        output = BytesIO()
        candidate.save(output, "PNG", optimize=True)
        outputs[key] = output.getvalue()
    return outputs, quality


def inspect_candidate(image_bytes: bytes) -> dict:
    opened = Image.open(BytesIO(image_bytes))
    generation_mode = opened.info.get("perler_generation_mode", "offline_stylized_preview")
    model_name = opened.info.get("perler_model")
    complexity_score = opened.info.get("perler_complexity_score")
    image = opened.convert("RGBA")
    alpha = image.getchannel("A")
    meaningful = alpha.point(lambda value: 255 if value >= SUBJECT_ALPHA_THRESHOLD else 0)
    coverage = sum(meaningful.histogram()[1:]) / max(1, image.width * image.height)
    bbox, margins, touches_edge = _meaningful_subject_geometry(alpha)
    model_generated = generation_mode == "model_generated"
    return {
        "score": 78 if touches_edge else 92,
        "coverage": round(coverage, 3),
        "complexBackground": False,
        "touchesEdge": touches_edge,
        "subjectBounds": (
            {"left": bbox[0], "top": bbox[1], "right": bbox[2], "bottom": bbox[3]}
            if bbox else None
        ),
        "subjectMargins": margins,
        "edgeSafetyMargin": max(4, round(min(image.size) * 0.006)),
        "generationMode": generation_mode,
        "model": model_name,
        "complexityScore": int(complexity_score) if complexity_score else None,
        "complexityLevel": opened.info.get("perler_complexity_level"),
        "recommendedVariant": opened.info.get("perler_recommended_variant"),
        "recommendedBoard": opened.info.get("perler_recommended_board"),
        "route": opened.info.get("perler_route"),
        "selectedStrategy": opened.info.get("perler_variant"),
        # A genuine tight crop is useful information, but it is not a reason
        # to trap a paid model result in the 2D stage.  The board stage can
        # still position/scale the approved subject with its own safe margin.
        "confirmable": model_generated and coverage >= 0.12,
        "warnings": [
            *([{
                "code": "SUBJECT_TOUCHES_EDGE",
                "message": (
                    "主体进入安全边距（左 {left}px、上 {top}px、右 {right}px、下 {bottom}px；"
                    "建议最少 {safe}px）。可确认后在图板阶段调整位置与留白。"
                ).format(**margins, safe=max(4, round(min(image.size) * 0.006))),
            }] if touches_edge else []),
            *([{
                "code": "PREVIEW_NOT_FINAL_2D",
                "message": "当前离线结果仅为预处理参考稿，不能确认为正式 2D。",
            }] if not model_generated else []),
        ],
    }


def repair_model_candidate_background(image_bytes: bytes) -> bytes:
    """Remove a connected pale/textured model background without another model call.

    Qwen commonly returns an opaque ivory paper-like background even when the
    prompt asks for transparency.  A fixed near-white threshold leaves that
    texture attached to every border, which makes a valid candidate impossible
    to confirm.  Flood filling only the border-connected region preserves pale
    details inside the character while clearing the surrounding paper texture.
    """
    opened = Image.open(BytesIO(image_bytes))
    generation_mode = opened.info.get("perler_generation_mode")
    if generation_mode != "model_generated":
        return image_bytes

    metadata_values = {
        key: value
        for key, value in opened.info.items()
        if key.startswith("perler_") and isinstance(value, str)
    }
    image = opened.convert("RGBA")
    rgb = image.convert("RGB")
    marker = (1, 2, 3)
    flooded = rgb.copy()
    width, height = flooded.size
    for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if flooded.getpixel(corner) != marker:
            ImageDraw.floodfill(flooded, corner, marker, thresh=58)

    background = flooded.point(lambda value: 255 if value in marker else 0).convert("L")
    # RGB point() works per channel, so require all three marker components.
    red, green, blue = flooded.split()
    background = ImageChops.multiply(
        ImageChops.multiply(red.point(lambda value: 255 if value == marker[0] else 0),
                            green.point(lambda value: 255 if value == marker[1] else 0)),
        blue.point(lambda value: 255 if value == marker[2] else 0),
    )
    background = background.filter(ImageFilter.GaussianBlur(1.2))
    repaired_alpha = ImageChops.multiply(
        image.getchannel("A"),
        ImageOps.invert(background),
    )
    image.putalpha(repaired_alpha)

    metadata = PngImagePlugin.PngInfo()
    for key, value in metadata_values.items():
        metadata.add_text(key, value)
    metadata.add_text("perler_background_repair", "border_flood_v1")
    output = BytesIO()
    image.save(output, "PNG", optimize=True, pnginfo=metadata)
    return output.getvalue()
