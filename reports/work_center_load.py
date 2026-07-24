from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Font

from core.capacity import CapacityCalculator
from core.data_loader import DataLoader
from core.report_base import BaseReport


CRITICAL_WORK_CENTER_KEYWORDS = (
    "Surinkėjai",
    "Pakuotojai",
)


class WorkCenterLoadReport(BaseReport):
    name = "Work Center Load"
    description = (
        "Aktyvių SO likusio planinio darbo suvestinė "
        "pagal kritinius darbo centrus."
    )

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.loader = DataLoader(client)
        self.capacity = CapacityCalculator()

    def run(self) -> None:
        print("\n====================================")
        print("WORK CENTER LOAD")
        print("====================================")
        print(
            "\nNuskaitomi aktyvūs SO, susiję MO "
            "ir kritinių darbo centrų Work Orders..."
        )

        sale_orders, manufacturing_orders, work_orders = (
            self.loader.load_active_so_manufacturing_data(
                force_reload=True
            )
        )

        filtered_work_orders = self.filter_critical_work_orders(
            work_orders
        )

        detail_rows = self.capacity.build_detail_rows(
            sale_orders=sale_orders,
            manufacturing_orders=manufacturing_orders,
            work_orders=filtered_work_orders,
        )

        if not detail_rows:
            print("\nNebaigtų kritinių operacijų nerasta.")
            return

        work_center_summary = (
            self.capacity.calculate_work_center_summary(
                detail_rows
            )
        )
        so_summary = self.capacity.calculate_so_summary(
            detail_rows
        )

        self.print_work_center_summary(
            work_center_summary
        )
        self.print_so_summary(so_summary)

        output_path = self.export_to_excel(
            work_center_summary=work_center_summary,
            so_summary=so_summary,
            detail_rows=detail_rows,
        )

        print("\nAtaskaita sukurta:")
        print(output_path)

    @staticmethod
    def filter_critical_work_orders(
        work_orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        for work_order in work_orders:
            workcenter = work_order.get("workcenter_id")
            workcenter_name = ""

            if (
                isinstance(workcenter, (list, tuple))
                and len(workcenter) > 1
            ):
                workcenter_name = str(workcenter[1])

            if any(
                keyword.lower() in workcenter_name.lower()
                for keyword in CRITICAL_WORK_CENTER_KEYWORDS
            ):
                result.append(work_order)

        return result

    @staticmethod
    def print_work_center_summary(
        summary: list[dict[str, Any]],
    ) -> None:
        print(
            "\n"
            f"{'Work Center':35}"
            f"{'SO':>7}"
            f"{'MO':>7}"
            f"{'WO':>8}"
            f"{'Remaining h':>14}"
            f"{'Waiting':>10}"
            f"{'Ready':>8}"
            f"{'Progress':>10}"
            f"{'Pending':>10}"
        )
        print("-" * 109)

        total_remaining = 0.0
        total_work_orders = 0

        for row in summary:
            total_remaining += row["Remaining Minutes"]
            total_work_orders += row["Work Orders"]

            print(
                f"{row['Work Center'][:34]:35}"
                f"{row['SO Count']:>7}"
                f"{row['MO Count']:>7}"
                f"{row['Work Orders']:>8}"
                f"{row['Remaining Hours']:>14.2f}"
                f"{row['Waiting']:>10}"
                f"{row['Ready']:>8}"
                f"{row['Progress']:>10}"
                f"{row['Pending']:>10}"
            )

        print("-" * 109)
        print(
            f"{'TOTAL':35}"
            f"{'':>7}"
            f"{'':>7}"
            f"{total_work_orders:>8}"
            f"{total_remaining / 60:>14.2f}"
        )

    @staticmethod
    def print_so_summary(
        summary: list[dict[str, Any]],
        row_limit: int = 30,
    ) -> None:
        print(
            f"\nDidžiausią likusią apkrovą kuriantys SO "
            f"(rodoma {min(row_limit, len(summary))}):"
        )
        print(
            f"{'SO':24}"
            f"{'Customer':34}"
            f"{'Work Center':35}"
            f"{'MO':>7}"
            f"{'WO':>8}"
            f"{'Remaining h':>14}"
        )
        print("-" * 122)

        for row in summary[:row_limit]:
            print(
                f"{row['SO'][:23]:24}"
                f"{row['Customer'][:33]:34}"
                f"{row['Work Center'][:34]:35}"
                f"{row['MO Count']:>7}"
                f"{row['Work Orders']:>8}"
                f"{row['Remaining Hours']:>14.2f}"
            )

    @staticmethod
    def export_to_excel(
        work_center_summary: list[dict[str, Any]],
        so_summary: list[dict[str, Any]],
        detail_rows: list[dict[str, Any]],
    ) -> Path:
        output_directory = Path("output")
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            output_directory
            / "Work_Center_Load_Report.xlsx"
        )

        summary_df = pd.DataFrame(work_center_summary)
        so_df = pd.DataFrame(so_summary)
        details_df = pd.DataFrame(detail_rows)

        with pd.ExcelWriter(
            output_path,
            engine="openpyxl",
        ) as writer:
            summary_df.to_excel(
                writer,
                index=False,
                sheet_name="Work Center Summary",
            )
            so_df.to_excel(
                writer,
                index=False,
                sheet_name="SO Load Details",
            )
            details_df.to_excel(
                writer,
                index=False,
                sheet_name="Work Order Details",
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