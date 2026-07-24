from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.data_loader import DataLoader
from core.report_base import BaseReport


CRITICAL_WORK_CENTER_KEYWORDS = (
    "Surinkėjai",
    "Pakuotojai",
)


class WorkCenterLoadReport(BaseReport):
    name = "Work Center Load"
    description = (
        "Aktyvių SO planinio darbo laiko suvestinė pagal kritinius darbo centrus."
    )

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.loader = DataLoader(client)

    def run(self) -> None:
        print("\n====================================")
        print("WORK CENTER LOAD")
        print("====================================")
        print(
            "\nNuskaitomi aktyvūs SO, susiję MO ir kritinių darbo centrų Work Orders..."
        )

        sale_orders, manufacturing_orders, work_orders = (
            self.loader.load_active_so_manufacturing_data(
                force_reload=True
            )
        )

        if not sale_orders:
            print("\nAktyvių SO nerasta.")
            return

        if not manufacturing_orders:
            print("\nAktyviems SO susietų aktyvių MO nerasta.")
            return

        filtered_work_orders = self.filter_critical_work_orders(
            work_orders
        )

        if not filtered_work_orders:
            print("\nKritinių darbo centrų Work Orders nerasta.")
            return

        detail_rows = self.build_detail_rows(
            sale_orders=sale_orders,
            manufacturing_orders=manufacturing_orders,
            work_orders=filtered_work_orders,
        )

        summary = self.calculate_summary(detail_rows)
        self.print_summary(summary)
        self.print_so_breakdown(detail_rows)

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
    def build_detail_rows(
        sale_orders: list[dict[str, Any]],
        manufacturing_orders: list[dict[str, Any]],
        work_orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        sale_orders_by_id = {
            int(sale_order["id"]): sale_order
            for sale_order in sale_orders
        }

        manufacturing_orders_by_id = {
            int(manufacturing_order["id"]): manufacturing_order
            for manufacturing_order in manufacturing_orders
        }

        rows: list[dict[str, Any]] = []

        for work_order in work_orders:
            production_id = WorkCenterLoadReport.get_many2one_id(
                work_order.get("production_id")
            )
            if production_id is None:
                continue

            manufacturing_order = manufacturing_orders_by_id.get(
                production_id
            )
            if manufacturing_order is None:
                continue

            sale_order_id = WorkCenterLoadReport.get_many2one_id(
                manufacturing_order.get("sale_primary_id")
            )
            if sale_order_id is None:
                continue

            sale_order = sale_orders_by_id.get(sale_order_id)
            if sale_order is None:
                continue

            workcenter_name = WorkCenterLoadReport.get_many2one_name(
                work_order.get("workcenter_id")
            )

            rows.append(
                {
                    "SO": sale_order.get("name", ""),
                    "Customer": WorkCenterLoadReport.get_many2one_name(
                        sale_order.get("partner_id")
                    ),
                    "MO": manufacturing_order.get("name", ""),
                    "Work Center": workcenter_name,
                    "Work Order": work_order.get("name", ""),
                    "WO State": work_order.get("state", ""),
                    "Expected Minutes": float(
                        work_order.get("duration_expected") or 0
                    ),
                }
            )

        return rows

    @staticmethod
    def calculate_summary(
        detail_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "Work Center": "",
                "SO": set(),
                "MO": set(),
                "Work Orders": 0,
                "Expected Minutes": 0.0,
                "Waiting": 0,
                "Ready": 0,
                "Progress": 0,
                "Pending": 0,
            }
        )

        for detail_row in detail_rows:
            workcenter_name = str(detail_row["Work Center"])
            row = grouped[workcenter_name]

            row["Work Center"] = workcenter_name
            row["SO"].add(detail_row["SO"])
            row["MO"].add(detail_row["MO"])
            row["Work Orders"] += 1
            row["Expected Minutes"] += float(
                detail_row["Expected Minutes"]
            )

            state = str(detail_row["WO State"] or "")

            if state == "waiting":
                row["Waiting"] += 1
            elif state == "ready":
                row["Ready"] += 1
            elif state == "progress":
                row["Progress"] += 1
            elif state == "pending":
                row["Pending"] += 1

        result: list[dict[str, Any]] = []

        for row in grouped.values():
            result.append(
                {
                    "Work Center": row["Work Center"],
                    "SO Count": len(row["SO"]),
                    "MO Count": len(row["MO"]),
                    "Work Orders": row["Work Orders"],
                    "Expected Minutes": row["Expected Minutes"],
                    "Expected Hours": round(
                        row["Expected Minutes"] / 60,
                        2,
                    ),
                    "Waiting": row["Waiting"],
                    "Ready": row["Ready"],
                    "Progress": row["Progress"],
                    "Pending": row["Pending"],
                }
            )

        return sorted(
            result,
            key=lambda row: row["Expected Minutes"],
            reverse=True,
        )

    @staticmethod
    def print_summary(
        summary: list[dict[str, Any]],
    ) -> None:
        print(
            "\n"
            f"{'Work Center':35}"
            f"{'SO':>7}"
            f"{'MO':>7}"
            f"{'WO':>8}"
            f"{'Minutes':>12}"
            f"{'Hours':>10}"
            f"{'Waiting':>10}"
            f"{'Ready':>8}"
            f"{'Progress':>10}"
            f"{'Pending':>10}"
        )
        print("-" * 117)

        total_minutes = 0.0
        total_work_orders = 0

        for row in summary:
            total_minutes += row["Expected Minutes"]
            total_work_orders += row["Work Orders"]

            print(
                f"{row['Work Center'][:34]:35}"
                f"{row['SO Count']:>7}"
                f"{row['MO Count']:>7}"
                f"{row['Work Orders']:>8}"
                f"{row['Expected Minutes']:>12.1f}"
                f"{row['Expected Hours']:>10.2f}"
                f"{row['Waiting']:>10}"
                f"{row['Ready']:>8}"
                f"{row['Progress']:>10}"
                f"{row['Pending']:>10}"
            )

        print("-" * 117)
        print(
            f"{'TOTAL':35}"
            f"{'':>7}"
            f"{'':>7}"
            f"{total_work_orders:>8}"
            f"{total_minutes:>12.1f}"
            f"{total_minutes / 60:>10.2f}"
        )

    @staticmethod
    def print_so_breakdown(
        detail_rows: list[dict[str, Any]],
        row_limit: int = 30,
    ) -> None:
        grouped: dict[
            tuple[str, str, str],
            dict[str, Any],
        ] = defaultdict(
            lambda: {
                "SO": "",
                "Customer": "",
                "Work Center": "",
                "Work Orders": 0,
                "Expected Minutes": 0.0,
            }
        )

        for detail_row in detail_rows:
            key = (
                str(detail_row["SO"]),
                str(detail_row["Customer"]),
                str(detail_row["Work Center"]),
            )
            row = grouped[key]
            row["SO"] = key[0]
            row["Customer"] = key[1]
            row["Work Center"] = key[2]
            row["Work Orders"] += 1
            row["Expected Minutes"] += float(
                detail_row["Expected Minutes"]
            )

        rows = sorted(
            grouped.values(),
            key=lambda row: row["Expected Minutes"],
            reverse=True,
        )

        print(
            f"\nDidžiausią apkrovą kuriantys SO "
            f"(rodoma {min(row_limit, len(rows))}):"
        )
        print(
            f"{'SO':24}"
            f"{'Customer':34}"
            f"{'Work Center':35}"
            f"{'WO':>8}"
            f"{'Hours':>10}"
        )
        print("-" * 111)

        for row in rows[:row_limit]:
            print(
                f"{row['SO'][:23]:24}"
                f"{row['Customer'][:33]:34}"
                f"{row['Work Center'][:34]:35}"
                f"{row['Work Orders']:>8}"
                f"{row['Expected Minutes'] / 60:>10.2f}"
            )

    @staticmethod
    def get_many2one_id(value: Any) -> int | None:
        if isinstance(value, (list, tuple)) and value:
            return int(value[0])

        if isinstance(value, int):
            return value

        return None

    @staticmethod
    def get_many2one_name(value: Any) -> str:
        if (
            isinstance(value, (list, tuple))
            and len(value) > 1
        ):
            return str(value[1])

        return ""