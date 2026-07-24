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

    def clear_cache(self) -> None:
        self._sale_orders = None
        self._purchase_orders = None
        self._receipts = None

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