from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExplosionRow:
    so_number: str
    sale_line_id: int
    group_name: str

    root_product_id: int
    root_sku: str
    root_so_qty: float

    level: int

    parent_sku: str

    component_product_id: int
    component_sku: str
    component_name: str

    bom_id: int
    bom_reference: str
    bom_type: str
    bom_sequence: int
    bom_base_qty: float

    bom_line_id: int
    bom_line_qty: float
    required_qty: float

    child_bom_id: int | None
    is_leaf: bool

    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BomError:
    so_number: str
    sale_line_id: int | None
    group_name: str
    root_sku: str

    status: str = "BOM ERROR"
    error: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BomExplosionResult:
    so_number: str

    rows: list[ExplosionRow] = field(
        default_factory=list
    )

    errors: list[BomError] = field(
        default_factory=list
    )

    @property
    def leaf_rows(self) -> list[ExplosionRow]:
        return [
            row
            for row in self.rows
            if row.is_leaf
        ]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def status(self) -> str:
        if self.errors:
            return "BOM ERROR"

        return "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "so_number": self.so_number,
            "status": self.status,
            "explosion_rows": [
                row.to_dict()
                for row in self.rows
            ],
            "errors": [
                error.to_dict()
                for error in self.errors
            ],
        }