from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Font, PatternFill

from core.data_loader import DataLoader
from core.report_base import BaseReport


class SoPoArrivalReport(BaseReport):
    name = "SO → PO gavimo datų ataskaita"
    description = (
        "Aktyvūs pardavimo užsakymai, susiję aktyvūs pirkimo užsakymai "
        "ir jų planuojamos bei faktinės gavimo datos."
    )

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.loader = DataLoader(client)

    def run(self) -> None:
        print("\n====================================")
        print(self.name)
        print("====================================")
        print("\nNuskaitomi duomenys iš Odoo trimis bendromis užklausomis...")

        dataframe = self.build_dataframe()

        if dataframe.empty:
            print("\nAtaskaitai tinkamų duomenų nerasta.")
            return

        self.print_preview(dataframe)
        output_path = self.export_to_excel(dataframe)

        print("\nAtaskaita sukurta:")
        print(output_path)

    def build_dataframe(self) -> pd.DataFrame:
        sale_orders, purchase_orders, receipts = (
            self.loader.load_so_po_receipt_data(force_reload=True)
        )

        purchase_orders_by_so: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for purchase_order in purchase_orders:
            sale_order_id = self.get_many2one_id(
                purchase_order.get("sale_primary_id")
            )
            if sale_order_id is not None:
                purchase_orders_by_so[sale_order_id].append(purchase_order)

        receipts_by_id = {
            int(receipt["id"]): receipt
            for receipt in receipts
            if receipt.get("id")
        }

        rows: list[dict[str, Any]] = []

        for index, sale_order in enumerate(sale_orders, start=1):
            print(
                f"\rApdorojamas SO {index}/{len(sale_orders)}",
                end="",
                flush=True,
            )

            linked_purchase_orders = purchase_orders_by_so.get(
                int(sale_order["id"]),
                [],
            )

            if not linked_purchase_orders:
                rows.append(
                    self.build_row(
                        sale_order=sale_order,
                        purchase_order=None,
                        receipt=None,
                    )
                )
                continue

            for purchase_order in linked_purchase_orders:
                linked_receipts = [
                    receipts_by_id[picking_id]
                    for picking_id in purchase_order.get("picking_ids", [])
                    if picking_id in receipts_by_id
                ]

                if not linked_receipts:
                    rows.append(
                        self.build_row(
                            sale_order=sale_order,
                            purchase_order=purchase_order,
                            receipt=None,
                        )
                    )
                    continue

                for receipt in linked_receipts:
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
                "Risk Priority",
                "Days Until Commitment",
                "PO Expected Arrival",
                "SO",
                "PO",
                "Receipt",
            ],
            ascending=[True, True, True, True, True, True],
            na_position="last",
        ).reset_index(drop=True)

        return dataframe.drop(columns=["Risk Priority"])

    def build_row(
        self,
        sale_order: dict[str, Any],
        purchase_order: dict[str, Any] | None,
        receipt: dict[str, Any] | None,
    ) -> dict[str, Any]:
        today = pd.Timestamp.now().normalize()
        so_date = self.to_datetime(sale_order.get("date_order"))
        commitment_date = self.to_datetime(
            sale_order.get("commitment_date")
        )

        base_row = {
            "SO": sale_order.get("name", ""),
            "Customer": self.get_many2one_name(
                sale_order.get("partner_id")
            ),
            "SO Date": so_date,
            "SO Age (days)": self.date_difference(today, so_date),
            "Commitment Date": commitment_date,
            "Days Until Commitment": self.date_difference(
                commitment_date,
                today,
            ),
            "Invoice Status": sale_order.get("invoice_status", ""),
        }

        if purchase_order is None:
            return {
                **base_row,
                "PO": "",
                "Vendor": "",
                "PO State": "No Active Purchase Order",
                "PO Expected Arrival": pd.NaT,
                "Receipt": "",
                "Receipt State": "",
                "Scheduled Arrival": pd.NaT,
                "Actual Arrival": pd.NaT,
                "Supplier Delay (days)": pd.NA,
                "Risk Status": "Missing PO",
                "Risk Priority": 1,
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
            supplier_delay = self.open_delay(expected_arrival, today)
            risk_status, risk_priority = self.risk_status(
                days_until_commitment=base_row["Days Until Commitment"],
                supplier_delay_days=supplier_delay,
                receipt_state="",
                has_purchase_order=True,
            )
            return {
                **po_row,
                "Receipt": "",
                "Receipt State": "No Incoming Receipt",
                "Scheduled Arrival": pd.NaT,
                "Actual Arrival": pd.NaT,
                "Supplier Delay (days)": supplier_delay,
                "Risk Status": risk_status,
                "Risk Priority": risk_priority,
            }

        receipt_state = str(receipt.get("state", ""))
        actual_arrival = self.to_datetime(receipt.get("date_done"))
        supplier_delay = self.supplier_delay(
            expected_arrival=expected_arrival,
            actual_arrival=actual_arrival,
            receipt_state=receipt_state,
            today=today,
        )
        risk_status, risk_priority = self.risk_status(
            days_until_commitment=base_row["Days Until Commitment"],
            supplier_delay_days=supplier_delay,
            receipt_state=receipt_state,
            has_purchase_order=True,
        )

        return {
            **po_row,
            "Receipt": receipt.get("name", ""),
            "Receipt State": receipt_state,
            "Scheduled Arrival": self.to_datetime(
                receipt.get("scheduled_date")
            ),
            "Actual Arrival": actual_arrival,
            "Supplier Delay (days)": supplier_delay,
            "Risk Status": risk_status,
            "Risk Priority": risk_priority,
        }

    @staticmethod
    def get_many2one_id(value: Any) -> int | None:
        if isinstance(value, (list, tuple)) and value:
            return int(value[0])
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def get_many2one_name(value: Any) -> str:
        if isinstance(value, (list, tuple)) and len(value) > 1:
            return str(value[1])
        return ""

    @staticmethod
    def to_datetime(value: Any) -> Any:
        if not value:
            return pd.NaT
        return pd.to_datetime(value, errors="coerce")

    @staticmethod
    def date_difference(later_date: Any, earlier_date: Any) -> Any:
        if pd.isna(later_date) or pd.isna(earlier_date):
            return pd.NA
        return int(
            (
                pd.Timestamp(later_date).normalize()
                - pd.Timestamp(earlier_date).normalize()
            ).days
        )

    @staticmethod
    def open_delay(expected_arrival: Any, today: pd.Timestamp) -> Any:
        if pd.isna(expected_arrival):
            return pd.NA
        return max(
            int(
                (
                    today
                    - pd.Timestamp(expected_arrival).normalize()
                ).days
            ),
            0,
        )

    @staticmethod
    def supplier_delay(
        expected_arrival: Any,
        actual_arrival: Any,
        receipt_state: str,
        today: pd.Timestamp,
    ) -> Any:
        if pd.isna(expected_arrival):
            return pd.NA

        expected_day = pd.Timestamp(expected_arrival).normalize()
        comparison_day = today

        if receipt_state == "done" and not pd.isna(actual_arrival):
            comparison_day = pd.Timestamp(actual_arrival).normalize()

        return max(int((comparison_day - expected_day).days), 0)

    @staticmethod
    def risk_status(
        days_until_commitment: Any,
        supplier_delay_days: Any,
        receipt_state: str,
        has_purchase_order: bool,
    ) -> tuple[str, int]:
        if not has_purchase_order:
            return "Missing PO", 1

        if receipt_state == "done":
            if (
                not pd.isna(supplier_delay_days)
                and int(supplier_delay_days) > 0
            ):
                return "Received Late", 5
            return "Received", 6

        if (
            not pd.isna(days_until_commitment)
            and int(days_until_commitment) < 0
        ):
            return "Customer Late", 2

        if (
            not pd.isna(supplier_delay_days)
            and int(supplier_delay_days) > 0
        ):
            return "Supplier Late", 3

        return "Waiting", 4

    @staticmethod
    def print_preview(
        dataframe: pd.DataFrame,
        row_limit: int = 30,
    ) -> None:
        print(f"\nAtaskaitos eilučių: {len(dataframe)}")
        print("\nRizikų suvestinė:")

        for status, count in (
            dataframe["Risk Status"].value_counts(dropna=False).items()
        ):
            print(f"- {status}: {count}")

        print("\nPirmos ataskaitos eilutės:\n")
        with pd.option_context(
            "display.max_rows",
            row_limit,
            "display.max_columns",
            None,
            "display.width",
            320,
        ):
            print(dataframe.head(row_limit).to_string(index=False))

    @staticmethod
    def export_to_excel(dataframe: pd.DataFrame) -> Path:
        output_directory = Path("output")
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / "SO_PO_Arrival_Report.xlsx"

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

            widths = [
                22, 35, 22, 16, 22, 23, 18, 16,
                30, 24, 22, 22, 22, 22, 22, 24,
            ]
            for index, width in enumerate(widths, start=1):
                worksheet.column_dimensions[
                    worksheet.cell(row=1, column=index).column_letter
                ].width = width

            for cell in worksheet[1]:
                cell.font = Font(bold=True)

            fills = {
                "Missing PO": PatternFill("solid", fgColor="F4CCCC"),
                "Customer Late": PatternFill("solid", fgColor="EA9999"),
                "Supplier Late": PatternFill("solid", fgColor="F9CB9C"),
                "Waiting": PatternFill("solid", fgColor="FFF2CC"),
                "Received Late": PatternFill("solid", fgColor="FCE5CD"),
                "Received": PatternFill("solid", fgColor="D9EAD3"),
            }

            status_column = next(
                (
                    cell.column
                    for cell in worksheet[1]
                    if cell.value == "Risk Status"
                ),
                None,
            )
            if status_column is not None:
                for row_number in range(2, worksheet.max_row + 1):
                    status = worksheet.cell(
                        row=row_number,
                        column=status_column,
                    ).value
                    fill = fills.get(status)
                    if fill is None:
                        continue
                    for column_number in range(
                        1,
                        worksheet.max_column + 1,
                    ):
                        worksheet.cell(
                            row=row_number,
                            column=column_number,
                        ).fill = fill

        return output_path.resolve()