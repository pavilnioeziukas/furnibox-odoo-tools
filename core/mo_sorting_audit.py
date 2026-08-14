from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


def normalize_group(value: Any) -> str:
    return str(value or "").strip().upper()


@dataclass(frozen=True)
class GroupedDocument:
    document_id: int
    name: str
    group_name: str


@dataclass(frozen=True)
class MoSortingAuditRow:
    group_name: str
    status: str
    mo_names: tuple[str, ...] = ()
    int_names: tuple[str, ...] = ()


@dataclass
class MoSortingAuditResult:
    rows: list[MoSortingAuditRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: bool = True

    @property
    def mo_count(self) -> int:
        return sum(len(row.mo_names) for row in self.rows)

    @property
    def int_count(self) -> int:
        return sum(len(row.int_names) for row in self.rows)

    @property
    def matched_count(self) -> int:
        return sum(row.status == "MATCH" for row in self.rows)

    @property
    def missing_int_count(self) -> int:
        return sum(row.status == "MISSING_INT" for row in self.rows)

    @property
    def missing_mo_count(self) -> int:
        return sum(row.status == "MISSING_MO" for row in self.rows)

    @property
    def duplicate_group_count(self) -> int:
        return sum(row.status == "DUPLICATE_GROUP" for row in self.rows)

    @property
    def status(self) -> str:
        if not self.checked:
            return "NOT_CHECKED"
        return "PASS" if all(row.status == "MATCH" for row in self.rows) else "FAIL"


def compare_mo_and_sorting_int(
    manufacturing_orders: list[GroupedDocument],
    sorting_ints: list[GroupedDocument],
) -> MoSortingAuditResult:
    """Compare records by Primary SO (query scope) and Sale Group Name."""
    mos: dict[str, list[str]] = defaultdict(list)
    ints: dict[str, list[str]] = defaultdict(list)

    for document in manufacturing_orders:
        mos[normalize_group(document.group_name)].append(document.name)
    for document in sorting_ints:
        ints[normalize_group(document.group_name)].append(document.name)

    rows: list[MoSortingAuditRow] = []
    for group_name in sorted(set(mos) | set(ints)):
        mo_names = tuple(sorted(mos.get(group_name, [])))
        int_names = tuple(sorted(ints.get(group_name, [])))
        if not group_name:
            status = "MISSING_GROUP"
        elif len(mo_names) > 1 or len(int_names) > 1:
            status = "DUPLICATE_GROUP"
        elif not int_names:
            status = "MISSING_INT"
        elif not mo_names:
            status = "MISSING_MO"
        else:
            status = "MATCH"
        rows.append(MoSortingAuditRow(group_name, status, mo_names, int_names))

    return MoSortingAuditResult(rows=rows)


def find_sale_group_field(fields: dict[str, dict[str, Any]]) -> str | None:
    """Resolve the custom field from real Odoo metadata, without guessing x_* names."""
    preferred = ("sale_group_name", "group_name")
    for field_name in preferred:
        if field_name in fields:
            return field_name

    exact_labels = {"sale group name", "sale group"}
    matches = [
        field_name
        for field_name, metadata in fields.items()
        if str(metadata.get("string") or "").strip().casefold() in exact_labels
        and metadata.get("type") in {"char", "selection"}
    ]
    return matches[0] if len(matches) == 1 else None


def duplicate_sides(rows: list[MoSortingAuditRow]) -> tuple[int, int]:
    """Return duplicate MO and INT group counts independently for the summary."""
    mo_duplicates = sum(len(row.mo_names) > 1 for row in rows)
    int_duplicates = sum(len(row.int_names) > 1 for row in rows)
    return mo_duplicates, int_duplicates
