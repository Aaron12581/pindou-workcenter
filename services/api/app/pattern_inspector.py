from __future__ import annotations

from math import sqrt


def _rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))


def _distance(left: str, right: str) -> float:
    return sqrt(sum((a - b) ** 2 for a, b in zip(_rgb(left), _rgb(right))))


def inspect_pattern(pattern: dict) -> dict:
    cells = {(cell["x"], cell["y"]): cell for cell in pattern["cells"]}
    width, height = pattern["width"], pattern["height"]
    seams_x = set(pattern["boardLayout"].get("seamsX", []))
    seams_y = set(pattern["boardLayout"].get("seamsY", []))
    issues: list[dict] = []

    for (x, y), cell in cells.items():
        neighbors = [
            cells.get((x - 1, y)), cells.get((x + 1, y)),
            cells.get((x, y - 1)), cells.get((x, y + 1)),
        ]
        occupied = [item for item in neighbors if item]
        same = [item for item in occupied if item["colorCode"] == cell["colorCode"]]
        if not occupied or (not same and len(occupied) <= 2):
            issues.append({
                "id": f"isolated-{x}-{y}", "type": "isolated_bead", "severity": "warning",
                "title": "孤立豆需要确认", "message": "该豆与相邻豆缺少同色连接，可保留为高光或并入周围主色。",
                "coordinates": [{"x": x, "y": y}], "colorCodes": [cell["colorCode"]],
            })
        different = [item for item in occupied if item["colorCode"] != cell["colorCode"]]
        if different:
            closest = min(different, key=lambda item: _distance(cell["colorValue"], item["colorValue"]))
            distance = _distance(cell["colorValue"], closest["colorValue"])
            if distance < 22 and cell["colorCode"] < closest["colorCode"]:
                issues.append({
                    "id": f"similar-{x}-{y}", "type": "similar_colors", "severity": "info",
                    "title": "相邻色过于接近", "message": "两个相邻色号的屏幕色差较小，可检查是否需要合并。",
                    "coordinates": [{"x": x, "y": y}, {"x": closest["x"], "y": closest["y"]}],
                    "colorCodes": [cell["colorCode"], closest["colorCode"]], "metric": round(distance, 1),
                })
        boundary = x in (0, width - 1) or y in (0, height - 1) or (x - 1, y) not in cells or (x + 1, y) not in cells or (x, y - 1) not in cells or (x, y + 1) not in cells
        if boundary and occupied:
            contrast = max((_distance(cell["colorValue"], item["colorValue"]) for item in occupied), default=255)
            if contrast < 38:
                issues.append({
                    "id": f"contrast-{x}-{y}", "type": "low_outline_contrast", "severity": "warning",
                    "title": "轮廓对比偏弱", "message": "边缘与邻近区域色差偏低，远距离识别可能受影响。",
                    "coordinates": [{"x": x, "y": y}], "colorCodes": [cell["colorCode"]], "metric": round(contrast, 1),
                })

    seam_cells = [
        {"x": x, "y": y} for (x, y) in cells
        if x in seams_x or x + 1 in seams_x or y in seams_y or y + 1 in seams_y
    ]
    if seam_cells:
        issues.append({
            "id": "board-seam-content", "type": "board_seam_content", "severity": "info",
            "title": "主体经过分板线", "message": "关键豆点跨越图板拼接处，制作前请确认拼接方向与编号。",
            "coordinates": seam_cells[:80], "colorCodes": [],
        })

    priority = {"warning": 0, "info": 1}
    issues.sort(key=lambda item: (priority[item["severity"]], item["type"], item["id"]))
    counts = {
        "warning": sum(item["severity"] == "warning" for item in issues),
        "info": sum(item["severity"] == "info" for item in issues),
    }
    return {
        "inspected_revision": int(pattern.get("revision", 0)),
        "summary": {"total": len(issues), **counts, "blocking": 0},
        "issues": issues,
    }
