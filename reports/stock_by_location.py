from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Font

from core.report_base import BaseReport


class StockByLocationReport(BaseReport):
    name = "SKU likučiai pagal lokaciją"
    description = (
        "Aktyvių stockable produktų fiziniai, rezervuoti ir "
        "laisvi likučiai WH/STOCK bei C/Stock lokacijose."
    )

    LOCATION_IDS = {
        "WH": 8,
        "C": 688,
    }

    BUY_ROUTE_IDS = {
        7,   # Buy
        10,  # Buy Input-Custom
    }

    PRODUCT_FIELDS = [
        "default_code",
        "display_name",
        "categ_id",
        "uom_id",
        "route_ids",
    ]

    CATEGORY_FIELDS = [
        "route_ids",
    ]

    QUANT_FIELDS = [
        "product_id",
        "quantity",
        "reserved_quantity",
    ]

    MOVE_FIELDS = [
        "product_id",
        "picking_id",
        "purchase_line_id",
    ]

    PICKING_FIELDS = [
        "date_done",
    ]

    PURCHASE_LINE_FIELDS = [
        "order_id",
        "price_unit",
        "currency_id",
    ]

    PURCHASE_ORDER_FIELDS = [
        "partner_id",
    ]

    def run(self) -> None:
        print("\n====================================")
        print("SKU LIKUČIAI PAGAL LOKACIJĄ")
        print("====================================")
        print("\nNuskaitomi aktyvūs stockable produktai...")

        products = self.load_products()
        print(f"Rasta produktų: {len(products)}")

        categories = self.load_categories(products)

        buy_product_ids = self.find_buy_product_ids(
            products=products,
            categories=categories,
        )
        print(f"Rasta perkamų produktų: {len(buy_product_ids)}")

        print("Nuskaitomi WH/STOCK likučiai...")
        wh_balances = self.load_location_balances(
            self.LOCATION_IDS["WH"]
        )

        print("Nuskaitomi C/Stock likučiai...")
        c_balances = self.load_location_balances(
            self.LOCATION_IDS["C"]
        )

        print("Nuskaitomi paskutiniai faktiniai pirkimų gavimai...")
        last_purchases = self.load_last_purchases(
            buy_product_ids
        )
        print(
            "Rasta perkamų produktų su faktiniu gavimu: "
            f"{len(last_purchases)}"
        )

        rows = self.build_rows(
            products=products,
            buy_product_ids=buy_product_ids,
            wh_balances=wh_balances,
            c_balances=c_balances,
            last_purchases=last_purchases,
        )

        output_path = self.export_to_excel(rows)

        print("\nAtaskaita sukurta:")
        print(output_path)

    def load_products(self) -> list[dict[str, Any]]:
        product_ids = self.client.search(
            "product.product",
            [
                ("active", "=", True),
                ("detailed_type", "=", "product"),
                ("default_code", "!=", False),
            ],
            order="default_code, id",
        )

        return self.read_in_batches(
            model="product.product",
            record_ids=product_ids,
            fields=self.PRODUCT_FIELDS,
        )

    def load_categories(
        self,
        products: list[dict[str, Any]],
    ) -> dict[int, dict[str, Any]]:
        category_ids = {
            category_id
            for product in products
            if (
                category_id := self.many2one_id(
                    product.get("categ_id")
                )
            ) is not None
        }

        category_records = self.read_in_batches(
            model="product.category",
            record_ids=sorted(category_ids),
            fields=self.CATEGORY_FIELDS,
        )

        return {
            int(category["id"]): category
            for category in category_records
        }

    def find_buy_product_ids(
        self,
        *,
        products: list[dict[str, Any]],
        categories: dict[int, dict[str, Any]],
    ) -> set[int]:
        buy_product_ids: set[int] = set()

        for product in products:
            product_route_ids = {
                int(route_id)
                for route_id in (
                    product.get("route_ids") or []
                )
            }

            category_id = self.many2one_id(
                product.get("categ_id")
            )
            category = categories.get(
                category_id or 0,
                {},
            )
            category_route_ids = {
                int(route_id)
                for route_id in (
                    category.get("route_ids") or []
                )
            }

            effective_route_ids = (
                product_route_ids | category_route_ids
            )

            if effective_route_ids & self.BUY_ROUTE_IDS:
                buy_product_ids.add(int(product["id"]))

        return buy_product_ids

    def load_location_balances(
        self,
        root_location_id: int,
    ) -> dict[int, dict[str, float]]:
        quant_ids = self.client.search(
            "stock.quant",
            [
                ("location_id", "child_of", root_location_id),
            ],
        )

        quants = self.read_in_batches(
            model="stock.quant",
            record_ids=quant_ids,
            fields=self.QUANT_FIELDS,
        )

        balances: dict[int, dict[str, float]] = defaultdict(
            lambda: {
                "on_hand": 0.0,
                "reserved": 0.0,
            }
        )

        for quant in quants:
            product_id = self.many2one_id(
                quant.get("product_id")
            )
            if product_id is None:
                continue

            balances[product_id]["on_hand"] += float(
                quant.get("quantity") or 0
            )
            balances[product_id]["reserved"] += float(
                quant.get("reserved_quantity") or 0
            )

        return dict(balances)

    def load_last_purchases(
        self,
        buy_product_ids: set[int],
    ) -> dict[int, dict[str, Any]]:
        if not buy_product_ids:
            return {}

        move_ids = self.client.search(
            "stock.move",
            [
                ("state", "=", "done"),
                ("product_id", "in", sorted(buy_product_ids)),
                ("purchase_line_id", "!=", False),
                ("picking_id", "!=", False),
                ("location_id.usage", "=", "supplier"),
                ("location_dest_id.usage", "=", "internal"),
            ],
        )

        moves = self.read_in_batches(
            model="stock.move",
            record_ids=move_ids,
            fields=self.MOVE_FIELDS,
        )

        picking_ids = {
            picking_id
            for move in moves
            if (
                picking_id := self.many2one_id(
                    move.get("picking_id")
                )
            ) is not None
        }

        purchase_line_ids = {
            purchase_line_id
            for move in moves
            if (
                purchase_line_id := self.many2one_id(
                    move.get("purchase_line_id")
                )
            ) is not None
        }

        pickings = self.read_map(
            model="stock.picking",
            record_ids=picking_ids,
            fields=self.PICKING_FIELDS,
        )

        purchase_lines = self.read_map(
            model="purchase.order.line",
            record_ids=purchase_line_ids,
            fields=self.PURCHASE_LINE_FIELDS,
        )

        purchase_order_ids = {
            order_id
            for line in purchase_lines.values()
            if (
                order_id := self.many2one_id(
                    line.get("order_id")
                )
            ) is not None
        }

        purchase_orders = self.read_map(
            model="purchase.order",
            record_ids=purchase_order_ids,
            fields=self.PURCHASE_ORDER_FIELDS,
        )

        last_purchases: dict[int, dict[str, Any]] = {}

        for move in moves:
            product_id = self.many2one_id(
                move.get("product_id")
            )
            picking_id = self.many2one_id(
                move.get("picking_id")
            )
            purchase_line_id = self.many2one_id(
                move.get("purchase_line_id")
            )

            if (
                product_id is None
                or picking_id is None
                or purchase_line_id is None
            ):
                continue

            picking = pickings.get(picking_id, {})
            date_done = picking.get("date_done")

            if not date_done:
                continue

            purchase_line = purchase_lines.get(
                purchase_line_id,
                {},
            )
            purchase_order_id = self.many2one_id(
                purchase_line.get("order_id")
            )
            purchase_order = purchase_orders.get(
                purchase_order_id or 0,
                {},
            )

            candidate = {
                "date_done": str(date_done),
                "move_id": int(move["id"]),
                "supplier": self.many2one_name(
                    purchase_order.get("partner_id")
                ),
                "price": float(
                    purchase_line.get("price_unit") or 0
                ),
                "currency": self.many2one_name(
                    purchase_line.get("currency_id")
                ),
            }

            current = last_purchases.get(product_id)

            if current is None:
                last_purchases[product_id] = candidate
                continue

            candidate_key = (
                candidate["date_done"],
                candidate["move_id"],
            )
            current_key = (
                current["date_done"],
                current["move_id"],
            )

            if candidate_key > current_key:
                last_purchases[product_id] = candidate

        return last_purchases

    def read_map(
        self,
        *,
        model: str,
        record_ids: set[int],
        fields: list[str],
    ) -> dict[int, dict[str, Any]]:
        records = self.read_in_batches(
            model=model,
            record_ids=sorted(record_ids),
            fields=fields,
        )

        return {
            int(record["id"]): record
            for record in records
        }

    @staticmethod
    def build_rows(
        *,
        products: list[dict[str, Any]],
        buy_product_ids: set[int],
        wh_balances: dict[int, dict[str, float]],
        c_balances: dict[int, dict[str, float]],
        last_purchases: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        for product in products:
            product_id = int(product["id"])

            wh = wh_balances.get(
                product_id,
                {"on_hand": 0.0, "reserved": 0.0},
            )
            c_stock = c_balances.get(
                product_id,
                {"on_hand": 0.0, "reserved": 0.0},
            )
            last_purchase = last_purchases.get(
                product_id,
                {},
            )

            wh_on_hand = float(wh["on_hand"])
            wh_reserved = float(wh["reserved"])
            c_on_hand = float(c_stock["on_hand"])
            c_reserved = float(c_stock["reserved"])

            is_buy = product_id in buy_product_ids

            rows.append(
                {
                    "SKU": product.get("default_code") or "",
                    "Product": product.get("display_name") or "",
                    "Product Category Name": (
                        StockByLocationReport.many2one_name(
                            product.get("categ_id")
                        )
                    ),
                    "UoM": StockByLocationReport.many2one_name(
                        product.get("uom_id")
                    ),
                    "Buy": "Yes" if is_buy else "No",
                    "Last Supplier": (
                        last_purchase.get("supplier", "")
                        if is_buy
                        else ""
                    ),
                    "Last Purchase Price": (
                        last_purchase.get("price")
                        if last_purchase
                        else None
                    ),
                    "Purchase Currency": (
                        last_purchase.get("currency", "")
                        if is_buy
                        else ""
                    ),
                    "WH On Hand": wh_on_hand,
                    "WH Reserved": wh_reserved,
                    "WH Available": wh_on_hand - wh_reserved,
                    "C On Hand": c_on_hand,
                    "C Reserved": c_reserved,
                    "C Available": c_on_hand - c_reserved,
                }
            )

        return sorted(
            rows,
            key=lambda row: str(row["SKU"]).lower(),
        )

    @staticmethod
    def export_to_excel(
        rows: list[dict[str, Any]],
    ) -> Path:
        output_directory = Path("output")
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        generation_date = datetime.now().strftime("%Y%m%d")

        output_path = (
            output_directory
            / f"SKU_Stock_WH_and_C_{generation_date}.xlsx"
        )

        dataframe = pd.DataFrame(rows)

        with pd.ExcelWriter(
            output_path,
            engine="openpyxl",
        ) as writer:
            dataframe.to_excel(
                writer,
                index=False,
                sheet_name="SKU Stock",
            )

            worksheet = writer.book["SKU Stock"]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

            for cell in worksheet[1]:
                cell.font = Font(bold=True)

            header_positions = {
                cell.value: cell.column
                for cell in worksheet[1]
            }
            price_column = header_positions.get(
                "Last Purchase Price"
            )

            if price_column is not None:
                for row_number in range(
                    2,
                    worksheet.max_row + 1,
                ):
                    worksheet.cell(
                        row=row_number,
                        column=price_column,
                    ).number_format = "#,##0.0000"

            for column_cells in worksheet.columns:
                max_length = max(
                    len(str(cell.value or ""))
                    for cell in column_cells
                )
                column_letter = column_cells[0].column_letter
                worksheet.column_dimensions[
                    column_letter
                ].width = min(
                    max(max_length + 2, 12),
                    50,
                )

        return output_path.resolve()

    def read_in_batches(
        self,
        *,
        model: str,
        record_ids: list[int],
        fields: list[str],
        batch_size: int = 500,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        for start in range(0, len(record_ids), batch_size):
            batch_ids = record_ids[
                start:start + batch_size
            ]
            records.extend(
                self.client.read(
                    model,
                    batch_ids,
                    fields,
                )
            )

        return records

    @staticmethod
    def many2one_id(value: Any) -> int | None:
        if isinstance(value, (list, tuple)) and value:
            return int(value[0])

        if isinstance(value, int):
            return value

        return None

    @staticmethod
    def many2one_name(value: Any) -> str:
        if (
            isinstance(value, (list, tuple))
            and len(value) > 1
        ):
            return str(value[1])

        return ""