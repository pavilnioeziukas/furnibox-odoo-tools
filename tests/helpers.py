from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import BomError, ExplosionRow


class FakeOdooClient:
    def __init__(self, records: dict[str, list[dict[str, Any]]]) -> None:
        self.records = records

    def search_read(self, *, model: str, domain: list, fields: list, **kwargs):
        rows = list(self.records.get(model, []))
        for field_name, operator, expected in domain:
            if operator == "=":
                rows = [row for row in rows if row.get(field_name) == expected]
            elif operator == "!=":
                rows = [row for row in rows if row.get(field_name) != expected]
        limit = kwargs.get("limit")
        return rows[:limit] if limit else rows

    def read(self, *, model: str, record_ids: list[int], fields: list):
        wanted = set(record_ids)
        return [
            row for row in self.records.get(model, [])
            if int(row["id"]) in wanted
        ]


@dataclass
class FakeExplosionResult:
    leaf_rows: list[ExplosionRow] = field(default_factory=list)
    errors: list[BomError] = field(default_factory=list)
    fallback_count: int = 0
    fallbacks: list[Any] = field(default_factory=list)
    dataset_id: str = "TEST_DATASET"
    batch_reference: str = "TEST_BATCH"

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class FakeExecutionEngine:
    def __init__(self, result: FakeExplosionResult) -> None:
        self.result = result

    def explode_sales_order(self, so_number: str, *, only_grouped_lines: bool = True):
        return self.result


def explosion_row(
    sku: str,
    qty: float,
    *,
    group_name: str = "A-1",
    root_sku: str = "EU-C-CAB01-ABC123-A",
) -> ExplosionRow:
    return ExplosionRow(
        so_number="SO001",
        sale_line_id=1,
        group_name=group_name,
        root_product_id=10,
        root_sku=root_sku,
        root_so_qty=1,
        level=1,
        parent_sku=root_sku,
        component_product_id=20,
        component_sku=sku,
        component_name=sku,
        bom_id=100,
        bom_reference="TEST",
        bom_type="normal",
        bom_sequence=0,
        bom_base_qty=1,
        bom_line_id=1000,
        bom_line_qty=qty,
        required_qty=qty,
        child_bom_id=None,
        is_leaf=True,
        path=f"{root_sku} > {sku}",
    )
