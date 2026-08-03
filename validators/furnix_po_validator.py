from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from core.furnix_part_classifier import FurnixPartClassifier
from core.odoo_helpers import many2one_id, many2one_name
from core.sticker_info_validator import validate_sticker_info

if TYPE_CHECKING:
    from core.odoo_client import OdooClient




class SalesOrderExplosionProvider(Protocol):
    def explode_sales_order(
        self,
        so_number: str,
        *,
        only_grouped_lines: bool = True,
    ) -> Any:
        ...


QTY_TOLERANCE = 0.000001
FURNIX_VENDOR_NAME = "FURNIX, UAB"


def normalize_sku_key(value: Any) -> str:
    """Canonical key for SKU comparison while preserving display values."""
    return str(value or "").strip().upper()


@dataclass
class FurnixPoComparisonRow:
    sku: str
    product_name: str
    required_qty: float
    po_qty: float
    difference: float
    status: str
    origins: list[dict[str, Any]] = field(default_factory=list)
    component_sticker_info: list[str] = field(default_factory=list)
    sticker_status: str = ""
    sticker_error: str = ""


@dataclass
class FurnixPoValidationResult:
    so_number: str
    po_number: str = ""
    po_state: str = ""
    vendor_name: str = ""
    furnix_po_count: int = 0
    status: str = ""
    error: str = ""

    dataset_id: str = ""
    batch_reference: str = ""
    fallback_count: int = 0
    fallbacks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    rows: list[FurnixPoComparisonRow] = field(default_factory=list)

    @property
    def missing_count(self) -> int:
        return sum(
            row.status == "MISSING"
            for row in self.rows
        )

    @property
    def extra_count(self) -> int:
        return sum(
            row.status == "EXTRA"
            for row in self.rows
        )

    @property
    def qty_mismatch_count(self) -> int:
        return sum(
            row.status == "QTY MISMATCH"
            for row in self.rows
        )

    @property
    def pass_count(self) -> int:
        return sum(
            row.status == "PASS"
            for row in self.rows
        )

    @property
    def sticker_error_count(self) -> int:
        return sum(
            row.sticker_status == "STICKER INFO ERROR"
            for row in self.rows
        )


class FurnixPoValidator:
    def __init__(
        self,
        client: "OdooClient",
        execution_engine: SalesOrderExplosionProvider,
    ) -> None:
        self.client = client
        self.execution_engine = execution_engine

    def validate(
        self,
        so_number: str,
    ) -> FurnixPoValidationResult:
        result = FurnixPoValidationResult(
            so_number=so_number,
        )

        sale_orders = self.client.search_read(
            model="sale.order",
            domain=[
                ["name", "=", so_number],
            ],
            fields=[
                "name",
            ],
            limit=2,
        )

        if not sale_orders:
            result.status = "BOM ERROR"
            result.error = f"SO nerastas: {so_number}"
            return result

        if len(sale_orders) > 1:
            result.status = "BOM ERROR"
            result.error = (
                f"Rasti keli SO numeriu {so_number}"
            )
            return result

        sale_order_id = int(
            sale_orders[0]["id"]
        )

        purchase_orders = self.client.search_read(
            model="purchase.order",
            domain=[
                ["sale_primary_id", "=", sale_order_id],
                ["state", "!=", "cancel"],
            ],
            fields=[
                "name",
                "state",
                "partner_id",
                "sale_primary_id",
                "order_line",
            ],
            order="id asc",
        )

        furnix_purchase_orders = [
            po
            for po in purchase_orders
            if many2one_name(
                po.get("partner_id")
            ).strip().upper()
            == FURNIX_VENDOR_NAME
        ]

        result.furnix_po_count = len(
            furnix_purchase_orders
        )

        if not furnix_purchase_orders:
            result.status = "NO PO"
            result.error = (
                "Aktyvus Furnix PO pagal "
                "Primary Sale Order nerastas."
            )
            return result

        if len(furnix_purchase_orders) > 1:
            result.status = "MULTIPLE PO"
            result.error = (
                "Vienam SO rasti keli aktyvÅ«s Furnix PO: "
                + ", ".join(
                    str(
                        po.get("name")
                        or po.get("id")
                    )
                    for po in furnix_purchase_orders
                )
            )
            return result

        purchase_order = furnix_purchase_orders[0]

        result.po_number = str(
            purchase_order.get("name") or ""
        )
        result.po_state = str(
            purchase_order.get("state") or ""
        )
        result.vendor_name = many2one_name(
            purchase_order.get("partner_id")
        )

        bom_result = self.execution_engine.explode_sales_order(
            so_number,
            only_grouped_lines=True,
        )

        result.dataset_id = str(
            getattr(bom_result, "dataset_id", "") or ""
        )
        result.batch_reference = str(
            getattr(bom_result, "batch_reference", "") or ""
        )

        raw_fallbacks = list(
            getattr(bom_result, "fallbacks", []) or []
        )
        result.fallback_count = len(raw_fallbacks)

        for fallback in raw_fallbacks:
            result.fallbacks.append(
                {
                    "sale_line_id": getattr(
                        fallback,
                        "sale_line_id",
                        None,
                    ),
                    "group_name": str(
                        getattr(
                            fallback,
                            "group_name",
                            "",
                        )
                        or ""
                    ),
                    "root_sku": str(
                        getattr(
                            fallback,
                            "root_sku",
                            "",
                        )
                        or ""
                    ),
                    "reason": str(
                        getattr(
                            fallback,
                            "reason",
                            "",
                        )
                        or ""
                    ),
                    "source": str(
                        getattr(
                            fallback,
                            "source",
                            "ODOO_FALLBACK",
                        )
                        or "ODOO_FALLBACK"
                    ),
                }
            )

        if result.fallback_count:
            result.warnings.append(
                "Naudotas Odoo BOM fallback "
                f"{result.fallback_count} SO eilutėms."
            )

        if bom_result.has_errors:
            result.status = "BOM ERROR"
            result.error = "; ".join(
                error.error
                for error in bom_result.errors
            )
            return result

        furnix_leaf_rows = [
            row
            for row in bom_result.leaf_rows
            if FurnixPartClassifier.is_furnix_detail(
                row.component_sku
            )
        ]

        required_by_sku: dict[str, float] = defaultdict(float)
        origins_by_sku: dict[
            str,
            list[dict[str, Any]],
        ] = defaultdict(list)
        product_name_by_sku: dict[str, str] = {}
        display_sku_by_key: dict[str, str] = {}

        for row in furnix_leaf_rows:
            display_sku = str(
                row.component_sku or ""
            ).strip()
            sku = normalize_sku_key(display_sku)

            if not sku:
                continue

            required_by_sku[sku] += (
                row.required_qty
            )

            display_sku_by_key.setdefault(
                sku,
                display_sku,
            )

            product_name_by_sku[sku] = (
                row.component_name
            )

            origins_by_sku[sku].append(
                {
                    "group_name": row.group_name,
                    "root_sku": row.root_sku,
                    "required_qty": row.required_qty,
                    "path": row.path,
                }
            )

        po_line_ids = [
            int(line_id)
            for line_id in purchase_order.get(
                "order_line",
                [],
            )
        ]

        po_lines = self.client.read(
            model="purchase.order.line",
            record_ids=po_line_ids,
            fields=[
                "product_id",
                "product_qty",
                "component_sticker_info",
            ],
        )

        product_ids = sorted(
            {
                product_id
                for line in po_lines
                if (
                    product_id := many2one_id(
                        line.get("product_id")
                    )
                )
                is not None
            }
        )

        products = self.client.read(
            model="product.product",
            record_ids=product_ids,
            fields=[
                "default_code",
                "display_name",
            ],
        )

        products_by_id = {
            int(product["id"]): product
            for product in products
        }

        po_qty_by_sku: dict[str, float] = defaultdict(float)
        sticker_info_by_sku: dict[
            str,
            list[str],
        ] = defaultdict(list)

        for line in po_lines:
            product_id = many2one_id(
                line.get("product_id")
            )

            product = products_by_id.get(
                product_id or -1,
                {},
            )

            display_sku = str(
                product.get("default_code") or ""
            ).strip()
            sku = normalize_sku_key(
                display_sku
            )

            if not sku:
                continue

            display_sku_by_key.setdefault(
                sku,
                display_sku,
            )

            po_qty_by_sku[sku] += float(
                line.get("product_qty") or 0
            )

            sticker_info = str(
                line.get("component_sticker_info")
                or ""
            )

            sticker_info_by_sku[sku].append(
                sticker_info
            )

            if sku not in product_name_by_sku:
                product_name_by_sku[sku] = str(
                    product.get("display_name") or ""
                )

        all_skus = sorted(
            set(required_by_sku)
            | set(po_qty_by_sku)
        )

        for sku in all_skus:
            required_qty = required_by_sku.get(
                sku,
                0.0,
            )
            po_qty = po_qty_by_sku.get(
                sku,
                0.0,
            )
            difference = po_qty - required_qty

            if sku not in required_by_sku:
                row_status = "EXTRA"
            elif sku not in po_qty_by_sku:
                row_status = "MISSING"
            elif abs(difference) > QTY_TOLERANCE:
                row_status = "QTY MISMATCH"
            else:
                row_status = "PASS"

            origins = origins_by_sku.get(
                sku,
                [],
            )

            sticker_values = sticker_info_by_sku.get(
                sku,
                [],
            )

            sticker_status = ""
            sticker_error = ""

            if row_status == "PASS":
                sticker_result = validate_sticker_info(
                    so_number=so_number,
                    po_qty=po_qty,
                    origins=origins,
                    sticker_values=sticker_values,
                )

                sticker_status = (
                    sticker_result.status
                )
                sticker_error = (
                    sticker_result.error
                )

            result.rows.append(
                FurnixPoComparisonRow(
                    sku=(
                        display_sku_by_key.get(
                            sku,
                            sku,
                        )
                    ),
                    product_name=(
                        product_name_by_sku.get(
                            sku,
                            "",
                        )
                    ),
                    required_qty=required_qty,
                    po_qty=po_qty,
                    difference=difference,
                    status=row_status,
                    origins=origins,
                    component_sticker_info=(
                        sticker_values
                    ),
                    sticker_status=sticker_status,
                    sticker_error=sticker_error,
                )
            )

        statuses = {
            row.status
            for row in result.rows
        }

        sticker_statuses = {
            row.sticker_status
            for row in result.rows
            if row.sticker_status
        }

        if "MISSING" in statuses:
            result.status = "MISSING"
        elif "EXTRA" in statuses:
            result.status = "EXTRA"
        elif "QTY MISMATCH" in statuses:
            result.status = "QTY MISMATCH"
        elif "STICKER INFO ERROR" in sticker_statuses:
            result.status = "STICKER INFO ERROR"
        elif result.fallback_count:
            result.status = "PASS WITH FALLBACK"
        else:
            result.status = "PASS"

        return result
