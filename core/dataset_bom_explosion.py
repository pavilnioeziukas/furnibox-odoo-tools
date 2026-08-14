from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.validated_dataset_repository import (
    DatasetProduct,
    ValidatedDataset,
)


QTY_TOLERANCE = 0.000001


class DatasetExplosionError(RuntimeError):
    """Nepavyko išskleisti produkto BOM iš Validated Dataset."""


@dataclass(frozen=True)
class DatasetExplosionRow:
    root_sku: str
    parent_sku: str
    component_sku: str

    direct_qty: float
    required_qty: float

    depth: int
    is_leaf: bool

    path: tuple[str, ...] = field(
        default_factory=tuple
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_sku": self.root_sku,
            "parent_sku": self.parent_sku,
            "component_sku": self.component_sku,
            "direct_qty": self.direct_qty,
            "required_qty": self.required_qty,
            "depth": self.depth,
            "is_leaf": self.is_leaf,
            "path": list(self.path),
        }


@dataclass
class DatasetExplosionResult:
    root_sku: str
    root_quantity: float

    rows: list[DatasetExplosionRow] = field(
        default_factory=list
    )

    @property
    def leaf_rows(self) -> list[DatasetExplosionRow]:
        return [
            row
            for row in self.rows
            if row.is_leaf
        ]

    @property
    def leaf_quantities(self) -> dict[str, float]:
        quantities: dict[str, float] = defaultdict(float)

        for row in self.leaf_rows:
            quantities[row.component_sku] += (
                row.required_qty
            )

        return dict(
            sorted(
                quantities.items()
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_sku": self.root_sku,
            "root_quantity": self.root_quantity,
            "row_count": len(self.rows),
            "leaf_row_count": len(self.leaf_rows),
            "leaf_quantities": self.leaf_quantities,
            "rows": [
                row.to_dict()
                for row in self.rows
            ],
        }


class DatasetBomExplosion:
    """Rekursyviai išskleidžia BOM pagal Validated Product Dataset."""

    def __init__(
        self,
        dataset: ValidatedDataset,
        *,
        max_depth: int = 20,
    ) -> None:
        if max_depth < 1:
            raise ValueError(
                "max_depth turi būti bent 1."
            )

        self.dataset = dataset
        self.max_depth = max_depth

        self.products_by_sku = self._index_products(
            dataset.products
        )

    def explode_product(
        self,
        *,
        sku: str,
        quantity: float = 1.0,
    ) -> DatasetExplosionResult:
        normalized_sku = self._normalize_sku(
            sku
        )

        root_quantity = self._normalize_quantity(
            quantity,
            context=f"produkto {normalized_sku}",
        )

        root_product = self.products_by_sku.get(
            normalized_sku
        )

        if root_product is None:
            raise DatasetExplosionError(
                "Produktas nerastas Validated Dataset: "
                f"{normalized_sku}"
            )

        result = DatasetExplosionResult(
            root_sku=normalized_sku,
            root_quantity=root_quantity,
        )

        self._explode(
            result=result,
            root_sku=normalized_sku,
            product=root_product,
            multiplier=root_quantity,
            depth=1,
            path=(normalized_sku,),
        )

        return result

    def _explode(
        self,
        *,
        result: DatasetExplosionResult,
        root_sku: str,
        product: DatasetProduct,
        multiplier: float,
        depth: int,
        path: tuple[str, ...],
    ) -> None:
        if depth > self.max_depth:
            raise DatasetExplosionError(
                "Viršytas maksimalus BOM gylis "
                f"{self.max_depth}: {' > '.join(path)}"
            )

        if not product.components:
            raise DatasetExplosionError(
                f"Dataset produktas {product.sku} "
                "neturi BOM komponentų."
            )

        for component_data in product.components:
            component_sku = self._normalize_sku(
                component_data.get("sku")
            )

            direct_qty = self._normalize_quantity(
                component_data.get("quantity"),
                context=(
                    f"komponento {component_sku} "
                    f"BOM {product.sku}"
                ),
            )

            required_qty = (
                multiplier * direct_qty
            )

            component_product = (
                self.products_by_sku.get(
                    component_sku
                )
            )

            is_leaf = component_product is None

            component_path = (
                *path,
                component_sku,
            )

            if component_sku in path:
                raise DatasetExplosionError(
                    "Aptiktas ciklinis BOM: "
                    + " > ".join(component_path)
                )

            result.rows.append(
                DatasetExplosionRow(
                    root_sku=root_sku,
                    parent_sku=product.sku,
                    component_sku=component_sku,
                    direct_qty=direct_qty,
                    required_qty=required_qty,
                    depth=depth,
                    is_leaf=is_leaf,
                    path=component_path,
                )
            )

            if not is_leaf:
                self._explode(
                    result=result,
                    root_sku=root_sku,
                    product=component_product,
                    multiplier=required_qty,
                    depth=depth + 1,
                    path=component_path,
                )

    @classmethod
    def _index_products(
        cls,
        products: list[DatasetProduct],
    ) -> dict[str, DatasetProduct]:
        indexed: dict[str, DatasetProduct] = {}

        for product in products:
            sku = cls._normalize_sku(
                product.sku
            )

            if sku in indexed:
                raise DatasetExplosionError(
                    "Dataset kartojasi produkto SKU: "
                    f"{sku}"
                )

            indexed[sku] = product

        return indexed

    @staticmethod
    def _normalize_sku(
        value: Any,
    ) -> str:
        sku = str(
            value or ""
        ).strip().upper()

        if not sku:
            raise DatasetExplosionError(
                "BOM įrašas neturi SKU."
            )

        return sku

    @staticmethod
    def _normalize_quantity(
        value: Any,
        *,
        context: str,
    ) -> float:
        try:
            quantity = float(value)
        except (TypeError, ValueError) as exc:
            raise DatasetExplosionError(
                f"Neteisingas kiekis {context}: "
                f"{value!r}"
            ) from exc

        if quantity <= QTY_TOLERANCE:
            raise DatasetExplosionError(
                f"Kiekis turi būti teigiamas "
                f"{context}: {quantity}"
            )

        return quantity