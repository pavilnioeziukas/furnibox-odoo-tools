import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


QTY_TOLERANCE = 0.000001

STICKER_ENTRY_PATTERN = re.compile(
    r"""
    ^\s*
    (?P<group>[ACP]-\d+)
    \s*,\s*
    (?:
        (?P<item_code>[A-Z0-9_-]+)
        \s*,\s*
    )?
    (?P<so>[A-Z0-9_-]+)
    \s*
    \[
        QTY
        \s*:\s*
        (?P<qty>\d+(?:[.,]\d+)?)
    \]
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

ROOT_ITEM_CODE_PATTERN = re.compile(
    r"(?:^|-)(?P<code>[A-Z]{3,}[0-9]{3})(?:-A)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StickerAssignment:
    group_name: str
    item_code: str
    so_number: str
    qty: float

    def comparison_key(self) -> tuple[str, str, str, int]:
        return (
            self.group_name.upper(),
            self.item_code.upper(),
            self.so_number.upper(),
            round(self.qty / QTY_TOLERANCE),
        )


@dataclass(frozen=True)
class StickerValidationResult:
    status: str
    error: str
    expected: list[StickerAssignment]
    actual: list[StickerAssignment]

    @property
    def is_valid(self) -> bool:
        return self.status == "PASS"


class StickerInfoParseError(RuntimeError):
    """Component Sticker Info formato klaida."""


def extract_item_code(
    root_sku: str | None,
) -> str:
    normalized = str(root_sku or "").strip().upper()

    match = ROOT_ITEM_CODE_PATTERN.search(normalized)

    if not match:
        return ""

    return match.group("code").upper()


def parse_sticker_info(
    sticker_info: str | None,
) -> list[StickerAssignment]:
    value = str(sticker_info or "").strip()

    if not value:
        raise StickerInfoParseError(
            "Component Sticker Info yra tuščias."
        )

    raw_entries = [
        entry.strip()
        for entry in value.split(";")
        if entry.strip()
    ]

    if not raw_entries:
        raise StickerInfoParseError(
            "Component Sticker Info neturi priskyrimų."
        )

    assignments: list[StickerAssignment] = []

    for raw_entry in raw_entries:
        match = STICKER_ENTRY_PATTERN.fullmatch(
            raw_entry
        )

        if not match:
            raise StickerInfoParseError(
                "Neatpažintas Sticker Info įrašas: "
                f"{raw_entry!r}"
            )

        qty_text = match.group("qty").replace(
            ",",
            ".",
        )

        assignments.append(
            StickerAssignment(
                group_name=match.group(
                    "group"
                ).upper(),
                item_code=str(
                    match.group("item_code") or ""
                ).upper(),
                so_number=match.group("so").upper(),
                qty=float(qty_text),
            )
        )

    return assignments


def build_expected_assignments(
    *,
    so_number: str,
    origins: list[dict[str, Any]],
) -> list[StickerAssignment]:
    expected: list[StickerAssignment] = []

    for origin in origins:
        group_name = str(
            origin.get("group_name") or ""
        ).strip().upper()

        root_sku = str(
            origin.get("root_sku") or ""
        ).strip().upper()

        required_qty = float(
            origin.get("required_qty") or 0
        )

        if not group_name:
            raise RuntimeError(
                "BOM kilmė neturi Group Name."
            )

        item_code = ""

        if group_name.startswith("A-"):
            item_code = extract_item_code(
                root_sku
            )

            if not item_code:
                raise RuntimeError(
                    "Nepavyko nustatyti baldo kodo iš "
                    f"root SKU {root_sku!r}."
                )

        expected.append(
            StickerAssignment(
                group_name=group_name,
                item_code=item_code,
                so_number=so_number.upper(),
                qty=required_qty,
            )
        )

    return expected


def validate_sticker_info(
    *,
    so_number: str,
    po_qty: float,
    origins: list[dict[str, Any]],
    sticker_values: list[str],
) -> StickerValidationResult:
    try:
        expected = build_expected_assignments(
            so_number=so_number,
            origins=origins,
        )

        actual: list[StickerAssignment] = []

        for sticker_value in sticker_values:
            actual.extend(
                parse_sticker_info(sticker_value)
            )

    except (RuntimeError, StickerInfoParseError) as exc:
        return StickerValidationResult(
            status="STICKER INFO ERROR",
            error=str(exc),
            expected=[],
            actual=[],
        )

    actual_qty_sum = sum(
        assignment.qty
        for assignment in actual
    )

    if abs(actual_qty_sum - po_qty) > QTY_TOLERANCE:
        return StickerValidationResult(
            status="STICKER INFO ERROR",
            error=(
                "Sticker Info QTY suma nesutampa su "
                f"PO kiekiu: Sticker={actual_qty_sum}, "
                f"PO={po_qty}."
            ),
            expected=expected,
            actual=actual,
        )

    expected_counter = Counter(
        assignment.comparison_key()
        for assignment in expected
    )

    actual_counter = Counter(
        assignment.comparison_key()
        for assignment in actual
    )

    if expected_counter != actual_counter:
        missing = list(
            (expected_counter - actual_counter).elements()
        )

        extra = list(
            (actual_counter - expected_counter).elements()
        )

        messages: list[str] = []

        if missing:
            messages.append(
                f"trūksta priskyrimų: {missing}"
            )

        if extra:
            messages.append(
                f"papildomi priskyrimai: {extra}"
            )

        return StickerValidationResult(
            status="STICKER INFO ERROR",
            error="; ".join(messages),
            expected=expected,
            actual=actual,
        )

    return StickerValidationResult(
        status="PASS",
        error="",
        expected=expected,
        actual=actual,
    )