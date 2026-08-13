from __future__ import annotations

from collections import Counter, deque
from colorsys import rgb_to_hsv
from io import BytesIO
from math import atan2, cos, degrees, exp, pow, radians, sin, sqrt

from PIL import Image, ImageChops, ImageFilter

from .mard_palette import MARD_STANDARD_PALETTE, MardColor


BOARD_LAYOUTS = {
    "single": (52, 52, 1, 1),
    "double_horizontal": (104, 52, 2, 1),
    "double_vertical": (52, 104, 1, 2),
    "quad": (104, 104, 2, 2),
    "six_horizontal": (156, 104, 3, 2),
}
# The 2D strategy controls visual simplification. Pattern conversion must not
# silently discard a valid official colour merely because an image needs more
# than the former 12/24/40 hard caps.
# Colour counts are ceilings, not targets.  The generator should keep a
# smaller palette whenever the image can be read clearly with fewer colours.
COLOR_LIMITS = {"limited": 16, "standard": 30, "rich": 42}
BOARD_SIZE = 52
LOCAL_ENGINE_VERSION = "direct-model-grid-v12"
DIRECT_MODEL_ENGINE_VERSION = "direct-model-image-v11"
ANALYSIS_SIZE = 116

REGION_WEIGHTS = {
    "base": 1,
    "clothing": 2,
    "outline": 4,
    "face": 5,
    "facial_detail": 8,
    "hand": 7,
    "weapon": 7,
}


def _srgb_channel(value: int) -> float:
    channel = value / 255
    return channel / 12.92 if channel <= 0.04045 else pow((channel + 0.055) / 1.055, 2.4)


def _lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    red, green, blue = (_srgb_channel(value) for value in rgb)
    x = (red * .4124564 + green * .3575761 + blue * .1804375) / .95047
    y = red * .2126729 + green * .7151522 + blue * .0721750
    z = (red * .0193339 + green * .1191920 + blue * .9503041) / 1.08883

    def pivot(value: float) -> float:
        return pow(value, 1 / 3) if value > .008856 else 7.787 * value + 16 / 116

    fx, fy, fz = pivot(x), pivot(y), pivot(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _delta_e_2000(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    """CIEDE2000 for D65 Lab values."""
    l1, a1, b1 = left
    l2, a2, b2 = right
    c1, c2 = sqrt(a1 * a1 + b1 * b1), sqrt(a2 * a2 + b2 * b2)
    c_bar = (c1 + c2) / 2
    g = .5 * (1 - sqrt(pow(c_bar, 7) / (pow(c_bar, 7) + pow(25, 7))))
    ap1, ap2 = (1 + g) * a1, (1 + g) * a2
    cp1, cp2 = sqrt(ap1 * ap1 + b1 * b1), sqrt(ap2 * ap2 + b2 * b2)

    def hue(a: float, b: float) -> float:
        value = degrees(atan2(b, a))
        return value + 360 if value < 0 else value

    hp1, hp2 = hue(ap1, b1), hue(ap2, b2)
    dl, dc = l2 - l1, cp2 - cp1
    dh_raw = hp2 - hp1
    if cp1 * cp2 == 0:
        dh = 0
    elif abs(dh_raw) <= 180:
        dh = dh_raw
    elif dh_raw > 180:
        dh = dh_raw - 360
    else:
        dh = dh_raw + 360
    dh_term = 2 * sqrt(cp1 * cp2) * sin(radians(dh / 2))
    l_bar, cp_bar = (l1 + l2) / 2, (cp1 + cp2) / 2
    if cp1 * cp2 == 0:
        hp_bar = hp1 + hp2
    elif abs(hp1 - hp2) <= 180:
        hp_bar = (hp1 + hp2) / 2
    elif hp1 + hp2 < 360:
        hp_bar = (hp1 + hp2 + 360) / 2
    else:
        hp_bar = (hp1 + hp2 - 360) / 2
    t = (
        1
        - .17 * cos(radians(hp_bar - 30))
        + .24 * cos(radians(2 * hp_bar))
        + .32 * cos(radians(3 * hp_bar + 6))
        - .20 * cos(radians(4 * hp_bar - 63))
    )
    sl = 1 + .015 * pow(l_bar - 50, 2) / sqrt(20 + pow(l_bar - 50, 2))
    sc = 1 + .045 * cp_bar
    sh = 1 + .015 * cp_bar * t
    rt = (
        -2
        * sqrt(pow(cp_bar, 7) / (pow(cp_bar, 7) + pow(25, 7)))
        * sin(radians(60 * exp(-pow((hp_bar - 275) / 25, 2))))
    )
    return sqrt(
        pow(dl / sl, 2)
        + pow(dc / sc, 2)
        + pow(dh_term / sh, 2)
        + rt * (dc / sc) * (dh_term / sh)
    )


_MARD_LAB = tuple((color, _lab(color.rgb)) for color in MARD_STANDARD_PALETTE)


def _nearest_mard(
    rgb: tuple[int, int, int],
    palette: tuple[tuple[MardColor, tuple[float, float, float]], ...] = _MARD_LAB,
) -> tuple[MardColor, float]:
    target = _lab(rgb)
    color, color_lab = min(palette, key=lambda item: _delta_e_2000(target, item[1]))
    return color, round(_delta_e_2000(target, color_lab), 3)


def _board_id(x: int, y: int, columns: int) -> str:
    return f"{chr(65 + y // BOARD_SIZE)}{x // BOARD_SIZE + 1}"


def _layout(value: str) -> tuple[int, int, int, int]:
    if value in BOARD_LAYOUTS:
        return BOARD_LAYOUTS[value]
    if value.startswith("custom_") and "x" in value:
        try:
            columns, rows = (int(item) for item in value.removeprefix("custom_").split("x", 1))
        except ValueError as exc:
            raise ValueError("BOARD_LAYOUT_UNSUPPORTED") from exc
        if 1 <= columns <= 6 and 1 <= rows <= 6 and columns * rows <= 12:
            return columns * BOARD_SIZE, rows * BOARD_SIZE, columns, rows
    raise ValueError("BOARD_LAYOUT_UNSUPPORTED")


def _edge_strength(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    return gray.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))


def _remove_obvious_border_background(source: Image.Image) -> tuple[Image.Image, dict]:
    """Clear only a pale, border-connected backdrop before sampling beads.

    Confirmed 2D files can be imported with an opaque white/ivory canvas.  That
    canvas has no physical counterpart in a fuse-bead pattern and must not use
    colour budget or create thousands of background beads.  This intentionally
    does *not* attempt general subject extraction: it runs only when at least
    three corners agree on a bright, low-chroma colour and clears only the
    connected region reached from the image border.  Pale highlights enclosed
    by the character therefore remain intact.
    """
    image = source.convert("RGBA")
    alpha = image.getchannel("A")
    width, height = image.size
    corners = [
        image.getpixel((0, 0)), image.getpixel((width - 1, 0)),
        image.getpixel((0, height - 1)), image.getpixel((width - 1, height - 1)),
    ]
    opaque_corners = [pixel[:3] for pixel in corners if pixel[3] >= 240]
    if len(opaque_corners) < 3:
        return image, {"applied": False, "removedPixels": 0, "reason": "transparent-or-mixed-corners"}

    def luma(rgb: tuple[int, int, int]) -> float:
        return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]

    reference = tuple(round(sum(pixel[index] for pixel in opaque_corners) / len(opaque_corners)) for index in range(3))
    spread = max(max(abs(pixel[index] - reference[index]) for index in range(3)) for pixel in opaque_corners)
    if luma(reference) < 218 or max(reference) - min(reference) > 30 or spread > 24:
        return image, {"applied": False, "removedPixels": 0, "reason": "corner-background-not-obvious"}

    pixels = image.load()

    def is_background_candidate(x: int, y: int) -> bool:
        red, green, blue, value_alpha = pixels[x, y]
        if value_alpha < 18:
            return False
        rgb = (red, green, blue)
        # Slightly wider than the corner comparison so antialiased backdrop
        # pixels disappear too, but still excludes skin, gold and coloured art.
        return (
            luma(rgb) >= 202
            and max(rgb) - min(rgb) <= 42
            and max(abs(rgb[index] - reference[index]) for index in range(3)) <= 58
        )

    queue: deque[tuple[int, int]] = deque()
    visited: set[tuple[int, int]] = set()
    for x in range(width):
        queue.extend(((x, 0), (x, height - 1)))
    for y in range(1, max(1, height - 1)):
        queue.extend(((0, y), (width - 1, y)))
    while queue:
        point = queue.popleft()
        if point in visited:
            continue
        x, y = point
        if not is_background_candidate(x, y):
            continue
        visited.add(point)
        for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            nx, ny = neighbour
            if 0 <= nx < width and 0 <= ny < height and neighbour not in visited:
                queue.append(neighbour)
    # A tiny light strip at an edge is not a canvas background.
    if len(visited) < max(64, round(width * height * .025)):
        return image, {"applied": False, "removedPixels": 0, "reason": "background-region-too-small"}

    cleaned_alpha = alpha.copy()
    cleaned = cleaned_alpha.load()
    for x, y in visited:
        cleaned[x, y] = 0
    image.putalpha(cleaned_alpha)
    return image, {"applied": True, "removedPixels": len(visited), "reason": "border-connected-pale-background"}


def _is_skin(rgb: tuple[int, int, int]) -> bool:
    """Broad display-skin classifier used only to allocate detail budget."""
    red, green, blue = rgb
    maximum, minimum = max(rgb), min(rgb)
    return (
        red > 72
        and red > green * 1.03
        and green > blue * 1.06
        and maximum - minimum > 12
        and red - green < 105
    )


def _components(points: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    remaining = set(points)
    result: list[set[tuple[int, int]]] = []
    while remaining:
        first = remaining.pop()
        pending = [first]
        component = {first}
        while pending:
            x, y = pending.pop()
            for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    component.add(neighbour)
                    pending.append(neighbour)
        result.append(component)
    return result


def _expand(points: set[tuple[int, int]], radius: int, width: int, height: int) -> set[tuple[int, int]]:
    return {
        (x + dx, y + dy)
        for x, y in points
        for dx in range(-radius, radius + 1)
        for dy in range(-radius, radius + 1)
        if 0 <= x + dx < width and 0 <= y + dy < height
    }


def _semantic_regions(
    placed: Image.Image,
    edges: Image.Image,
    visible: set[tuple[int, int]],
    structural_ink: Image.Image | None = None,
    semantic_plan: dict | None = None,
) -> dict[tuple[int, int], str]:
    """Infer high-value regions from a clean, transparent 2D character asset.

    P1 intentionally stays deterministic. It does not invent pixels or call a
    model; regions only change sampling weight and local cleanup protection.
    """
    width, height = placed.size
    pixels, edge_pixels = placed.load(), edges.load()
    ink_pixels = structural_ink.load() if structural_ink is not None else None
    min_x = min(x for x, _ in visible)
    max_x = max(x for x, _ in visible)
    min_y = min(y for _, y in visible)
    max_y = max(y for _, y in visible)
    subject_width = max(1, max_x - min_x + 1)
    subject_height = max(1, max_y - min_y + 1)

    # Face: prefer a compact skin component in the upper 56% of the subject.
    skin = {
        (x, y)
        for x, y in visible
        if _is_skin(pixels[x, y][:3])
    }
    plausible_faces = []
    for component in _components(skin):
        xs, ys = [x for x, _ in component], [y for _, y in component]
        component_width = max(xs) - min(xs) + 1
        component_height = max(ys) - min(ys) + 1
        if (
            len(component) >= 3
            and sum(y for _, y in component) / len(component) <= min_y + subject_height * .60
            # Chibi heads are deliberately large.  The former 42%/30% cap
            # rejected a normal head by one or two grid cells, which in turn
            # meant neither face nor hands received their detail protection.
            and component_width <= subject_width * .56
            and component_height <= subject_height * .40
        ):
            plausible_faces.append(component)
    face = max(
        plausible_faces,
        key=lambda item: len(item) * (1.4 - (sum(y for _, y in item) / len(item) - min_y) / subject_height),
        default=set(),
    )
    face_zone = _expand(face, 1, width, height) & visible
    # Hands often contain just a few beads.  They must get their own protection
    # instead of being treated as generic clothing and smoothed away.  This is
    # still source-led: a hand receives no invented fingers or creases.
    hands: set[tuple[int, int]] = set()
    for component in _components(skin):
        if component == face or len(component) < 2:
            continue
        average_y = sum(y for _, y in component) / len(component)
        if average_y >= min_y + subject_height * .34:
            hands |= _expand(component, 1, width, height) & visible
    if face:
        # In small chibi illustrations a hand can touch the cheek or neck and
        # therefore arrive as part of the same skin component.  Do not invent
        # a separate hand shape; simply give the lower exposed skin edge the
        # same contrast protection as an already separate hand component.
        face_top = min(y for _, y in face)
        face_height = max(y for _, y in face) - face_top + 1
        lower_exposed_skin = {
            point
            for point in face
            if (
                point[1] >= face_top + face_height * .62
                and point[1] >= min_y + subject_height * .42
                and edge_pixels[point[0], point[1]] >= 28
            )
        }
        hands |= lower_exposed_skin
    facial_detail: set[tuple[int, int]] = set()
    if face:
        face_colors = [pixels[x, y][:3] for x, y in face]
        face_luma = sum(.2126 * r + .7152 * g + .0722 * b for r, g, b in face_colors) / len(face_colors)
        xs, ys = [x for x, _ in face], [y for _, y in face]
        box = (
            max(min_x, min(xs) - 2),
            max(min_y, min(ys) - 2),
            min(max_x, max(xs) + 2),
            min(max_y, max(ys) + 2),
        )
        for x, y in visible:
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                red, green, blue = pixels[x, y][:3]
                luma = .2126 * red + .7152 * green + .0722 * blue
                if luma < face_luma - 22 or edge_pixels[x, y] >= 80:
                    facial_detail.add((x, y))

    # Weapon/accessory: visible protrusions that are locally thin and far from
    # the subject's robust central body. This covers swords, staffs and hairpins.
    centre_x = (min_x + max_x) / 2
    centre_y = (min_y + max_y) / 2
    weapon_seeds: set[tuple[int, int]] = set()
    for x, y in visible:
        local = sum(
            (x + dx, y + dy) in visible
            for dx in range(-2, 3)
            for dy in range(-2, 3)
        )
        outside_core = (
            abs(x - centre_x) > subject_width * .27
            or abs(y - centre_y) > subject_height * .38
        )
        if outside_core and local <= 15 and edge_pixels[x, y] >= 28:
            weapon_seeds.add((x, y))
    weapon = _expand(weapon_seeds, 1, width, height) & visible

    regions: dict[tuple[int, int], str] = {}
    clothing_start = min_y + subject_height * .34
    for point in visible:
        x, y = point
        if point in facial_detail:
            region = "facial_detail"
        # This mask is sampled before the illustration is reduced to its bead
        # grid.  It keeps a source-backed, continuous dark outer stroke from
        # being averaged into the adjoining hair or garment fill.
        elif ink_pixels is not None and ink_pixels[x, y][3] >= 58:
            region = "outline"
        elif point in face_zone:
            region = "face"
        elif point in hands:
            region = "hand"
        elif point in weapon:
            region = "weapon"
        elif edge_pixels[x, y] >= 72:
            region = "outline"
        elif y >= clothing_start:
            region = "clothing"
        else:
            region = "base"
        regions[point] = region
    if semantic_plan:
        visible_left = min(x for x, _ in visible)
        visible_right = max(x for x, _ in visible)
        visible_top = min(y for _, y in visible)
        visible_bottom = max(y for _, y in visible)

        def plan_x(value: float) -> int:
            return round(visible_left + value * (visible_right - visible_left))

        def plan_y(value: float) -> int:
            return round(visible_top + value * (visible_bottom - visible_top))

        face_box = semantic_plan.get("faceBox")
        if face_box:
            left, top, right, bottom = (
                plan_x(face_box[0]), plan_y(face_box[1]),
                plan_x(face_box[2]), plan_y(face_box[3]),
            )
            for x, y in visible:
                if left <= x <= right and top <= y <= bottom:
                    regions[(x, y)] = "face"
        for box in semantic_plan.get("garmentBoxes", []):
            left, top, right, bottom = (
                plan_x(box[0]), plan_y(box[1]),
                plan_x(box[2]), plan_y(box[3]),
            )
            for x, y in visible:
                if left <= x <= right and top <= y <= bottom and regions[(x, y)] == "base":
                    regions[(x, y)] = "clothing"
        for point in semantic_plan.get("facialKeypoints", []):
            centre_x = plan_x(point["x"])
            centre_y = plan_y(point["y"])
            radius = int(point.get("radius", 1))
            for x, y in _expand({(centre_x, centre_y)}, radius, width, height) & visible:
                regions[(x, y)] = "facial_detail"
        for path in semantic_plan.get("thinFeaturePaths", []):
            points = path.get("points", [])
            thickness = int(path.get("thickness", 2))
            for start, end in zip(points, points[1:]):
                x0, y0 = plan_x(start[0]), plan_y(start[1])
                x1, y1 = plan_x(end[0]), plan_y(end[1])
                steps = max(abs(x1 - x0), abs(y1 - y0), 1)
                line = {
                    (round(x0 + (x1 - x0) * step / steps), round(y0 + (y1 - y0) * step / steps))
                    for step in range(steps + 1)
                }
                for x, y in _expand(line, max(0, thickness - 1), width, height) & visible:
                    regions[(x, y)] = "weapon"
    return regions


def _prepare_grid(source: Image.Image, width: int, height: int) -> tuple[Image.Image, Image.Image, Image.Image]:
    source = source.crop(source.getchannel("A").getbbox())
    scale = min((width - 4) / source.width, (height - 4) / source.height)
    target_size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    # Resize premultiplied RGBA, then unpremultiply on the small target grid.
    # Pillow's normal RGBA resize can mix transparent canvas RGB into opaque
    # edge pixels. That creates several false near-skin shades even when the
    # 2D asset has one flat face colour.
    source_alpha = source.getchannel("A")
    # BOX sampling deliberately avoids bicubic ringing.  Ringing creates
    # several near-identical pixels across a flat cheek or garment and then
    # turns them into false MARD shades.  BOX preserves real 2D colour blocks
    # while still averaging the source into a target bead cell.
    premultiplied = [
        ImageChops.multiply(channel, source_alpha).resize(target_size, Image.Resampling.BOX)
        for channel in source.convert("RGB").split()
    ]
    alpha = source_alpha.resize(target_size, Image.Resampling.BOX)
    output_channels = [Image.new("L", target_size, 0) for _ in range(3)]
    alpha_pixels = alpha.load()
    premultiplied_pixels = [channel.load() for channel in premultiplied]
    output_pixels = [channel.load() for channel in output_channels]
    for y in range(target_size[1]):
        for x in range(target_size[0]):
            value_alpha = alpha_pixels[x, y]
            if value_alpha < 18:
                continue
            for index in range(3):
                output_pixels[index][x, y] = min(255, round(premultiplied_pixels[index][x, y] * 255 / value_alpha))
    rgb = Image.merge("RGB", tuple(output_channels))

    # Keep a second, ink-only resample.  The normal BOX image correctly makes
    # flat fills stable, but it can dilute a 6–14px hair or garment outline to
    # the fill colour when that outline occupies only part of a future bead.
    # The mask is deliberately conservative: it accepts dark, high-contrast
    # source strokes and leaves low-contrast interior shading to normal
    # simplification.
    source_edges = source.convert("L").filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    source_pixels, source_edge_pixels, source_alpha_pixels = source.convert("RGB").load(), source_edges.load(), source_alpha.load()
    ink_alpha = Image.new("L", source.size, 0)
    ink_alpha_pixels = ink_alpha.load()
    for y in range(source.height):
        for x in range(source.width):
            if source_alpha_pixels[x, y] < 160:
                continue
            red, green, blue = source_pixels[x, y]
            luma = .2126 * red + .7152 * green + .0722 * blue
            # Very dark hair/fabric and dark pixels on a strong boundary are
            # both legitimate outline evidence.  Pale or low-contrast folds
            # are intentionally not promoted here.
            if luma <= 108 or (luma <= 158 and source_edge_pixels[x, y] >= 72):
                ink_alpha_pixels[x, y] = source_alpha_pixels[x, y]
    ink_channels = [
        ImageChops.multiply(channel, ink_alpha).resize(target_size, Image.Resampling.BOX)
        for channel in source.convert("RGB").split()
    ]
    ink_alpha_small = ink_alpha.resize(target_size, Image.Resampling.BOX)
    ink_output_channels = [Image.new("L", target_size, 0) for _ in range(3)]
    ink_alpha_small_pixels = ink_alpha_small.load()
    ink_channel_pixels = [channel.load() for channel in ink_channels]
    ink_output_pixels = [channel.load() for channel in ink_output_channels]
    for y in range(target_size[1]):
        for x in range(target_size[0]):
            ink_value = ink_alpha_small_pixels[x, y]
            if ink_value < 1:
                continue
            for index in range(3):
                ink_output_pixels[index][x, y] = min(255, round(ink_channel_pixels[index][x, y] * 255 / ink_value))

    # Do not dilate alpha after resampling.  A dilation makes formerly
    # transparent pixels eligible for bead placement and can turn antialiased
    # edge colours into invented shadow beads.  A thin source feature remains
    # visible through the normal alpha threshold; absent source pixels remain
    # absent.
    placed = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    structural_ink = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    offset = ((width - target_size[0]) // 2, (height - target_size[1]) // 2)
    placed.paste(Image.merge("RGBA", (*rgb.split(), alpha)), offset)
    structural_ink.paste(Image.merge("RGBA", (*ink_output_channels, ink_alpha_small)), offset)
    return placed, _edge_strength(placed), structural_ink


def _select_palette(
    pixels: list[tuple[tuple[int, int, int], int, str]],
    limit: int,
) -> tuple[tuple[MardColor, tuple[float, float, float]], ...]:
    """Select real bead colours with protected regional palette allocations."""
    scores: Counter[str] = Counter()
    regional_scores: dict[str, Counter[str]] = {
        name: Counter() for name in REGION_WEIGHTS
    }
    colors_by_code = {color.code: color for color in MARD_STANDARD_PALETTE}
    cache: dict[tuple[int, int, int], tuple[MardColor, float]] = {}
    for rgb, importance, region in pixels:
        if rgb not in cache:
            cache[rgb] = _nearest_mard(rgb)
        color, distance = cache[rgb]
        saturation = rgb_to_hsv(*(value / 255 for value in rgb))[1]
        score = importance * (1 + .25 * saturation) / (1 + .03 * distance)
        scores[color.code] += score
        regional_scores[region][color.code] += score

    selected_codes: list[str] = []
    # Small high-value regions get first claim on the budget instead of being
    # swallowed by a large garment. Quotas are maxima, not forced colours.
    quotas = {
        "facial_detail": 2 if limit <= 12 else 3,
        "face": 2 if limit <= 12 else 4,
        "hand": 2 if limit <= 12 else 3,
        "weapon": 2 if limit <= 12 else 4,
        "outline": 1 if limit <= 12 else 2,
        "clothing": 3 if limit <= 12 else (7 if limit <= 24 else 12),
    }
    for region in ("facial_detail", "face", "hand", "weapon", "outline", "clothing"):
        for code, _ in regional_scores[region].most_common(quotas[region]):
            if code not in selected_codes and len(selected_codes) < limit:
                selected_codes.append(code)
    for code, _ in scores.most_common():
        if code not in selected_codes and len(selected_codes) < limit:
            selected_codes.append(code)
    selected = [colors_by_code[code] for code in selected_codes]
    return tuple((color, _lab(color.rgb)) for color in selected)


def _stable_palette(source: Image.Image, color_mode: str, semantic_plan: dict | None = None) -> tuple[
    tuple[MardColor, tuple[float, float, float]], ...
]:
    """Choose colours on a fixed analysis grid, independent of board size.

    A larger board may reveal more edges, but it must not silently replace the
    garment's identity colours.  Using one canonical analysis resolution keeps
    2x2 and 3x3 outputs chromatically comparable.
    """
    placed, edges, structural_ink = _prepare_grid(source, ANALYSIS_SIZE, ANALYSIS_SIZE)
    pixels, edge_pixels, ink_pixels = placed.load(), edges.load(), structural_ink.load()
    visible = {
        (x, y)
        for y in range(ANALYSIS_SIZE)
        for x in range(ANALYSIS_SIZE)
        if pixels[x, y][3] >= 18
    }
    regions = _semantic_regions(placed, edges, visible, structural_ink, semantic_plan)
    samples = [
        (
            ink_pixels[x, y][:3] if regions[(x, y)] == "outline" and ink_pixels[x, y][3] >= 58 else pixels[x, y][:3],
            (1 + min(4, edge_pixels[x, y] // 48)) * REGION_WEIGHTS[regions[(x, y)]],
            regions[(x, y)],
        )
        for x, y in visible
    ]
    return _select_palette(samples, COLOR_LIMITS[color_mode])


def _refine_facial_features(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
    regions: dict[tuple[int, int], str],
    selected_palette: tuple[tuple[MardColor, tuple[float, float, float]], ...],
) -> dict[tuple[int, int], tuple[MardColor, float]]:
    """Keep facial detail source-led; never synthesize eyes, brows or shading.

    This is deliberately conservative and symbolic: it only operates inside a
    detected face, requires enough bead area, and adds at most paired brows,
    paired eyes and a short mouth. Existing feature cells are retained.
    """
    # The local engine used to paint a generic face whenever a skin-coloured
    # region was sufficiently large. That makes a smooth 2D face gain dark
    # blocks which were never present in the asset. Mapping preserves source
    # detail; absence of source detail now deliberately means no edit.
    return assignments

    face_points = {
        point for point, region in regions.items()
        if region in {"face", "facial_detail"} and point in assignments
    }
    if len(face_points) < 20:
        return assignments
    xs = [x for x, _ in face_points]
    ys = [y for _, y in face_points]
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    face_width, face_height = right - left + 1, bottom - top + 1
    if face_width < 6 or face_height < 7:
        return assignments

    face_colors = [assignments[point][0] for point in face_points]
    base_luma = sum(
        .2126 * color.rgb[0] + .7152 * color.rgb[1] + .0722 * color.rgb[2]
        for color in face_colors
    ) / len(face_colors)
    dark_candidates = [
        item for item in selected_palette
        if (.2126 * item[0].rgb[0] + .7152 * item[0].rgb[1] + .0722 * item[0].rgb[2])
        < base_luma - 30
    ]
    if not dark_candidates:
        return assignments
    detail_color = min(
        dark_candidates,
        key=lambda item: .2126 * item[0].rgb[0] + .7152 * item[0].rgb[1] + .0722 * item[0].rgb[2],
    )[0]
    mouth_candidates = sorted(
        selected_palette,
        key=lambda item: (
            -((item[0].rgb[0] - item[0].rgb[1]) + (item[0].rgb[0] - item[0].rgb[2])),
            _delta_e_2000(_lab((150, 55, 60)), item[1]),
        ),
    )
    mouth_color = mouth_candidates[0][0] if mouth_candidates else detail_color

    def nearest_face(target_x: int, target_y: int) -> tuple[int, int] | None:
        candidates = [
            point for point in face_points
            if abs(point[0] - target_x) <= 1 and abs(point[1] - target_y) <= 1
        ]
        return min(
            candidates,
            key=lambda point: abs(point[0] - target_x) + abs(point[1] - target_y),
            default=None,
        )

    centre_x = (left + right) / 2
    eye_y = round(top + face_height * .43)
    brow_y = max(top, eye_y - 1)
    mouth_y = round(top + face_height * .72)
    eye_offset = max(1, round(face_width * .20))
    targets = [
        (round(centre_x - eye_offset), brow_y, detail_color),
        (round(centre_x + eye_offset), brow_y, detail_color),
        (round(centre_x - eye_offset), eye_y, detail_color),
        (round(centre_x + eye_offset), eye_y, detail_color),
        (round(centre_x), mouth_y, mouth_color),
    ]
    result = dict(assignments)
    for target_x, target_y, color in targets:
        point = nearest_face(target_x, target_y)
        if point is not None:
            result[point] = (color, 0.0)
            regions[point] = "facial_detail"
    return result


def _apply_model_guidance(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
    regions: dict[tuple[int, int], str],
    pixels,
    selected_palette: tuple[tuple[MardColor, tuple[float, float, float]], ...],
    semantic_plan: dict | None,
    width: int,
    height: int,
) -> tuple[dict[tuple[int, int], tuple[MardColor, float]], int]:
    """Turn model geometry into bounded, measurable grid edits.

    Earlier versions only relabelled semantic regions. That could affect palette
    weighting or cleanup, but often produced a byte-for-byte identical grid
    while reporting that the model plan had been applied. This pass makes the
    plan actionable: facial keypoints receive a readable dark bead and thin
    features are made colour-continuous along their model-provided paths.
    """
    if not semantic_plan or not assignments:
        return assignments, 0

    result = dict(assignments)
    before = {point: value[0].code for point, value in assignments.items()}
    visible = set(assignments)
    xs = [x for x, _ in visible]
    ys = [y for _, y in visible]
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)

    def plan_x(value: float) -> int:
        return round(left + value * (right - left))

    def plan_y(value: float) -> int:
        return round(top + value * (bottom - top))

    def luma(color: MardColor) -> float:
        red, green, blue = color.rgb
        return .2126 * red + .7152 * green + .0722 * blue

    # Use a dark-but-not-always-black official bead for eyes and brows.
    dark_palette = sorted(selected_palette, key=lambda item: luma(item[0]))
    detail_color = next(
        (item[0] for item in dark_palette if luma(item[0]) < 92),
        dark_palette[0][0],
    )
    for item in semantic_plan.get("facialKeypoints", []):
        centre = (plan_x(item["x"]), plan_y(item["y"]))
        radius = max(1, min(2, int(item.get("radius", 1))))
        candidates = _expand({centre}, radius, width, height) & visible
        if not candidates:
            continue
        target = min(
            candidates,
            key=lambda point: abs(point[0] - centre[0]) + abs(point[1] - centre[1]),
        )
        result[target] = (detail_color, 0.0)
        regions[target] = "facial_detail"

    # A sword/hat edge can be technically present yet visually fragmented by
    # independent nearest-colour mapping. Sample one representative official
    # colour per path, then apply it conservatively to path cells that belong to
    # the visible subject. This changes colour continuity, never arbitrary shape.
    for path in semantic_plan.get("thinFeaturePaths", []):
        normalized = path.get("points", [])
        if len(normalized) < 2:
            continue
        line: set[tuple[int, int]] = set()
        for start, end in zip(normalized, normalized[1:]):
            x0, y0 = plan_x(start[0]), plan_y(start[1])
            x1, y1 = plan_x(end[0]), plan_y(end[1])
            steps = max(abs(x1 - x0), abs(y1 - y0), 1)
            line.update({
                (round(x0 + (x1 - x0) * step / steps), round(y0 + (y1 - y0) * step / steps))
                for step in range(steps + 1)
            })
        thickness = max(1, min(3, int(path.get("thickness", 2))))
        path_cells = _expand(line, thickness - 1, width, height) & visible
        if len(path_cells) < 2:
            continue
        source_rgb = [
            pixels[x, y][:3] for x, y in path_cells
            if pixels[x, y][3] >= 18
        ]
        if not source_rgb:
            continue
        representative = tuple(
            round(sum(rgb[channel] for rgb in source_rgb) / len(source_rgb))
            for channel in range(3)
        )
        path_color, distance = _nearest_mard(representative, selected_palette)
        for point in path_cells:
            result[point] = (path_color, distance)
            regions[point] = "weapon"

    changed = sum(
        before.get(point) != value[0].code
        for point, value in result.items()
    )
    return result, changed


def _clean_cells(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
    edge_values: dict[tuple[int, int], int],
    regions: dict[tuple[int, int], str],
) -> dict[tuple[int, int], tuple[MardColor, float]]:
    """Remove isolated colour noise without erasing protected edges."""
    result = dict(assignments)
    for (x, y), value in assignments.items():
        if regions.get((x, y)) in {"face", "facial_detail", "weapon"}:
            continue
        if edge_values.get((x, y), 0) >= 70:
            continue
        neighbours = [
            assignments.get((x + dx, y + dy))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
        ]
        neighbours = [item for item in neighbours if item]
        if len(neighbours) < 3:
            continue
        codes = Counter(item[0].code for item in neighbours)
        common, count = codes.most_common(1)[0]
        if count >= 3 and common != value[0].code:
            replacement = next(item for item in neighbours if item[0].code == common)
            result[(x, y)] = replacement
    return result


def _collapse_unproven_near_colour_cells(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
    pixels,
    regions: dict[tuple[int, int], str],
) -> tuple[dict[tuple[int, int], tuple[MardColor, float]], int]:
    """Merge a mapped shade only when the 2D source has no real contrast for it.

    Anti-aliasing produces tiny RGB variations along a flat fill.  Mapping each
    variation independently to the MARD catalogue can make them look like
    deliberate facial shading.  A cell is merged only when three neighbours
    agree on one bead colour *and* its source RGB is within a small difference
    of those neighbours.  Real blush, lines and material boundaries have
    visible source contrast and are left untouched.
    """
    result = dict(assignments)
    changed = 0
    for (x, y), value in assignments.items():
        # A coarse, source-backed silhouette is more important than removing a
        # one-bead colour difference at its edge.  Do not let this final noise
        # pass erase hair, headwear or garment contours that were explicitly
        # identified before downsampling.
        if regions.get((x, y)) in {"outline", "hand", "weapon", "facial_detail"}:
            continue
        neighbours = [
            ((x + dx, y + dy), assignments.get((x + dx, y + dy)))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
        ]
        populated = [(point, item) for point, item in neighbours if item is not None]
        if len(populated) < 3:
            continue
        codes = Counter(item[0].code for _, item in populated)
        common, count = codes.most_common(1)[0]
        if count < 3 or common == value[0].code:
            continue
        matching = [(point, item) for point, item in populated if item[0].code == common]
        source_rgb = pixels[x, y][:3]
        neighbour_rgb = tuple(
            round(sum(pixels[point[0], point[1]][channel] for point, _ in matching) / len(matching))
            for channel in range(3)
        )
        if max(abs(source_rgb[channel] - neighbour_rgb[channel]) for channel in range(3)) > 22:
            continue
        result[(x, y)] = matching[0][1]
        changed += 1
    return result, changed


def _collapse_flat_source_variants(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
    pixels,
    regions: dict[tuple[int, int], str],
) -> tuple[dict[tuple[int, int], tuple[MardColor, float]], int]:
    """Keep real blocks, but collapse near-identical sampling variants.

    A flat 2D fill should become one readable bead block.  MARD matching can
    otherwise map two nearly identical sampled RGB values to neighbouring bead
    colours, especially in large faces and fabric fills.  We use the most
    common *source* RGB in each semantic region as evidence, then only merge
    cells that are perceptually very close to that source.  Strong cheek,
    chin, seam and intentional shadow colours remain distinct.
    """
    result = dict(assignments)
    changed = 0
    # These values deliberately cover normal downsampling variation, not
    # independent painted tones.  The former 9/7 thresholds were too close to
    # the variation produced by a 2D export, so cheeks and broad fabric fills
    # still became several neighbouring MARD colours.
    thresholds = {"face": 15.0, "clothing": 13.0}
    for region, threshold in thresholds.items():
        points = [point for point in assignments if regions.get(point) == region]
        if len(points) < 8:
            continue
        source_counts = Counter(pixels[x, y][:3] for x, y in points)
        base_rgb, _ = source_counts.most_common(1)[0]
        base_point = next(
            point for point in points
            if pixels[point[0], point[1]][:3] == base_rgb
        )
        base_assignment = assignments[base_point]
        base_lab = _lab(base_rgb)
        for point in points:
            rgb = pixels[point[0], point[1]][:3]
            if _delta_e_2000(_lab(rgb), base_lab) > threshold:
                continue
            if result[point][0].code != base_assignment[0].code:
                result[point] = base_assignment
                changed += 1
    return result, changed


def _collapse_low_contrast_blocks(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
    pixels,
    edge_values: dict[tuple[int, int], int],
    regions: dict[tuple[int, int], str],
) -> tuple[dict[tuple[int, int], tuple[MardColor, float]], int]:
    """Remove broad, low-evidence face/fabric shade islands.

    A single-bead clean-up cannot catch a large, softly sampled shadow.  This
    pass treats one connected official-colour island as an accidental shade
    only when it borders one dominant colour, has little structural edge
    evidence, and the *source* pixels are perceptually close to that border.
    Thus a real seam, blush or a dark garment panel remains, while a broad
    low-contrast patch is reduced to the 2D asset's primary readable block.
    """
    result = dict(assignments)
    changed = 0
    visited: set[tuple[int, int]] = set()
    thresholds = {"face": 18.0, "clothing": 15.0}
    for start, value in assignments.items():
        if start in visited:
            continue
        region = regions.get(start)
        if region not in thresholds:
            continue
        code = value[0].code
        component = {start}
        pending = [start]
        visited.add(start)
        while pending:
            x, y = pending.pop()
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                neighbour = assignments.get(point)
                if (
                    point not in visited
                    and neighbour is not None
                    and neighbour[0].code == code
                    and regions.get(point) == region
                ):
                    visited.add(point)
                    component.add(point)
                    pending.append(point)
        # Keep tiny details for the existing single-bead pass.  This is for a
        # visible but unsupported *block* such as an overly wide garment shade.
        if len(component) < 3:
            continue
        border = []
        for x, y in component:
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                neighbour = assignments.get(point)
                if neighbour is not None and point not in component:
                    border.append((point, neighbour))
        if len(border) < 3:
            continue
        border_codes = Counter(item[0].code for _, item in border)
        replacement_code, replacement_hits = border_codes.most_common(1)[0]
        # An actual boundary generally has multiple neighbouring materials;
        # do not flatten it merely because one side happens to be larger.
        if replacement_hits / len(border) < .68 or replacement_code == code:
            continue
        if sum(edge_values.get(point, 0) >= 72 for point in component) / len(component) > .18:
            continue
        replacement_points = [point for point, item in border if item[0].code == replacement_code]
        source_component = tuple(
            round(sum(pixels[x, y][channel] for x, y in component) / len(component))
            for channel in range(3)
        )
        source_border = tuple(
            round(sum(pixels[x, y][channel] for x, y in replacement_points) / len(replacement_points))
            for channel in range(3)
        )
        if _delta_e_2000(_lab(source_component), _lab(source_border)) > thresholds[region]:
            continue
        replacement = next(item for point, item in border if item[0].code == replacement_code)
        for point in component:
            if result[point][0].code != replacement_code:
                result[point] = replacement
                changed += 1
    return result, changed


def _preserve_hand_contrast(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
    pixels,
    regions: dict[tuple[int, int], str],
    selected_palette: tuple[tuple[MardColor, tuple[float, float, float]], ...],
) -> tuple[dict[tuple[int, int], tuple[MardColor, float]], int]:
    """Keep source-backed hands visually distinct from adjacent clothing.

    This never draws fingers or enlarges a hand.  It only changes a mapped
    bead where the source already has a clear hand/garment boundary but two
    nearest catalogue matches collapse that contrast into nearly one colour.
    """
    result = dict(assignments)
    changed = 0
    for point, value in assignments.items():
        if regions.get(point) != "hand":
            continue
        x, y = point
        neighbours = [
            ((x + dx, y + dy), assignments.get((x + dx, y + dy)))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
        ]
        neighbours = [
            (other_point, other)
            for other_point, other in neighbours
            if other is not None and regions.get(other_point) in {"clothing", "base", "outline"}
        ]
        if not neighbours:
            continue
        other_point, other = min(
            neighbours,
            key=lambda item: _delta_e_2000(_lab(value[0].rgb), _lab(item[1][0].rgb)),
        )
        source_gap = _delta_e_2000(_lab(pixels[x, y][:3]), _lab(pixels[other_point[0], other_point[1]][:3]))
        mapped_gap = _delta_e_2000(_lab(value[0].rgb), _lab(other[0].rgb))
        if source_gap < 13.0 or mapped_gap >= 9.0:
            continue
        alternatives = [
            item for item in selected_palette
            if _delta_e_2000(item[1], _lab(other[0].rgb)) >= 9.0
        ]
        if not alternatives:
            continue
        replacement, replacement_lab = min(
            alternatives,
            key=lambda item: _delta_e_2000(_lab(pixels[x, y][:3]), item[1]),
        )
        if replacement.code != value[0].code:
            result[point] = (replacement, round(_delta_e_2000(_lab(pixels[x, y][:3]), replacement_lab), 3))
            changed += 1
    return result, changed


def _enforce_mode_palette(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
    color_mode: str,
) -> tuple[dict[tuple[int, int], tuple[MardColor, float]], int, int]:
    """Apply the mode's *maximum* colour budget after official-colour mapping.

    Image models frequently create several nearly identical shadow and highlight
    colours even when prompted not to.  A cap here is intentionally a maximum,
    not a fixed palette size: a character needing fewer colours remains fewer.
    """
    original_count = len({color.code for color, _ in assignments.values()})
    limit = COLOR_LIMITS[color_mode]
    if original_count <= limit:
        return assignments, 0, original_count
    usage = Counter(color.code for color, _ in assignments.values())
    catalog = {color.code: color for color in MARD_STANDARD_PALETTE}
    selected = [catalog[code] for code, _ in usage.most_common(limit)]
    selected_lab = tuple((color, _lab(color.rgb)) for color in selected)
    result: dict[tuple[int, int], tuple[MardColor, float]] = {}
    changed = 0
    for point, (color, distance) in assignments.items():
        if color.code in {item.code for item in selected}:
            result[point] = (color, distance)
            continue
        replacement, replacement_distance = _nearest_mard(color.rgb, selected_lab)
        result[point] = (replacement, replacement_distance)
        changed += replacement.code != color.code
    return result, changed, original_count


def _remove_incidental_single_bead_noise(
    assignments: dict[tuple[int, int], tuple[MardColor, float]],
) -> tuple[dict[tuple[int, int], tuple[MardColor, float]], int]:
    """Remove only a colour speck completely surrounded by one other colour.

    This does not smooth outlines, weapons, facial marks or an exposed edge; it
    addresses the isolated highlight/shadow pixels that cannot be intentionally
    placed from the finished diagram.
    """
    result = dict(assignments)
    changed = 0
    for (x, y), value in assignments.items():
        neighbours = [
            assignments.get((x + dx, y + dy))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
        ]
        if any(item is None for item in neighbours):
            continue
        neighbour_codes = {item[0].code for item in neighbours if item}
        if len(neighbour_codes) != 1:
            continue
        replacement = neighbours[0]
        if replacement and replacement[0].code != value[0].code:
            result[(x, y)] = replacement
            changed += 1
    return result, changed


def generate_pattern(
    image_bytes: bytes,
    *,
    layout: str,
    color_mode: str,
    alpha_threshold: int = 24,
    reference_image_bytes: bytes | None = None,
    semantic_plan: dict | None = None,
) -> dict:
    if color_mode not in COLOR_LIMITS:
        raise ValueError("COLOR_MODE_UNSUPPORTED")

    width, height, board_columns, board_rows = _layout(layout)
    source = Image.open(BytesIO(image_bytes)).convert("RGBA")
    source, background_removal = _remove_obvious_border_background(source)
    if not source.getchannel("A").getbbox():
        raise ValueError("IMAGE_HAS_NO_VISIBLE_PIXELS")
    placed, edges, structural_ink = _prepare_grid(source, width, height)
    pixels, ink_pixels = placed.load(), structural_ink.load()
    edge_pixels = edges.load()
    samples: list[tuple[tuple[int, int, int], int, str]] = []
    visible: list[tuple[int, int]] = []
    threshold = min(alpha_threshold, 18)
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha < threshold:
                continue
            visible.append((x, y))

    regions = _semantic_regions(placed, edges, set(visible), structural_ink, semantic_plan)
    for x, y in visible:
        # When a target bead contains enough of a continuous original outline,
        # map from the ink-only resample instead of its diluted fill average.
        rgb = ink_pixels[x, y][:3] if regions[(x, y)] == "outline" and ink_pixels[x, y][3] >= 58 else pixels[x, y][:3]
        region = regions[(x, y)]
        samples.append((
            rgb,
            (1 + min(4, edge_pixels[x, y] // 48)) * REGION_WEIGHTS[region],
            region,
        ))
    selected_palette = _stable_palette(source, color_mode, semantic_plan)
    mapped: dict[tuple[int, int, int], tuple[MardColor, float]] = {}
    assignments: dict[tuple[int, int], tuple[MardColor, float]] = {}
    edge_values: dict[tuple[int, int], int] = {}
    for x, y in visible:
        rgb = pixels[x, y][:3]
        if rgb not in mapped:
            mapped[rgb] = _nearest_mard(rgb, selected_palette)
        assignments[(x, y)] = mapped[rgb]
        edge_values[(x, y)] = edge_pixels[x, y]
    assignments, guided_changes = _apply_model_guidance(
        assignments,
        regions,
        pixels,
        selected_palette,
        semantic_plan,
        width,
        height,
    )
    assignments, flat_variants_merged = _collapse_flat_source_variants(assignments, pixels, regions)
    assignments, low_contrast_blocks_merged = _collapse_low_contrast_blocks(
        assignments, pixels, edge_values, regions,
    )
    assignments, hand_contrast_preserved = _preserve_hand_contrast(
        assignments, pixels, regions, selected_palette,
    )
    assignments = _clean_cells(assignments, edge_values, regions)
    assignments, unproven_shades_merged = _collapse_unproven_near_colour_cells(assignments, pixels, regions)
    assignments = _refine_facial_features(assignments, regions, selected_palette)

    cells: list[dict] = []
    counts: Counter[str] = Counter()
    distance_sum: Counter[str] = Counter()
    for (x, y), (color, distance) in assignments.items():
        counts[color.code] += 1
        distance_sum[color.code] += distance
        cells.append({
            "x": x,
            "y": y,
            "occupied": True,
            "brand": "MARD",
            "colorCode": color.code,
            "colorValue": color.hex,
            "boardId": _board_id(x, y, board_columns),
            "matchDistanceRgb": distance,
        })

    palette = [
        {
            "brand": "MARD",
            "code": color.code,
            "value": color.hex,
            "count": counts[color.code],
            "averageMatchDistanceRgb": round(distance_sum[color.code] / counts[color.code], 3),
        }
        for color in MARD_STANDARD_PALETTE
        if counts[color.code]
    ]
    isolated = 0
    for x, y in assignments:
        neighbours = sum((x + dx, y + dy) in assignments for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)))
        isolated += neighbours == 0
    region_counts = Counter(regions.values())
    average_delta = sum(distance_sum.values()) / max(1, sum(counts.values()))
    board_area = width * height
    occupancy = len(cells) / max(1, board_area)
    detail_cells = region_counts.get("facial_detail", 0)
    weapon_cells = region_counts.get("weapon", 0)
    structural = min(1.0, detail_cells / 8) * 12 + min(1.0, weapon_cells / 20) * 10
    quality_score = round(max(0, min(100,
        66 + structural - min(24, average_delta * .7) - min(14, isolated * .8)
        - (8 if occupancy > .82 else 0)
    )))
    quality_level = "good" if quality_score >= 82 else "review" if quality_score >= 65 else "insufficient"
    minimum_board = "104×104" if detail_cells < 5 and width < 104 else f"{width}×{height}"
    return {
        "schemaVersion": "1.0",
        "engineVersion": LOCAL_ENGINE_VERSION,
        "revision": 0,
        "width": width,
        "height": height,
        "beadDiameterMm": 5,
        "boardLayout": {
            "type": layout,
            "boardWidth": BOARD_SIZE,
            "boardHeight": BOARD_SIZE,
            "columns": board_columns,
            "rows": board_rows,
            "seamsX": [BOARD_SIZE * item for item in range(1, board_columns)],
            "seamsY": [BOARD_SIZE * item for item in range(1, board_rows)],
        },
        "beadBrand": "MARD",
        "paletteVersion": "official-v1",
        "colorMode": color_mode,
        "cells": cells,
        "palette": palette,
        "statistics": {
            "totalBeads": len(cells),
            "colorCount": len(palette),
            "physicalWidthMm": width * 5,
            "physicalHeightMm": height * 5,
            "averageColorDeltaE": round(average_delta, 3),
            "referenceColorUsed": False,
            "referenceColorPolicy": "disabled-global-bias",
            "backgroundRemoval": background_removal,
            "flatSourceVariantsMerged": flat_variants_merged,
            "lowContrastBlocksMerged": low_contrast_blocks_merged,
            "handContrastCellsPreserved": hand_contrast_preserved,
            "unprovenNearColorCellsMerged": unproven_shades_merged,
            "engineVersion": LOCAL_ENGINE_VERSION,
            "regionPolicy": "model-planned-face-weapon-clothing" if semantic_plan else "stable-palette-symbolic-face-weapon-clothing",
            "regionCounts": dict(region_counts),
            "qualityScore": quality_score,
            "qualityLevel": quality_level,
            "qualityPolicy": "structure-color-makeability-v1",
            "isolatedCellCount": isolated,
            "recommendedMinimumBoard": minimum_board,
            "qualityWarnings": [
                *([] if detail_cells >= 5 else ["面部可辨识细节不足，建议先使用标准 2D 重构或增大图板。"]),
                *([] if weapon_cells >= 12 else ["细长武器/配件的连续结构较弱，需要人工检查。"]),
                *([] if average_delta < 22 else ["真实色号匹配误差偏高，建议检查服饰主色。"]),
            ],
            "semanticPlanning": {
                "used": bool(semantic_plan and guided_changes > 0),
                "planReceived": bool(semantic_plan),
                "appliedCellChanges": guided_changes,
                "plannerVersion": semantic_plan.get("plannerVersion") if semantic_plan else None,
                "model": semantic_plan.get("model") if semantic_plan else None,
                "assessment": semantic_plan.get("assessment") if semantic_plan else None,
                "recommendedAction": semantic_plan.get("recommendedAction") if semantic_plan else None,
                "identityPriorities": semantic_plan.get("identityPriorities", []) if semantic_plan else [],
                "generationMode": "local-deterministic",
            },
        },
    }


def generate_pattern_from_model_grid(model_grid: dict, *, layout: str, color_mode: str) -> dict:
    """Serialize a validated model-authored grid without locally redrawing it."""
    if color_mode not in COLOR_LIMITS:
        raise ValueError("COLOR_MODE_UNSUPPORTED")
    width, height, board_columns, board_rows = _layout(layout)
    target = model_grid.get("targetGrid") or {}
    if target.get("width") != width or target.get("height") != height:
        raise ValueError("PATTERN_MODEL_GRID_SIZE_MISMATCH")
    catalog = {color.code: color for color in MARD_STANDARD_PALETTE}
    assignments: dict[tuple[int, int], MardColor] = {}
    for run in model_grid.get("runs", []):
        color = catalog.get(run.get("colorCode"))
        if color is None:
            continue
        x, y, length = int(run["x"]), int(run["y"]), int(run["length"])
        for cell_x in range(x, x + length):
            if 0 <= cell_x < width and 0 <= y < height:
                assignments[(cell_x, y)] = color
    if not assignments:
        raise ValueError("PATTERN_MODEL_EMPTY_GRID")
    # The legacy structured-grid route receives official colour codes directly,
    # but must still honour the same per-tier maximum as every other route.
    # Convert to the common assignment form so the merger can keep fewer
    # colours when that is sufficient rather than forcing a target count.
    source_color_count = len({color.code for color in assignments.values()})
    enforced, palette_reduced_cells, _ = _enforce_mode_palette(
        {point: (color, 0.0) for point, color in assignments.items()}, color_mode
    )
    assignments = {point: color for point, (color, _distance) in enforced.items()}
    counts: Counter[str] = Counter(color.code for color in assignments.values())
    cells = [{
        "x": x, "y": y, "occupied": True, "brand": "MARD",
        "colorCode": color.code, "colorValue": color.hex,
        "boardId": _board_id(x, y, board_columns), "matchDistanceRgb": 0,
    } for (x, y), color in assignments.items()]
    palette = [{
        "brand": "MARD", "code": color.code, "value": color.hex,
        "count": counts[color.code], "averageMatchDistanceRgb": 0,
    } for color in MARD_STANDARD_PALETTE if counts[color.code]]
    isolated = sum(
        sum((x + dx, y + dy) in assignments for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))) == 0
        for x, y in assignments
    )
    occupancy = len(cells) / (width * height)
    quality_score = round(max(0, min(100, 84 - min(18, isolated * .8) - (8 if occupancy > .86 else 0))))
    return {
        "schemaVersion": "1.0", "engineVersion": DIRECT_MODEL_ENGINE_VERSION, "revision": 0,
        "width": width, "height": height, "beadDiameterMm": 5,
        "boardLayout": {"type": layout, "boardWidth": BOARD_SIZE, "boardHeight": BOARD_SIZE,
            "columns": board_columns, "rows": board_rows,
            "seamsX": [BOARD_SIZE * item for item in range(1, board_columns)],
            "seamsY": [BOARD_SIZE * item for item in range(1, board_rows)]},
        "beadBrand": "MARD", "paletteVersion": "official-v1", "colorMode": color_mode,
        "cells": cells, "palette": palette,
        "statistics": {
            "totalBeads": len(cells), "colorCount": len(palette),
            "physicalWidthMm": width * 5, "physicalHeightMm": height * 5,
            "averageColorDeltaE": 0, "referenceColorUsed": False,
            "referenceColorPolicy": "model-direct-official-mard", "engineVersion": DIRECT_MODEL_ENGINE_VERSION,
            "regionPolicy": "model-authored-grid", "regionCounts": {}, "qualityScore": quality_score,
            "qualityLevel": "good" if quality_score >= 82 else "review",
            "qualityPolicy": "model-grid-makeability-v1", "isolatedCellCount": isolated,
            "recommendedMinimumBoard": f"{width}×{height}",
            "qualityWarnings": [] if isolated < 8 else ["存在较多孤立针位，建议在编辑页检查。"],
            "detailBudget": {
                "mode": color_mode,
                "maximumColors": COLOR_LIMITS[color_mode],
                "modelMappedColorsBeforeMerge": source_color_count,
                "paletteReducedCells": palette_reduced_cells,
            },
            "semanticPlanning": {
                "used": True, "planReceived": True, "appliedCellChanges": None,
                "plannerVersion": model_grid.get("plannerVersion"), "model": model_grid.get("model"),
                "assessment": model_grid.get("assessment"), "recommendedAction": model_grid.get("recommendedAction"),
                "identityPriorities": model_grid.get("identityPriorities", []),
                "generationMode": "direct-model-grid",
            },
        },
    }


def generate_pattern_from_model_image(
    image_bytes: bytes,
    *,
    layout: str,
    color_mode: str,
    model: str,
) -> dict:
    """Turn a model-authored pixel-ready image into a pattern without redrawing it.

    The image model decides silhouette, details and colour relationships.  This
    function is deliberately mechanical: crop transparent margins, sample one
    source pixel per bead with nearest-neighbour resampling, then map that
    pixel to the official MARD catalogue.  It does not use semantic regions,
    palette optimisation, clean-up, face repair, or a local draft.
    """
    if color_mode not in COLOR_LIMITS:
        raise ValueError("COLOR_MODE_UNSUPPORTED")
    width, height, board_columns, board_rows = _layout(layout)
    source = Image.open(BytesIO(image_bytes)).convert("RGBA")
    source, background_removal = _remove_obvious_border_background(source)
    alpha_box = source.getchannel("A").getbbox()
    if not alpha_box:
        raise ValueError("IMAGE_HAS_NO_VISIBLE_PIXELS")
    source = source.crop(alpha_box)
    scale = min((width - 4) / source.width, (height - 4) / source.height)
    target_size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    sampled = source.resize(target_size, Image.Resampling.NEAREST)
    placed = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    placed.alpha_composite(sampled, ((width - target_size[0]) // 2, (height - target_size[1]) // 2))
    pixels = placed.load()
    assignments: dict[tuple[int, int], tuple[MardColor, float]] = {}
    mapped: dict[tuple[int, int, int], tuple[MardColor, float]] = {}
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 18:
                continue
            rgb = (red, green, blue)
            if rgb not in mapped:
                mapped[rgb] = _nearest_mard(rgb)
            assignments[(x, y)] = mapped[rgb]
    if not assignments:
        raise ValueError("PATTERN_MODEL_EMPTY_GRID")
    assignments, palette_reduced_cells, source_color_count = _enforce_mode_palette(assignments, color_mode)
    assignments, noise_removed_cells = _remove_incidental_single_bead_noise(assignments)
    counts: Counter[str] = Counter(color.code for color, _ in assignments.values())
    distances: Counter[str] = Counter()
    for color, distance in assignments.values():
        distances[color.code] += distance
    cells = [{
        "x": x, "y": y, "occupied": True, "brand": "MARD",
        "colorCode": color.code, "colorValue": color.hex,
        "boardId": _board_id(x, y, board_columns), "matchDistanceRgb": distance,
    } for (x, y), (color, distance) in assignments.items()]
    palette = [{
        "brand": "MARD", "code": color.code, "value": color.hex,
        "count": counts[color.code],
        "averageMatchDistanceRgb": round(distances[color.code] / counts[color.code], 3),
    } for color in MARD_STANDARD_PALETTE if counts[color.code]]
    isolated = sum(
        sum((x + dx, y + dy) in assignments for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))) == 0
        for x, y in assignments
    )
    average_delta = sum(distances.values()) / len(assignments)
    return {
        "schemaVersion": "1.0", "engineVersion": DIRECT_MODEL_ENGINE_VERSION, "revision": 0,
        "width": width, "height": height, "beadDiameterMm": 5,
        "boardLayout": {"type": layout, "boardWidth": BOARD_SIZE, "boardHeight": BOARD_SIZE,
            "columns": board_columns, "rows": board_rows,
            "seamsX": [BOARD_SIZE * item for item in range(1, board_columns)],
            "seamsY": [BOARD_SIZE * item for item in range(1, board_rows)]},
        "beadBrand": "MARD", "paletteVersion": "official-v1", "colorMode": color_mode,
        "cells": cells, "palette": palette,
        "statistics": {
            "totalBeads": len(cells), "colorCount": len(palette),
            "physicalWidthMm": width * 5, "physicalHeightMm": height * 5,
            "averageColorDeltaE": round(average_delta, 3), "referenceColorUsed": False,
            "referenceColorPolicy": "model-authored-image-to-official-mard", "engineVersion": DIRECT_MODEL_ENGINE_VERSION,
            "backgroundRemoval": background_removal,
            "regionPolicy": "model-authored-image", "regionCounts": {},
            "qualityScore": 84, "qualityLevel": "good", "qualityPolicy": "model-image-makeability-v2",
            "isolatedCellCount": isolated, "recommendedMinimumBoard": f"{width}×{height}",
            "qualityWarnings": [
                *([] if isolated < 8 else ["存在较多孤立针位，建议在编辑页检查。"]),
                *([] if palette_reduced_cells == 0 else [f"已按{color_mode}方案合并 {palette_reduced_cells} 个近似阴影/高光色块。"]),
            ],
            "detailBudget": {
                "mode": color_mode,
                "maximumColors": COLOR_LIMITS[color_mode],
                "modelMappedColorsBeforeMerge": source_color_count,
                "paletteReducedCells": palette_reduced_cells,
                "incidentalNoiseRemovedCells": noise_removed_cells,
            },
            "semanticPlanning": {"used": True, "planReceived": True, "appliedCellChanges": None,
                "plannerVersion": "direct-pattern-image-v1", "model": model,
                "assessment": "图纸由模型直接生成像素成图后转换。", "recommendedAction": "preserve",
                "identityPriorities": [], "generationMode": "direct-model-image"},
        },
    }
