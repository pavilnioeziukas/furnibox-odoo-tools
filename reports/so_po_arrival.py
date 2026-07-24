from pathlib import Path
from typing import Any

import pandas as pd

from core.report_base import BaseReport


class SoPoArrivalReport(BaseReport):
    name = "SO → PO gavimo datų ataskaita"
    description = (
        "Aktyvūs pardavimo užsakymai, susiję pirkimo užsakymai "
        "ir planuojamos gavimo datos."
    )

    def run(self) -> None:
        print("\n====================================")
        print(self.name)
        print("====================================")
        print("\nNuskaitomi duomenys iš Odoo...")

        dataframe = self.build_dataframe()

        if dataframe.empty:
            print("\nAtaskaitai tinkamų duomenų nerasta.")
            return

        self.print_preview(dataframe)

        output_path = self.export_to_excel(dataframe)

        print(f"\nAtaskaita sukurta:")
        print(output_path)

    def build_dataframe(self) -> pd.DataFrame:
        sale_orders = self.load_sale_orders()
        rows: list[dict[str, Any]] = []

        for sale_order in sale_orders:
            purchase_orders = self.load_purchase_orders(
                sale_order_id=sale_order["id"]
            )

            if not purchase_orders:
                rows.append(
                    self.build_row(
                        sale_order=sale_order,
                        purchase_order=None,
                    )
                )
                continue

            for purchase_order in purchase_orders:
                rows.append(
                    self.build_row(
                        sale_order=sale_order,
                        purchase_order=purchase_order,
                    )
                )

        dataframe = pd.DataFrame(rows)

        if dataframe.empty:
            return dataframe

        dataframe = dataframe.sort_values(
            by=[
                "Commitment Date",
                "SO",
                "PO",
            ],
            ascending=[
                True,
                True,
                True,
            ],
            na_position="last",
        ).reset_index(drop=True)

        return dataframe

    def load_sale_orders(self) -> list[dict[str, Any]]:
        domain = [
            ("state", "=", "sale"),
            ("invoice_status", "!=", "invoiced"),
        ]

        fields = [
            "id",
            "name",
            "partner_id",
            "commitment_date",
            "invoice_status",
        ]

        return self.client.search_read(
            model="sale.order",
            domain=domain,
            fields=fields,
            order="date_order desc",
        )

    def load_purchase_orders(
        self,
        sale_order_id: int,
    ) -> list[dict[str, Any]]:
        domain = [
            ("sale_primary_id", "=", sale_order_id),
        ]

        fields = [
            "name",
            "partner_id",
            "state",
            "date_planned",
        ]

        return self.client.search_read(
            model="purchase.order",
            domain=domain,
            fields=fields,
            order="date_planned asc",
        )

    def build_row(
        self,
        sale_order: dict[str, Any],
        purchase_order: dict[str, Any] | None,
    ) -> dict[str, Any]:
        customer = self.get_many2one_name(
            sale_order.get("partner_id")
        )

        base_row = {
            "SO": sale_order.get("name", ""),
            "Customer": customer,
            "Commitment Date": self.to_datetime(
                sale_order.get("commitment_date")
            ),
            "Invoice Status": sale_order.get(
                "invoice_status",
                "",
            ),
        }

        if purchase_order is None:
            return {
                **base_row,
                "PO": "",
                "Vendor": "",
                "PO State": "No Purchase Order",
                "Expected Arrival": pd.NaT,
            }

        return {
            **base_row,
            "PO": purchase_order.get("name", ""),
            "Vendor": self.get_many2one_name(
                purchase_order.get("partner_id")
            ),
            "PO State": purchase_order.get(
                "state",
                "",
            ),
            "Expected Arrival": self.to_datetime(
                purchase_order.get("date_planned")
            ),
        }

    @staticmethod
    def get_many2one_name(value: Any) -> str:
        if (
            isinstance(value, (list, tuple))
            and len(value) > 1
        ):
            return str(value[1])

        return ""

    @staticmethod
    def to_datetime(value: Any) -> Any:
        if not value:
            return pd.NaT

        return pd.to_datetime(
            value,
            errors="coerce",
        )

    @staticmethod
    def print_preview(
        dataframe: pd.DataFrame,
        row_limit: int = 30,
    ) -> None:
        total_rows = len(dataframe)
        no_po_count = int(
            (dataframe["PO"] == "").sum()
        )

        print(f"\nAtaskaitos eilučių: {total_rows}")
        print(f"SO be PO: {no_po_count}")
        print("\nPirmos ataskaitos eilutės:\n")

        with pd.option_context(
            "display.max_rows",
            row_limit,
            "display.max_columns",
            None,
            "display.width",
            220,
        ):
            print(
                dataframe.head(row_limit).to_string(
                    index=False
                )
            )

    @staticmethod
    def export_to_excel(
        dataframe: pd.DataFrame,
    ) -> Path:
        output_directory = Path("output")

        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            output_directory
            / "SO_PO_Arrival_Report.xlsx"
        )

        with pd.ExcelWriter(
            output_path,
            engine="openpyxl",
            datetime_format="yyyy-mm-dd hh:mm:ss",
        ) as writer:
            dataframe.to_excel(
                writer,
                index=False,
                sheet_name="SO PO Arrival",
            )

            worksheet = writer.sheets["SO PO Arrival"]

            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

            column_widths = {
                "A": 22,
                "B": 35,
                "C": 22,
                "D": 18,
                "E": 16,
                "F": 30,
                "G": 20,
                "H": 22,
            }

            for column, width in column_widths.items():
                worksheet.column_dimensions[column].width = width

        return output_path.resolve()