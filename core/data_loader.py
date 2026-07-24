from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.odoo_client import OdooClient


class DataLoader:
    """Bendras Furnibox Odoo ataskaitų duomenų užkrovimo sluoksnis."""

    def __init__(self, client: OdooClient) -> None:
        self.client = client
        self._sale_orders: list[dict[str, Any]] | None = None
        self._purchase_orders: list[dict[str, Any]] | None = None
        self._receipts: list[dict[str, Any]] | None = None
        self._manufacturing_orders: list[dict[str, Any]] | None = None
        self._work_orders: list[dict[str, Any]] | None = None
        self._sale_order_lines: list[dict[str, Any]] | None = None
        self._products: list[dict[str, Any]] | None = None

    def clear_cache(self) -> None:
        self._sale_orders = None
        self._purchase_orders = None
        self._receipts = None
        self._manufacturing_orders = None
        self._work_orders = None
        self._sale_order_lines = None
        self._products = None

    def load_active_sale_orders(
        self,
        *,
        force_reload: bool = False,
    ) -> list[dict[str, Any]]:
        if self._sale_orders is not None and not force_reload:
            return self._sale_orders

        self._sale_orders = self.client.search_read(
            model="sale.order",
            domain=[
                ("state", "=", "sale"),
                ("invoice_status", "!=", "invoiced"),
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "date_order",
                "commitment_date",
                "invoice_status",
            ],
            order="date_order desc",
        )
        return self._sale_orders

    def load_purchase_orders(
        self,
        sale_order_ids: Iterable[int],
        *,
        force_reload: bool = False,
    ) -> list[dict[str, Any]]:
        if self._purchase_orders is not None and not force_reload:
            return self._purchase_orders

        ids = sorted({int(item) for item in sale_order_ids if item})
        if not ids:
            self._purchase_orders = []
            return self._purchase_orders

        self._purchase_orders = self.client.search_read(
            model="purchase.order",
            domain=[
                ("sale_primary_id", "in", ids),
                ("state", "!=", "cancel"),
            ],
            fields=[
                "id",
                "name",
                "partner_id",
                "state",
                "date_planned",
                "picking_ids",
                "sale_primary_id",
            ],
            order="date_planned asc",
        )
        return self._purchase_orders

    def load_incoming_receipts(
        self,
        picking_ids: Iterable[int],
        *,
        force_reload: bool = False,
    ) -> list[dict[str, Any]]:
        if self._receipts is not None and not force_reload:
            return self._receipts

        ids = sorted({int(item) for item in picking_ids if item})
        if not ids:
            self._receipts = []
            return self._receipts

        records = self.client.read(
            model="stock.picking",
            record_ids=ids,
            fields=[
                "id",
                "name",
                "state",
                "picking_type_code",
                "scheduled_date",
                "date_done",
                "origin",
            ],
        )

        self._receipts = [
            record
            for record in records
            if record.get("picking_type_code") == "incoming"
            and record.get("state") != "cancel"
        ]
        return self._receipts

    def load_active_manufacturing_orders(
        self,
        sale_order_ids: Iterable[int],
        *,
        force_reload: bool = False,
    ) -> list[dict[str, Any]]:
        if self._manufacturing_orders is not None and not force_reload:
            return self._manufacturing_orders

        ids = sorted({int(item) for item in sale_order_ids if item})
        if not ids:
            self._manufacturing_orders = []
            return self._manufacturing_orders

        self._manufacturing_orders = self.client.search_read(
            model="mrp.production",
            domain=[
                ("sale_primary_id", "in", ids),
                ("state", "not in", ["done", "cancel"]),
            ],
            fields=[
                "id",
                "name",
                "sale_primary_id",
                "product_id",
                "state",
                "workorder_ids",
            ],
            order="sale_primary_id, name",
        )
        return self._manufacturing_orders

    def load_work_orders(
        self,
        work_order_ids: Iterable[int],
        *,
        force_reload: bool = False,
    ) -> list[dict[str, Any]]:
        if self._work_orders is not None and not force_reload:
            return self._work_orders

        ids = sorted({int(item) for item in work_order_ids if item})
        if not ids:
            self._work_orders = []
            return self._work_orders

        self._work_orders = self.client.read(
            model="mrp.workorder",
            record_ids=ids,
            fields=[
                "id",
                "name",
                "production_id",
                "workcenter_id",
                "duration_expected",
                "duration",
                "state",
            ],
        )
        return self._work_orders

    def load_active_so_manufacturing_data(
        self,
        *,
        force_reload: bool = False,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        if force_reload:
            self.clear_cache()

        sale_orders = self.load_active_sale_orders()
        manufacturing_orders = self.load_active_manufacturing_orders(
            sale_order["id"] for sale_order in sale_orders
        )

        work_order_ids = [
            work_order_id
            for manufacturing_order in manufacturing_orders
            for work_order_id in manufacturing_order.get("workorder_ids", [])
        ]
        work_orders = self.load_work_orders(work_order_ids)

        return sale_orders, manufacturing_orders, work_orders

    def load_so_po_receipt_data(
        self,
        *,
        force_reload: bool = False,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        if force_reload:
            self.clear_cache()

        sale_orders = self.load_active_sale_orders()
        purchase_orders = self.load_purchase_orders(
            sale_order["id"] for sale_order in sale_orders
        )

        picking_ids = [
            picking_id
            for purchase_order in purchase_orders
            for picking_id in purchase_order.get("picking_ids", [])
        ]
        receipts = self.load_incoming_receipts(picking_ids)

        return sale_orders, purchase_orders, receipts

    def load_sale_order_lines(
        self,
        sale_order_ids: Iterable[int],
        *,
        force_reload: bool = False,
    ) -> list[dict[str, Any]]:
        """Nuskaito aktyvių SO eilutes."""

        if self._sale_order_lines is not None and not force_reload:
            return self._sale_order_lines

        ids = sorted({int(item) for item in sale_order_ids if item})
        if not ids:
            self._sale_order_lines = []
            return self._sale_order_lines

        self._sale_order_lines = self.client.search_read(
            model="sale.order.line",
            domain=[
                ("order_id", "in", ids),
                ("product_id", "!=", False),
                ("display_type", "=", False),
            ],
            fields=[
                "id",
                "order_id",
                "product_id",
                "name",
                "product_uom_qty",
                "qty_delivered",
                "product_uom",
            ],
            order="order_id, id",
        )
        return self._sale_order_lines

    def load_products(
        self,
        product_ids: Iterable[int],
        *,
        force_reload: bool = False,
    ) -> list[dict[str, Any]]:
        """Nuskaito produktus ir jų kategorijas."""

        if self._products is not None and not force_reload:
            return self._products

        ids = sorted({int(item) for item in product_ids if item})
        if not ids:
            self._products = []
            return self._products

        self._products = self.client.read(
            model="product.product",
            record_ids=ids,
            fields=[
                "id",
                "default_code",
                "name",
                "display_name",
                "categ_id",
            ],
        )
        return self._products

    def load_active_so_category_data(
        self,
        *,
        force_reload: bool = False,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Grąžina aktyvius SO, jų eilutes ir produktus."""

        if force_reload:
            self.clear_cache()

        sale_orders = self.load_active_sale_orders()
        sale_order_lines = self.load_sale_order_lines(
            sale_order["id"] for sale_order in sale_orders
        )

        product_ids = [
            int(line["product_id"][0])
            for line in sale_order_lines
            if isinstance(line.get("product_id"), (list, tuple))
            and line["product_id"]
        ]
        products = self.load_products(product_ids)

        return sale_orders, sale_order_lines, products