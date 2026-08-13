#!/usr/bin/env python3
"""Validate the Stage 0 OpenAPI document and Pattern JSON contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_pattern() -> None:
    schema = json.loads((ROOT / "schemas/pattern-v1.schema.json").read_text())
    example = json.loads((ROOT / "examples/pattern-v1.example.json").read_text())
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(example),
        key=lambda item: list(item.path),
    )
    if errors:
        rendered = "\n".join(
            f"  - {'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
            for error in errors
        )
        fail(f"pattern example does not match schema:\n{rendered}")

    width, height = example["width"], example["height"]
    palette_indexes = {item["index"] for item in example["palette"]}
    cells = example["cells"]
    coordinates = {(cell["x"], cell["y"]) for cell in cells}
    if len(coordinates) != len(cells):
        fail("pattern cells contain duplicate coordinates")
    if any(cell["x"] >= width or cell["y"] >= height for cell in cells):
        fail("pattern cells contain an out-of-bounds coordinate")
    if any(cell["paletteIndex"] not in palette_indexes for cell in cells):
        fail("pattern cells reference an unknown palette index")

    occupied = len(cells)
    if example["statistics"]["occupiedCells"] != occupied:
        fail("occupiedCells is not equal to the number of sparse cells")
    if example["statistics"]["emptyCells"] != width * height - occupied:
        fail("emptyCells is inconsistent with width, height and occupiedCells")
    counted = {
        index: sum(cell["paletteIndex"] == index for cell in cells)
        for index in palette_indexes
    }
    declared = {
        item["paletteIndex"]: item["count"]
        for item in example["statistics"]["colorCounts"]
    }
    if counted != declared:
        fail("colorCounts does not match the cell data")


def validate_openapi() -> None:
    document = yaml.safe_load((ROOT / "openapi/openapi.yaml").read_text())
    if document.get("openapi") != "3.1.0":
        fail("OpenAPI version must be 3.1.0")
    if not document.get("paths"):
        fail("OpenAPI paths cannot be empty")
    if not document.get("components", {}).get("schemas"):
        fail("OpenAPI component schemas cannot be empty")

    operation_ids: list[str] = []
    for path, path_item in document["paths"].items():
        if not path.startswith("/api/v1/"):
            fail(f"API path is outside /api/v1: {path}")
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                fail(f"{method.upper()} {path} has no operationId")
            operation_ids.append(operation_id)
            if method.lower() in {"post", "put", "patch", "delete"}:
                parameters = operation.get("parameters", []) + path_item.get("parameters", [])
                has_idempotency = any(
                    parameter.get("$ref") == "#/components/parameters/IdempotencyKey"
                    or parameter.get("name") == "Idempotency-Key"
                    for parameter in parameters
                )
                if not has_idempotency:
                    fail(f"{method.upper()} {path} has no Idempotency-Key parameter")
    if len(operation_ids) != len(set(operation_ids)):
        fail("OpenAPI operationId values must be unique")


def main() -> None:
    validate_pattern()
    validate_openapi()
    print("PASS: pattern schema, example semantics, and OpenAPI contract are valid")


if __name__ == "__main__":
    main()

