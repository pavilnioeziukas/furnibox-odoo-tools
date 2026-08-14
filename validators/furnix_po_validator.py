from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from core.furnix_part_classifier import FurnixPartClassifier
from core.odoo_helpers import many2one_id, many2one_name
from core.mo_sorting_audit import (
    GroupedDocument,
    MoSortingAuditResult,
    compare_mo_and_sorting_int,
    find_sale_group_field,
)
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
    received_qty: float = 0.0
    input_custom_qty: float = 0.0
    sorted_qty: float = 0.0
    sorting_pending_qty: float = 0.0
    mo_demand_qty: float = 0.0
    mo_reserved_qty: float = 0.0
    cross_so_reserved_qty: float = 0.0
    cross_so_reservations: list[dict[str, Any]] = field(default_factory=list)
    supply_status: str = ""
    supply_error: str = ""
    receipt_names: list[str] = field(default_factory=list)
    sorting_names: list[str] = field(default_factory=list)
    mo_names: list[str] = field(default_factory=list)


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
    mo_sorting_audit: MoSortingAuditResult = field(
        default_factory=MoSortingAuditResult
    )

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

    @property
    def supply_issue_count(self) -> int:
        return sum(
            row.supply_status in {
                "NOT RECEIVED",
                "SORTING NOT DONE",
                "SORTING PARTIAL",
                "MO NOT RESERVED",
                "NO RECEIPT TRACE",
            }
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

    def _fields(self, model: str) -> set[str]:
        """Return fields that actually exist in this Odoo database.

        The deployment has custom fields, so this avoids making a report fail
        just because a standard field was renamed or is unavailable.
        """
        return set(self.client.execute(model, "fields_get").keys())

    def _field_metadata(self, model: str) -> dict[str, dict[str, Any]]:
        return self.client.execute(
            model,
            "fields_get",
            kwargs={"attributes": ["string", "type"]},
        )

    def _audit_mo_sorting_int(
        self,
        *,
        sale_order_id: int,
    ) -> MoSortingAuditResult:
        """Audit MO and Sorting INT links using only discovered Odoo fields."""
        production_fields = self._field_metadata("mrp.production")
        picking_fields = self._field_metadata("stock.picking")
        warnings: list[str] = []

        for model, fields in (
            ("mrp.production", production_fields),
            ("stock.picking", picking_fields),
        ):
            if "sale_primary_id" not in fields:
                warnings.append(
                    f"{model} neturi sale_primary_id; MO ↔ Sorting INT auditas negalimas."
                )

        mo_group_field = find_sale_group_field(production_fields)
        int_group_field = find_sale_group_field(picking_fields)
        if not mo_group_field:
            warnings.append(
                "mrp.production Sale Group Name laukas neaptiktas pagal Odoo metaduomenis."
            )
        if not int_group_field:
            warnings.append(
                "stock.picking Sale Group Name laukas neaptiktas pagal Odoo metaduomenis."
            )

        if warnings:
            return MoSortingAuditResult(
                checked=False,
                warnings=warnings,
            )

        productions = self.client.search_read(
            model="mrp.production",
            domain=[
                ["sale_primary_id", "=", sale_order_id],
                ["state", "!=", "cancel"],
            ],
            fields=["name", mo_group_field],
            order="id asc",
        )
        pickings = self.client.search_read(
            model="stock.picking",
            domain=[
                ["sale_primary_id", "=", sale_order_id],
                ["state", "!=", "cancel"],
            ],
            fields=[
                name
                for name in ["name", "picking_type_id", int_group_field]
                if name in picking_fields
            ],
            order="id asc",
        )

        sorting_pickings = [
            picking
            for picking in pickings
            if str(picking.get("name") or "").strip().upper().startswith("INT")
            or "SORTING" in many2one_name(picking.get("picking_type_id")).upper()
            or "RŪŠIAV" in many2one_name(picking.get("picking_type_id")).upper()
        ]

        result = compare_mo_and_sorting_int(
            [
                GroupedDocument(
                    int(record["id"]),
                    str(record.get("name") or record["id"]),
                    str(record.get(mo_group_field) or ""),
                )
                for record in productions
            ],
            [
                GroupedDocument(
                    int(record["id"]),
                    str(record.get("name") or record["id"]),
                    str(record.get(int_group_field) or ""),
                )
                for record in sorting_pickings
            ],
        )
        result.warnings.append(
            "SKU ir quantity nelyginami: MO galutinio produkto ir Sorting INT judėjimų "
            "produktų/kiekių vienoda semantika Odoo metaduomenyse nepatvirtinta."
        )
        return result

    @staticmethod
    def _qty(record: dict[str, Any], *field_names: str) -> float:
        for field_name in field_names:
            if field_name in record:
                return float(record.get(field_name) or 0.0)
        return 0.0

    def _cross_so_reservations_by_sku(
        self,
        *,
        current_sale_order_id: int,
        skus: set[str],
    ) -> dict[str, list[dict[str, Any]]]:
        if not skus:
            return {}

        product_domain: list[Any] = []

        for sku in sorted(skus):
            if product_domain:
                product_domain.insert(0, "|")
            product_domain.append(
                ["default_code", "=ilike", sku]
            )

        products = self.client.search_read(
            "product.product",
            product_domain,
            fields=["default_code"],
        )

        sku_by_product_id = {
            int(product["id"]): normalize_sku_key(
                product.get("default_code")
            )
            for product in products
            if product.get("default_code")
        }

        if not sku_by_product_id:
            return {}

        moves = self.client.search_read(
            "stock.move",
            [
                ["product_id", "in", sorted(sku_by_product_id)],
                ["raw_material_production_id", "!=", False],
                ["state", "not in", ["done", "cancel"]],
            ],
            fields=[
                "product_id",
                "raw_material_production_id",
                "product_uom_qty",
                "quantity",
                "state",
            ],
        )

        production_ids = sorted({
            production_id
            for move in moves
            if (
                production_id := many2one_id(
                    move.get("raw_material_production_id")
                )
            ) is not None
        })

        productions = (
            self.client.read(
                "mrp.production",
                production_ids,
                ["name", "sale_primary_id", "state"],
            )
            if production_ids
            else []
        )

        production_by_id = {
            int(production["id"]): production
            for production in productions
        }

        result: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for move in moves:
            reserved_qty = self._qty(move, "quantity")
            if reserved_qty <= QTY_TOLERANCE:
                continue

            product_id = many2one_id(move.get("product_id"))
            production_id = many2one_id(
                move.get("raw_material_production_id")
            )

            if product_id is None or production_id is None:
                continue

            sku = sku_by_product_id.get(product_id)
            production = production_by_id.get(production_id)

            if not sku or not production:
                continue

            sale_order_id = many2one_id(
                production.get("sale_primary_id")
            )

            if (
                sale_order_id is None
                or sale_order_id == current_sale_order_id
            ):
                continue

            result[sku].append({
                "sale_order_id": sale_order_id,
                "sale_order": many2one_name(
                    production.get("sale_primary_id")
                ),
                "mo_number": str(
                    production.get("name") or production_id
                ),
                "reserved_qty": reserved_qty,
                "demand_qty": self._qty(
                    move,
                    "product_uom_qty",
                ),
                "state": str(move.get("state") or ""),
            })

        return dict(result)

    def _supply_chain_by_sku(
        self,
        *,
        sale_order_id: int,
        purchase_order: dict[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """Read PO fulfilment and MO reservation state, without changing Odoo.

        Quantities are aggregated per product SKU.  This deliberately reports
        both completed and pending sorting moves: a completed receipt alone is
        not evidence that a component can be reserved by manufacturing.
        """
        warnings: list[str] = []
        supply: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "received_qty": 0.0, "input_custom_qty": 0.0,
                "sorted_qty": 0.0, "sorting_pending_qty": 0.0,
                "mo_demand_qty": 0.0, "mo_reserved_qty": 0.0,
                "receipt_names": [], "sorting_names": [], "mo_names": [],
            }
        )

        picking_fields = self._fields("stock.picking")
        move_fields = self._fields("stock.move")
        production_fields = self._fields("mrp.production")

        po_id = int(purchase_order["id"])
        po_picking_ids = [int(value) for value in purchase_order.get("picking_ids", [])]
        if not po_picking_ids and "purchase_id" in picking_fields:
            po_pickings = self.client.search_read(
                "stock.picking", [["purchase_id", "=", po_id]],
                fields=["name", "state", "picking_type_id", "location_id", "location_dest_id"],
            )
            po_picking_ids = [int(picking["id"]) for picking in po_pickings]

        base_picking_fields = [
            field_name for field_name in ["name", "state", "picking_type_id", "location_id", "location_dest_id", "move_ids_without_package"]
            if field_name in picking_fields
        ]
        receipt_pickings = self.client.read("stock.picking", po_picking_ids, base_picking_fields) if po_picking_ids else []
        receipt_ids = {int(picking["id"]) for picking in receipt_pickings}
        receipt_names = {int(picking["id"]): str(picking.get("name") or picking["id"]) for picking in receipt_pickings}

        # Custom Primary Sale Order is the authoritative link.  If a database
        # lacks it on pickings/moves, report that fact instead of guessing.
        primary_field = "sale_primary_id"
        sorting_pickings: list[dict[str, Any]] = []
        if primary_field in picking_fields:
            sorting_pickings = self.client.search_read(
                "stock.picking", [[primary_field, "=", sale_order_id]],
                fields=base_picking_fields,
                order="id asc",
            )
        else:
            warnings.append("stock.picking neturi lauko sale_primary_id; rūšiavimo perkėlimų pagal SO patikra negalima.")

        all_pickings = {int(picking["id"]): picking for picking in receipt_pickings + sorting_pickings}
        sorting_ids = set(all_pickings) - receipt_ids
        move_query_fields = [
            field_name for field_name in ["product_id", "picking_id", "state", "product_uom_qty", "quantity", "quantity_done", "location_id", "location_dest_id"]
            if field_name in move_fields
        ]
        pickings_to_read = sorted(all_pickings)
        moves = self.client.search_read(
            "stock.move", [["picking_id", "in", pickings_to_read]], fields=move_query_fields,
        ) if pickings_to_read else []

        product_ids = sorted({many2one_id(move.get("product_id")) for move in moves if many2one_id(move.get("product_id")) is not None})
        products = self.client.read("product.product", product_ids, ["default_code"]) if product_ids else []
        sku_by_product = {int(product["id"]): normalize_sku_key(product.get("default_code")) for product in products}

        for move in moves:
            product_id = many2one_id(move.get("product_id"))
            sku = sku_by_product.get(product_id or -1, "")
            picking_id = many2one_id(move.get("picking_id"))
            if not sku or picking_id is None:
                continue
            picking = all_pickings[picking_id]
            move_qty = self._qty(move, "quantity_done", "quantity", "product_uom_qty")
            picking_name = str(picking.get("name") or picking_id)
            if picking_id in receipt_ids:
                supply[sku]["receipt_names"].append(picking_name)
                if move.get("state") == "done":
                    supply[sku]["received_qty"] += move_qty
                    destination = many2one_name(picking.get("location_dest_id")).upper()
                    if "INPUT-CUSTOM" in destination or "INPUT CUSTOM" in destination:
                        supply[sku]["input_custom_qty"] += move_qty
            elif picking_id in sorting_ids:
                supply[sku]["sorting_names"].append(picking_name)
                if move.get("state") == "done":
                    supply[sku]["sorted_qty"] += move_qty
                elif move.get("state") not in {"cancel"}:
                    supply[sku]["sorting_pending_qty"] += self._qty(move, "product_uom_qty", "quantity")

        if primary_field not in production_fields:
            warnings.append("mrp.production neturi lauko sale_primary_id; MO rezervacijos pagal SO patikra negalima.")
            return supply, warnings

        productions = self.client.search_read(
            "mrp.production", [[primary_field, "=", sale_order_id], ["state", "!=", "cancel"]],
            fields=["name", "move_raw_ids", "state"], order="id asc",
        )
        raw_move_ids = [int(move_id) for production in productions for move_id in production.get("move_raw_ids", [])]
        raw_moves = self.client.read("stock.move", raw_move_ids, move_query_fields) if raw_move_ids else []
        raw_product_ids = sorted({many2one_id(move.get("product_id")) for move in raw_moves if many2one_id(move.get("product_id")) is not None})
        missing_product_ids = [product_id for product_id in raw_product_ids if product_id not in sku_by_product]
        if missing_product_ids:
            products = self.client.read("product.product", missing_product_ids, ["default_code"])
            sku_by_product.update({int(product["id"]): normalize_sku_key(product.get("default_code")) for product in products})
        production_by_raw_move = {int(move_id): str(production.get("name") or production["id"]) for production in productions for move_id in production.get("move_raw_ids", [])}
        for move in raw_moves:
            sku = sku_by_product.get(many2one_id(move.get("product_id")) or -1, "")
            if not sku or move.get("state") == "cancel":
                continue
            supply[sku]["mo_demand_qty"] += self._qty(move, "product_uom_qty")
            supply[sku]["mo_reserved_qty"] += self._qty(move, "quantity", "quantity_done")
            supply[sku]["mo_names"].append(production_by_raw_move.get(int(move["id"]), "?"))

        return supply, warnings

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

        result.mo_sorting_audit = self._audit_mo_sorting_int(
            sale_order_id=sale_order_id,
        )
        result.warnings.extend(result.mo_sorting_audit.warnings)

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
                "picking_ids",
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

        supply_by_sku, supply_warnings = self._supply_chain_by_sku(
            sale_order_id=sale_order_id,
            purchase_order=purchase_order,
        )
        result.warnings.extend(supply_warnings)

        cross_so_candidate_skus = set()

        for row in result.rows:
            sku = normalize_sku_key(row.sku)
            supply = supply_by_sku.get(sku, {})

            received_qty = float(
                supply.get("received_qty", 0.0)
            )
            sorted_qty = float(
                supply.get("sorted_qty", 0.0)
            )
            sorting_pending_qty = float(
                supply.get("sorting_pending_qty", 0.0)
            )
            input_custom_qty = float(
                supply.get("input_custom_qty", 0.0)
            )
            mo_demand_qty = float(
                supply.get("mo_demand_qty", 0.0)
            )
            mo_reserved_qty = float(
                supply.get("mo_reserved_qty", 0.0)
            )

            fully_received = (
                received_qty + QTY_TOLERANCE
                >= float(row.po_qty or 0.0)
            )

            sorting_complete = (
                sorting_pending_qty <= QTY_TOLERANCE
                and (
                    sorted_qty + QTY_TOLERANCE >= received_qty
                    or input_custom_qty <= QTY_TOLERANCE
                )
            )

            mo_missing = (
                mo_demand_qty > QTY_TOLERANCE
                and mo_reserved_qty + QTY_TOLERANCE
                < mo_demand_qty
            )

            if fully_received and sorting_complete and mo_missing:
                cross_so_candidate_skus.add(sku)

        cross_so_by_sku = self._cross_so_reservations_by_sku(
            current_sale_order_id=sale_order_id,
            skus=cross_so_candidate_skus,
        )



        for row in result.rows:
            supply = supply_by_sku.get(normalize_sku_key(row.sku), {})
            row.received_qty = float(supply.get("received_qty", 0.0))
            row.input_custom_qty = float(supply.get("input_custom_qty", 0.0))
            row.sorted_qty = float(supply.get("sorted_qty", 0.0))
            row.sorting_pending_qty = float(supply.get("sorting_pending_qty", 0.0))
            row.mo_demand_qty = float(supply.get("mo_demand_qty", 0.0))
            row.mo_reserved_qty = float(supply.get("mo_reserved_qty", 0.0))
            cross_so_reservations = sorted(
                cross_so_by_sku.get(
                    normalize_sku_key(row.sku),
                    [],
                ),
                key=lambda item: (
                    str(item.get("sale_order") or ""),
                    str(item.get("mo_number") or ""),
                ),
            )

            missing_qty = max(
                row.mo_demand_qty - row.mo_reserved_qty,
                0.0,
            )

            relevant_reservations: list[dict[str, Any]] = []
            relevant_reserved_qty = 0.0

            for item in cross_so_reservations:
                if relevant_reserved_qty + QTY_TOLERANCE >= missing_qty:
                    break

                relevant_reservations.append(item)
                relevant_reserved_qty += float(
                    item.get("reserved_qty") or 0.0
                )

            row.cross_so_reservations = relevant_reservations
            row.cross_so_reserved_qty = min(
                relevant_reserved_qty,
                missing_qty,
            )

            row.receipt_names = sorted(set(supply.get("receipt_names", [])))
            row.sorting_names = sorted(set(supply.get("sorting_names", [])))
            row.mo_names = sorted(set(supply.get("mo_names", [])))

            # PO comparison errors remain the primary status.  Supply status
            # explains why a correctly ordered component is still unavailable.
            if row.status != "PASS":
                row.supply_status = "NOT CHECKED"
            elif row.received_qty + QTY_TOLERANCE < row.po_qty:
                row.supply_status = "NOT RECEIVED"
                row.supply_error = "Furnix PO dar nepriimtas pilnai."
            elif row.input_custom_qty > QTY_TOLERANCE and row.sorted_qty + QTY_TOLERANCE < row.received_qty:
                row.supply_status = "SORTING NOT DONE"
                row.supply_error = "Detalė priimta į WH/Input-Custom, bet rūšiavimas į WH/Stock nepatvirtintas."
            elif row.sorting_pending_qty > QTY_TOLERANCE:
                row.supply_status = "SORTING PARTIAL"
                row.supply_error = "Dalis rūšiavimo perkėlimo dar nepatvirtinta."
            elif row.mo_demand_qty > QTY_TOLERANCE and row.mo_reserved_qty + QTY_TOLERANCE < row.mo_demand_qty:
                row.supply_status = "MO NOT RESERVED"
                row.supply_error = "Detalė pasiekė sandėlį, bet MO komponentas nėra pilnai rezervuotas."
            elif row.received_qty > QTY_TOLERANCE:
                row.supply_status = "AVAILABLE / RESERVED"
            else:
                row.supply_status = "NO RECEIPT TRACE"
                row.supply_error = "Nerastas priėmimo perkėlimas pagal šį PO."

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
