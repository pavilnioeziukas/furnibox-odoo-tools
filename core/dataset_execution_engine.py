from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.bom_engine import BomEngine
from core.dataset_bom_explosion import (
    DatasetBomExplosion,
    DatasetExplosionError,
)
from core.models import BomError, BomExplosionResult
from core.odoo_client import OdooClient
from core.odoo_helpers import many2one_id, many2one_name
from core.validated_dataset_repository import (
    ValidatedDataset,
    ValidatedDatasetRepository,
    ValidatedDatasetRepositoryError,
)


QTY_TOLERANCE = 0.000001


class DatasetExecutionError(RuntimeError):
    """Nepavyko išskleisti SO pagal Product Catalog."""


@dataclass(frozen=True)
class DatasetExecutionRow:
    """Viena Product Catalog išskleista SO BOM eilutė."""

    so_number: str
    sale_line_id: int
    group_name: str

    root_product_id: int
    root_sku: str
    root_so_qty: float

    level: int
    parent_sku: str

    component_product_id: int | None
    component_sku: str
    component_name: str

    bom_id: int | None
    bom_reference: str
    bom_type: str
    bom_sequence: int
    bom_base_qty: float

    bom_line_id: int | None
    bom_line_qty: float
    required_qty: float

    child_bom_id: int | None
    is_leaf: bool
    path: str

    source: str = "PRODUCT_CATALOG"


@dataclass(frozen=True)
class DatasetFallback:
    """SO eilutė, kuri išskleista pagal Odoo BOM."""

    sale_line_id: int
    group_name: str
    root_sku: str
    reason: str
    source: str = "ODOO_FALLBACK"


@dataclass
class DatasetExecutionResult:
    """Su FurnixPoValidator naudojama sąsaja suderinamas rezultatas."""

    so_number: str
    dataset_id: str
    batch_reference: str

    rows: list[Any] = field(default_factory=list)
    errors: list[BomError] = field(default_factory=list)
    fallbacks: list[DatasetFallback] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def leaf_rows(self) -> list[Any]:
        return [
            row
            for row in self.rows
            if row.is_leaf
        ]

    @property
    def fallback_count(self) -> int:
        return len(self.fallbacks)


class DatasetExecutionEngine:
    """SO išskleidžia pagal Product Catalog, su Odoo BOM fallback."""

    def __init__(
        self,
        client: OdooClient,
        bom_engine: BomEngine,
        dataset: ValidatedDataset | None = None,
        *,
        environment: str = "production",
        repository: ValidatedDatasetRepository | None = None,
        max_depth: int = 20,
    ) -> None:
        self.client = client
        self.bom_engine = bom_engine
        self.environment = environment

        self.repository = (
            repository
            or ValidatedDatasetRepository()
        )

        try:
            self.dataset = (
                dataset
                if dataset is not None
                else self.repository.load_latest(
                    environment
                )
            )
        except ValidatedDatasetRepositoryError as exc:
            raise DatasetExecutionError(
                f"Nepavyko užkrauti Product Catalog: {exc}"
            ) from exc

        self.explosion = DatasetBomExplosion(
            self.dataset,
            max_depth=max_depth,
        )

    def explode_sales_order(
        self,
        so_number: str,
        *,
        only_grouped_lines: bool = True,
    ) -> DatasetExecutionResult:
        normalized_so_number = str(
            so_number or ""
        ).strip()

        if not normalized_so_number:
            raise DatasetExecutionError(
                "Nenurodytas SO numeris."
            )

        result = DatasetExecutionResult(
            so_number=normalized_so_number,
            dataset_id=self.dataset.dataset_id,
            batch_reference=self.dataset.batch_reference,
        )

        sale_order = self._load_sale_order(
            normalized_so_number
        )

        sale_line_ids = [
            int(line_id)
            for line_id in sale_order.get(
                "order_line",
                [],
            )
        ]

        if not sale_line_ids:
            result.errors.append(
                BomError(
                    so_number=normalized_so_number,
                    sale_line_id=None,
                    group_name="",
                    root_sku="",
                    error=(
                        f"SO neturi eilučių: "
                        f"{normalized_so_number}"
                    ),
                )
            )
            return result

        sale_lines = self.client.read(
            model="sale.order.line",
            record_ids=sale_line_ids,
            fields=[
                "sequence",
                "group_name",
                "product_id",
                "product_uom_qty",
                "display_type",
            ],
        )

        product_ids = sorted(
            {
                product_id
                for line in sale_lines
                if (
                    product_id := many2one_id(
                        line.get("product_id")
                    )
                )
                is not None
            }
        )

        products_by_id = self._load_products(
            product_ids
        )

        processable_lines = []

        for sale_line in sale_lines:
            if sale_line.get("display_type"):
                continue

            if (
                only_grouped_lines
                and not sale_line.get("group_name")
            ):
                continue

            processable_lines.append(sale_line)

        processable_lines.sort(
            key=lambda line: (
                int(line.get("sequence") or 0),
                int(line.get("id") or 0),
            )
        )

        for sale_line in processable_lines:
            self._process_sale_line(
                so_number=normalized_so_number,
                sale_line=sale_line,
                products_by_id=products_by_id,
                result=result,
            )

        return result

    def _process_sale_line(
        self,
        *,
        so_number: str,
        sale_line: dict[str, Any],
        products_by_id: dict[int, dict[str, Any]],
        result: DatasetExecutionResult,
    ) -> None:
        sale_line_id = int(
            sale_line.get("id") or 0
        )

        group_name = str(
            sale_line.get("group_name") or ""
        ).strip()

        product_id = many2one_id(
            sale_line.get("product_id")
        )

        if product_id is None:
            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_sku="",
                    error="SO eilutė neturi produkto.",
                )
            )
            return

        product = products_by_id.get(
            product_id,
            {},
        )

        root_sku = str(
            product.get("default_code") or ""
        ).strip()

        root_name = str(
            product.get("display_name")
            or many2one_name(
                sale_line.get("product_id")
            )
            or ""
        ).strip()

        try:
            root_qty = float(
                sale_line.get("product_uom_qty")
                or 0
            )
        except (TypeError, ValueError):
            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_sku=root_sku,
                    error=(
                        "Neteisingas SO eilutės kiekis: "
                        f"{sale_line.get('product_uom_qty')!r}"
                    ),
                )
            )
            return

        if root_qty <= QTY_TOLERANCE:
            return

        if not root_sku:
            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_sku="",
                    error=(
                        "SO eilutės produktas neturi "
                        "Internal Reference."
                    ),
                )
            )
            return

        if self.dataset.find_product(root_sku) is None:
            self._apply_odoo_fallback(
                so_number=so_number,
                sale_line=sale_line,
                root_sku=root_sku,
                group_name=group_name,
                result=result,
            )
            return

        try:
            explosion_result = (
                self.explosion.explode_product(
                    sku=root_sku,
                    quantity=root_qty,
                )
            )
        except DatasetExplosionError as exc:
            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_sku=root_sku,
                    error=str(exc),
                    path=root_sku,
                )
            )
            return

        for row in explosion_result.rows:
            result.rows.append(
                DatasetExecutionRow(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_product_id=product_id,
                    root_sku=root_sku,
                    root_so_qty=root_qty,
                    level=row.depth,
                    parent_sku=row.parent_sku,
                    component_product_id=None,
                    component_sku=row.component_sku,
                    component_name=row.component_sku,
                    bom_id=None,
                    bom_reference=(
                        self.dataset.batch_reference
                    ),
                    bom_type=(
                        self.dataset
                        .find_product(
                            row.parent_sku
                        )
                        .bom_type
                        if self.dataset.find_product(
                            row.parent_sku
                        )
                        is not None
                        else ""
                    ),
                    bom_sequence=0,
                    bom_base_qty=1.0,
                    bom_line_id=None,
                    bom_line_qty=row.direct_qty,
                    required_qty=row.required_qty,
                    child_bom_id=None,
                    is_leaf=row.is_leaf,
                    path=" > ".join(row.path),
                    source="PRODUCT_CATALOG",
                )
            )

    def _apply_odoo_fallback(
        self,
        *,
        so_number: str,
        sale_line: dict[str, Any],
        root_sku: str,
        group_name: str,
        result: DatasetExecutionResult,
    ) -> None:
        fallback_result = BomExplosionResult(
            so_number=so_number,
        )

        # Sąmoningai naudojama jau egzistuojanti BomEngine
        # vienos SO eilutės logika. Jos nedubliuojame.
        self.bom_engine._process_sale_line(
            so_number=so_number,
            sale_line=sale_line,
            result=fallback_result,
        )

        if fallback_result.has_errors:
            result.errors.extend(
                fallback_result.errors
            )
            return

        result.rows.extend(
            fallback_result.rows
        )

        result.fallbacks.append(
            DatasetFallback(
                sale_line_id=int(
                    sale_line.get("id") or 0
                ),
                group_name=group_name,
                root_sku=root_sku,
                reason=(
                    "Produktas nerastas Product Catalog; "
                    "naudotas aktyvus Odoo BOM."
                ),
            )
        )

    def _load_sale_order(
        self,
        so_number: str,
    ) -> dict[str, Any]:
        sale_orders = self.client.search_read(
            model="sale.order",
            domain=[
                ["name", "=", so_number],
            ],
            fields=[
                "name",
                "order_line",
            ],
            limit=2,
        )

        if not sale_orders:
            raise DatasetExecutionError(
                f"SO nerastas: {so_number}"
            )

        if len(sale_orders) > 1:
            raise DatasetExecutionError(
                f"Rasti keli SO numeriu: {so_number}"
            )

        return sale_orders[0]

    def _load_products(
        self,
        product_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        if not product_ids:
            return {}

        products = self.client.read(
            model="product.product",
            record_ids=product_ids,
            fields=[
                "default_code",
                "display_name",
                "product_tmpl_id",
                "categ_id",
            ],
        )

        return {
            int(product["id"]): product
            for product in products
        }