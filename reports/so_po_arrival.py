from pathlib import Path
from typing import Any

import pandas as pd

from core.report_base import BaseReport


class SoPoArrivalReport(BaseReport):
    name = "SO → PO gavimo datų ataskaita"
    description = (
        "Aktyvūs pardavimo užsakymai, susiję pirkimo užsakymai "
        "ir jų planuojamos bei faktinės gavimo datos."
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

        print("\nAtaskaita sukurta:")
        print(output_path)

    def build_dataframe(self) -> pd.DataFrame:
        sale_orders = self.load_sale_orders()
        rows: list[dict[str, Any]] = []

        for index, sale_order in enumerate(sale_orders, start=1):
            print(
                f"\rApdorojamas SO {index}/{len(sale_orders)}",
                end="",
                flush=True,
            )

            purchase_orders = self.load_purchase_orders(
                sale_order_id=sale_order["id"]
            )

            if not purchase_orders:
                rows.append(
                    self.build_row(
                        sale_order=sale_order,
                        purchase_order=None,
                        receipt=None,
                    )
                )
                continue

            for purchase_order in purchase_orders:
                receipts = self.load_incoming_receipts(
                    purchase_order.get("picking_ids", [])
                )

                if not receipts:
                    rows.append(
                        self.build_row(
                            sale_order=sale_order,
                            purchase_order=purchase_order,
                            receipt=None,
                        )
                    )
                    continue

                for receipt in receipts:
                    rows.append(
                        self.build_row(
                            sale_order=sale_order,
                            purchase_order=purchase_order,
                            receipt=receipt,
                        )
                    )

        print()

        dataframe = pd.DataFrame(rows)

        if dataframe.empty:
            return dataframe

        dataframe = dataframe.sort_values(
            by=[
                "Status Priority",
                "Commitment Date",
                "SO",
                "PO",
                "Receipt",
            ],
            ascending=[
                True,
                True,
                True,
                True,
                True,
            ],
            na_position="last",
        ).reset_index(drop=True)

        dataframe = dataframe.drop(
            columns=["Status Priority"]
        )

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
            "id",
            "name",
            "partner_id",
            "state",
            "date_planned",
            "picking_ids",
        ]

        return self.client.search_read(
            model="purchase.order",
            domain=domain,
            fields=fields,
            order="date_planned asc",
        )

    def load_incoming_receipts(
        self,
        picking_ids: list[int],
    ) -> list[dict[str, Any]]:
        if not picking_ids:
            return []

        receipts = self.client.read(
            model="stock.picking",
            record_ids=picking_ids,
            fields=[
                "name",
                "state",
                "picking_type_code",
                "scheduled_date",
                "date_done",
                "origin",
            ],
        )

        return [
            receipt
            for receipt in receipts
            if receipt.get("picking_type_code") == "incoming"
        ]

    def build_row(
        self,
        sale_order: dict[str, Any],
        purchase_order: dict[str, Any] | None,
        receipt: dict[str, Any] | None,
    ) -> dict[str, Any]:
        commitment_date = self.to_datetime(
            sale_order.get("commitment_date")
        )

        base_row = {
            "SO": sale_order.get("name", ""),
            "Customer": self.get_many2one_name(
                sale_order.get("partner_id")
            ),
            "Commitment Date": commitment_date,
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
                "PO Expected Arrival": pd.NaT,
                "Receipt": "",
                "Receipt State": "",
                "Scheduled Arrival": pd.NaT,
                "Actual Arrival": pd.NaT,
                "Days Late": pd.NA,
                "Status": "No Purchase Order",
                "Status Priority": 1,
            }

        expected_arrival = self.to_datetime(
            purchase_order.get("date_planned")
        )

        po_row = {
            **base_row,
            "PO": purchase_order.get("name", ""),
            "Vendor": self.get_many2one_name(
                purchase_order.get("partner_id")
            ),
            "PO State": purchase_order.get("state", ""),
            "PO Expected Arrival": expected_arrival,
        }

        if receipt is None:
            days_late, status, priority = self.calculate_status(
                expected_arrival=expected_arrival,
                actual_arrival=pd.NaT,
                receipt_state="",
                has_receipt=False,
            )

            return {
                **po_row,
                "Receipt": "",
                "Receipt State": "No Incoming Receipt",
                "Scheduled Arrival": pd.NaT,
                "Actual Arrival": pd.NaT,
                "Days Late": days_late,
                "Status": status,
                "Status Priority": priority,
            }

        actual_arrival = self.to_datetime(
            receipt.get("date_done")
        )

        receipt_state = str(
            receipt.get("state", "")
        )

        days_late, status, priority = self.calculate_status(
            expected_arrival=expected_arrival,
            actual_arrival=actual_arrival,
            receipt_state=receipt_state,
            has_receipt=True,
        )

        return {
            **po_row,
            "Receipt": receipt.get("name", ""),
            "Receipt State": receipt_state,
            "Scheduled Arrival": self.to_datetime(
                receipt.get("scheduled_date")
            ),
            "Actual Arrival": actual_arrival,
            "Days Late": days_late,
            "Status": status,
            "Status Priority": priority,
        }

    @staticmethod
    def calculate_status(
        expected_arrival: Any,
        actual_arrival: Any,
        receipt_state: str,
        has_receipt: bool,
    ) -> tuple[Any, str, int]:
        today = pd.Timestamp.now().normalize()

        if pd.isna(expected_arrival):
            if not has_receipt:
                return pd.NA, "No Expected Arrival", 2

            if receipt_state == "done":
                return pd.NA, "Received - No Expected Date", 6

            return pd.NA, "Open - No Expected Date", 3

        expected_day = expected_arrival.normalize()

        if receipt_state == "done" and not pd.isna(actual_arrival):
            actual_day = actual_arrival.normalize()
            days_late = max(
                int((actual_day - expected_day).days),
                0,
            )

            if days_late > 0:
                return days_late, "Received Late", 4

            return 0, "Received On Time", 7

        days_late = max(
            int((today - expected_day).days),
            0,
        )

        if not has_receipt:
            if days_late > 0:
                return days_late, "Overdue - No Receipt", 1

            return 0, "Expected - No Receipt", 5

        if days_late > 0:
            return days_late, "Overdue", 2

        return 0, "Expected", 6

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

        print(f"\nAtaskaitos eilučių: {total_rows}")
        print("\nStatusų suvestinė:")

        status_counts = (
            dataframe["Status"]
            .value_counts(dropna=False)
        )

        for status, count in status_counts.items():
            print(f"- {status}: {count}")

        print("\nPirmos ataskaitos eilutės:\n")

        with pd.option_context(
            "display.max_rows",
            row_limit,
            "display.max_columns",
            None,
            "display.width",
            280,
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
                "I": 22,
                "J": 22,
                "K": 22,
                "L": 22,
                "M": 15,
                "N": 28,
            }

            for column, width in column_widths.items():
                worksheet.column_dimensions[column].width = width

            for cell in worksheet[1]:
                cell.font = cell.font.copy(
                    bold=True
                )

            status_column = None

            for cell in worksheet[1]:
                if cell.value == "Status":
                    status_column = cell.column
                    break

            if status_column is not None:
                from openpyxl.styles import PatternFill

                fills = {
                    "No Purchase Order": PatternFill(
                        fill_type="solid",
                        fgColor="F4CCCC",
                    ),
                    "Overdue - No Receipt": PatternFill(
                        fill_type="solid",
                        fgColor="F4CCCC",
                    ),
                    "Overdue": PatternFill(
                        fill_type="solid",
                        fgColor="FCE5CD",
                    ),
                    "Received Late": PatternFill(
                        fill_type="solid",
                        fgColor="FCE5CD",
                    ),
                    "Expected": PatternFill(
                        fill_type="solid",
                        fgColor="FFF2CC",
                    ),
                    "Expected - No Receipt": PatternFill(
                        fill_type="solid",
                        fgColor="FFF2CC",
                    ),
                    "Received On Time": PatternFill(
                        fill_type="solid",
                        fgColor="D9EAD3",
                    ),
                }

                for row_number in range(
                    2,
                    worksheet.max_row + 1,
                ):
                    status_cell = worksheet.cell(
                        row=row_number,
                        column=status_column,
                    )

                    fill = fills.get(
                        status_cell.value
                    )

                    if fill:
                        status_cell.fill = fill

        return output_path.resolve()