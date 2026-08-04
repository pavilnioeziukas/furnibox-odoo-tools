from __future__ import annotations

from collections import defaultdict
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

    PRODUCT_FIELDS = [
        "default_code",
        "display_name",
        "categ_id",
        "uom_id",
    ]

    QUANT_FIELDS = [
        "product_id",
        "quantity",
        "reserved_quantity",
    ]

    def run(self) -> None:
        print("\n====================================")
        print("SKU LIKUČIAI PAGAL LOKACIJĄ")
        print("====================================")
        print("\nNuskaitomi aktyvūs stockable produktai...")

        products = self.load_products()
        print(f"Rasta produktų: {len(products)}")

        print("Nuskaitomi WH/STOCK likučiai...")
        wh_balances = self.load_location_balances(
            self.LOCATION_IDS["WH"]
        )

        print("Nuskaitomi C/Stock likučiai...")
        c_balances = self.load_location_balances(
            self.LOCATION_IDS["C"]
        )

        rows = self.build_rows(
            products=products,
            wh_balances=wh_balances,
            c_balances=c_balances,
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

    @staticmethod
    def build_rows(
        *,
        products: list[dict[str, Any]],
        wh_balances: dict[int, dict[str, float]],
        c_balances: dict[int, dict[str, float]],
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

            wh_on_hand = float(wh["on_hand"])
            wh_reserved = float(wh["reserved"])
            c_on_hand = float(c_stock["on_hand"])
            c_reserved = float(c_stock["reserved"])

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

        output_path = (
            output_directory
            / "SKU_Stock_WH_and_C.xlsx"
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