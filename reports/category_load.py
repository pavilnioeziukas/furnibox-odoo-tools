from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Font

from core.data_loader import DataLoader
from core.report_base import BaseReport


DEFAULT_CATEGORY = "All / CABINETS (Assembled)"


class CategoryLoadReport(BaseReport):
    name = "Active SO Category Load"
    description = (
        "Aktyvių pardavimo užsakymų produktų kiekiai "
        "pagal pasirinktą produkto kategoriją."
    )

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.loader = DataLoader(client)

    def run(self) -> None:
        print("\n====================================")
        print("ACTIVE SO CATEGORY LOAD")
        print("====================================")
        print("\nNuskaitomi aktyvūs SO ir jų produktų eilutės...")

        sale_orders, sale_order_lines, products = (
            self.loader.load_active_so_category_data(
                force_reload=True
            )
        )

        sale_orders_by_id = {
            int(order["id"]): order
            for order in sale_orders
            if order.get("id")
        }
        products_by_id = {
            int(product["id"]): product
            for product in products
            if product.get("id")
        }

        categories = self.get_available_categories(products)

        if not categories:
            print("\nAktyvių SO produktų kategorijų nerasta.")
            return

        selected_category = self.select_category(categories)
        if selected_category is None:
            return

        detail_rows = self.build_detail_rows(
            sale_order_lines=sale_order_lines,
            sale_orders_by_id=sale_orders_by_id,
            products_by_id=products_by_id,
            selected_category=selected_category,
        )

        if not detail_rows:
            print(
                "\nPasirinktoje kategorijoje aktyvių SO "
                "produktų nerasta."
            )
            return

        summary_rows = self.build_summary_rows(
            active_so_count=len(sale_orders),
            selected_category=selected_category,
            detail_rows=detail_rows,
        )
        so_summary = self.build_so_summary(detail_rows)
        sku_summary = self.build_sku_summary(detail_rows)

        self.print_summary(summary_rows)
        self.print_so_summary(so_summary)

        output_path = self.export_to_excel(
            selected_category=selected_category,
            summary_rows=summary_rows,
            so_summary=so_summary,
            sku_summary=sku_summary,
            detail_rows=detail_rows,
        )

        print("\nAtaskaita sukurta:")
        print(output_path)

    @staticmethod
    def get_available_categories(
        products: list[dict[str, Any]],
    ) -> list[str]:
        categories = {
            str(product["categ_id"][1])
            for product in products
            if isinstance(product.get("categ_id"), (list, tuple))
            and len(product["categ_id"]) > 1
        }

        return sorted(
            categories,
            key=lambda category: (
                category != DEFAULT_CATEGORY,
                category.lower(),
            ),
        )

    @staticmethod
    def select_category(
        categories: list[str],
    ) -> str | None:
        print("\nPasirinkite produkto kategoriją:")

        for index, category in enumerate(categories, start=1):
            default_marker = (
                " [numatytoji]"
                if category == DEFAULT_CATEGORY
                else ""
            )
            print(f"{index}. {category}{default_marker}")

        print("0. Grįžti")

        while True:
            choice = input(
                "\nKategorijos numeris "
                "(Enter – CABINETS (Assembled)): "
            ).strip()

            if not choice:
                if DEFAULT_CATEGORY in categories:
                    return DEFAULT_CATEGORY

                return categories[0]

            if choice == "0":
                return None

            try:
                selected_index = int(choice) - 1
            except ValueError:
                print("Neteisingas pasirinkimas.")
                continue

            if 0 <= selected_index < len(categories):
                return categories[selected_index]

            print("Neteisingas pasirinkimas.")

    @staticmethod
    def build_detail_rows(
        *,
        sale_order_lines: list[dict[str, Any]],
        sale_orders_by_id: dict[int, dict[str, Any]],
        products_by_id: dict[int, dict[str, Any]],
        selected_category: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        for line in sale_order_lines:
            order_id = CategoryLoadReport.many2one_id(
                line.get("order_id")
            )
            product_id = CategoryLoadReport.many2one_id(
                line.get("product_id")
            )

            if order_id is None or product_id is None:
                continue

            order = sale_orders_by_id.get(order_id)
            product = products_by_id.get(product_id)

            if order is None or product is None:
                continue

            category = CategoryLoadReport.many2one_name(
                product.get("categ_id")
            )
            if category != selected_category:
                continue

            quantity = float(line.get("product_uom_qty") or 0)
            if quantity <= 0:
                continue

            rows.append(
                {
                    "SO": order.get("name", ""),
                    "Customer": CategoryLoadReport.many2one_name(
                        order.get("partner_id")
                    ),
                    "Order Date": order.get("date_order", ""),
                    "Commitment Date": order.get(
                        "commitment_date", ""
                    ),
                    "SKU": product.get("default_code") or "",
                    "Product": (
                        product.get("display_name")
                        or product.get("name")
                        or CategoryLoadReport.many2one_name(
                            line.get("product_id")
                        )
                    ),
                    "Category": category,
                    "Cabinet Qty": quantity,
                    "UoM": CategoryLoadReport.many2one_name(
                        line.get("product_uom")
                    ),
                }
            )

        return sorted(
            rows,
            key=lambda row: (
                str(row["SO"]),
                str(row["SKU"]),
            ),
        )

    @staticmethod
    def build_summary_rows(
        *,
        active_so_count: int,
        selected_category: str,
        detail_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        so_numbers = {
            str(row["SO"]) for row in detail_rows
        }
        cabinet_qty = sum(
            float(row["Cabinet Qty"])
            for row in detail_rows
        )

        return [
            {
                "Metric": "Selected Category",
                "Value": selected_category,
            },
            {
                "Metric": "Active SO",
                "Value": active_so_count,
            },
            {
                "Metric": "SO with Category",
                "Value": len(so_numbers),
            },
            {
                "Metric": "Cabinet Qty",
                "Value": cabinet_qty,
            },
        ]

    @staticmethod
    def build_so_summary(
        detail_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = (
            defaultdict(
                lambda: {
                    "SO": "",
                    "Customer": "",
                    "SKU": set(),
                    "Cabinet Qty": 0.0,
                }
            )
        )

        for row in detail_rows:
            key = (
                str(row["SO"]),
                str(row["Customer"]),
            )
            summary = grouped[key]

            summary["SO"] = key[0]
            summary["Customer"] = key[1]
            summary["SKU"].add(str(row["SKU"]))
            summary["Cabinet Qty"] += float(
                row["Cabinet Qty"]
            )

        result = [
            {
                "SO": row["SO"],
                "Customer": row["Customer"],
                "SKU Count": len(row["SKU"]),
                "Cabinet Qty": row["Cabinet Qty"],
            }
            for row in grouped.values()
        ]

        return sorted(
            result,
            key=lambda row: row["Cabinet Qty"],
            reverse=True,
        )

    @staticmethod
    def build_sku_summary(
        detail_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = (
            defaultdict(
                lambda: {
                    "SKU": "",
                    "Product": "",
                    "SO": set(),
                    "Cabinet Qty": 0.0,
                }
            )
        )

        for row in detail_rows:
            key = (
                str(row["SKU"]),
                str(row["Product"]),
            )
            summary = grouped[key]

            summary["SKU"] = key[0]
            summary["Product"] = key[1]
            summary["SO"].add(str(row["SO"]))
            summary["Cabinet Qty"] += float(
                row["Cabinet Qty"]
            )

        result = [
            {
                "SKU": row["SKU"],
                "Product": row["Product"],
                "SO Count": len(row["SO"]),
                "Cabinet Qty": row["Cabinet Qty"],
            }
            for row in grouped.values()
        ]

        return sorted(
            result,
            key=lambda row: row["Cabinet Qty"],
            reverse=True,
        )

    @staticmethod
    def print_summary(
        summary_rows: list[dict[str, Any]],
    ) -> None:
        print("\nSuvestinė:")
        for row in summary_rows:
            print(f"{row['Metric']}: {row['Value']}")

    @staticmethod
    def print_so_summary(
        rows: list[dict[str, Any]],
        limit: int = 30,
    ) -> None:
        print(
            "\nSO su didžiausiu spintelių kiekiu "
            f"(rodoma {min(limit, len(rows))}):"
        )
        print(
            f"{'SO':24}"
            f"{'Customer':42}"
            f"{'SKU':>8}"
            f"{'Cabinets':>12}"
        )
        print("-" * 86)

        for row in rows[:limit]:
            print(
                f"{row['SO'][:23]:24}"
                f"{row['Customer'][:41]:42}"
                f"{row['SKU Count']:>8}"
                f"{row['Cabinet Qty']:>12.2f}"
            )

    @staticmethod
    def export_to_excel(
        *,
        selected_category: str,
        summary_rows: list[dict[str, Any]],
        so_summary: list[dict[str, Any]],
        sku_summary: list[dict[str, Any]],
        detail_rows: list[dict[str, Any]],
    ) -> Path:
        output_directory = Path("output")
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        safe_category = "".join(
            character
            if character.isalnum() or character in {"-", "_"}
            else "_"
            for character in selected_category
        ).strip("_")

        output_path = (
            output_directory
            / f"Active_SO_Category_Load_{safe_category}.xlsx"
        )

        with pd.ExcelWriter(
            output_path,
            engine="openpyxl",
        ) as writer:
            pd.DataFrame(summary_rows).to_excel(
                writer,
                index=False,
                sheet_name="Summary",
            )
            pd.DataFrame(so_summary).to_excel(
                writer,
                index=False,
                sheet_name="SO Summary",
            )
            pd.DataFrame(sku_summary).to_excel(
                writer,
                index=False,
                sheet_name="SKU Summary",
            )
            pd.DataFrame(detail_rows).to_excel(
                writer,
                index=False,
                sheet_name="SO Details",
            )

            for worksheet in writer.book.worksheets:
                worksheet.freeze_panes = "A2"
                worksheet.auto_filter.ref = (
                    worksheet.dimensions
                )

                for cell in worksheet[1]:
                    cell.font = Font(bold=True)

                for column_cells in worksheet.columns:
                    max_length = max(
                        len(str(cell.value or ""))
                        for cell in column_cells
                    )
                    column_letter = (
                        column_cells[0].column_letter
                    )
                    worksheet.column_dimensions[
                        column_letter
                    ].width = min(
                        max(max_length + 2, 12),
                        45,
                    )

        return output_path.resolve()

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