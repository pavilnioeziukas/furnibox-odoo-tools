from __future__ import annotations

from collections import defaultdict
from typing import Any


class CapacityCalculator:
    """Likusi planinė neužbaigtų Work Order apkrova."""

    ACTIVE_STATES = {"waiting", "ready", "progress", "pending"}

    @classmethod
    def build_detail_rows(
        cls,
        sale_orders: list[dict[str, Any]],
        manufacturing_orders: list[dict[str, Any]],
        work_orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        sale_orders_by_id = {
            int(sale_order["id"]): sale_order
            for sale_order in sale_orders
            if sale_order.get("id")
        }

        manufacturing_orders_by_id = {
            int(manufacturing_order["id"]): manufacturing_order
            for manufacturing_order in manufacturing_orders
            if manufacturing_order.get("id")
        }

        rows: list[dict[str, Any]] = []

        for work_order in work_orders:
            state = str(work_order.get("state") or "")

            if state not in cls.ACTIVE_STATES:
                continue

            production_id = cls.get_many2one_id(
                work_order.get("production_id")
            )
            if production_id is None:
                continue

            manufacturing_order = manufacturing_orders_by_id.get(
                production_id
            )
            if manufacturing_order is None:
                continue

            sale_order_id = cls.get_many2one_id(
                manufacturing_order.get("sale_primary_id")
            )
            if sale_order_id is None:
                continue

            sale_order = sale_orders_by_id.get(sale_order_id)
            if sale_order is None:
                continue

            remaining_minutes = float(
                work_order.get("duration_expected") or 0
            )

            rows.append(
                {
                    "SO": sale_order.get("name", ""),
                    "Customer": cls.get_many2one_name(
                        sale_order.get("partner_id")
                    ),
                    "MO": manufacturing_order.get("name", ""),
                    "Product": cls.get_many2one_name(
                        manufacturing_order.get("product_id")
                    ),
                    "Work Center": cls.get_many2one_name(
                        work_order.get("workcenter_id")
                    ),
                    "Work Order": work_order.get("name", ""),
                    "WO State": state,
                    "Remaining Minutes": remaining_minutes,
                    "Remaining Hours": round(
                        remaining_minutes / 60,
                        2,
                    ),
                }
            )

        return rows

    @staticmethod
    def calculate_work_center_summary(
        detail_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "Work Center": "",
                "SO": set(),
                "MO": set(),
                "Work Orders": 0,
                "Remaining Minutes": 0.0,
                "Waiting": 0,
                "Ready": 0,
                "Progress": 0,
                "Pending": 0,
            }
        )

        for detail_row in detail_rows:
            workcenter_name = str(
                detail_row["Work Center"]
            )
            row = grouped[workcenter_name]

            row["Work Center"] = workcenter_name
            row["SO"].add(detail_row["SO"])
            row["MO"].add(detail_row["MO"])
            row["Work Orders"] += 1
            row["Remaining Minutes"] += float(
                detail_row["Remaining Minutes"]
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
                    "Remaining Minutes": row[
                        "Remaining Minutes"
                    ],
                    "Remaining Hours": round(
                        row["Remaining Minutes"] / 60,
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
            key=lambda row: row["Remaining Minutes"],
            reverse=True,
        )

    @staticmethod
    def calculate_so_summary(
        detail_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[
            tuple[str, str, str],
            dict[str, Any],
        ] = defaultdict(
            lambda: {
                "SO": "",
                "Customer": "",
                "Work Center": "",
                "MO": set(),
                "Work Orders": 0,
                "Remaining Minutes": 0.0,
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
            row["MO"].add(detail_row["MO"])
            row["Work Orders"] += 1
            row["Remaining Minutes"] += float(
                detail_row["Remaining Minutes"]
            )

        result: list[dict[str, Any]] = []

        for row in grouped.values():
            result.append(
                {
                    "SO": row["SO"],
                    "Customer": row["Customer"],
                    "Work Center": row["Work Center"],
                    "MO Count": len(row["MO"]),
                    "Work Orders": row["Work Orders"],
                    "Remaining Minutes": row[
                        "Remaining Minutes"
                    ],
                    "Remaining Hours": round(
                        row["Remaining Minutes"] / 60,
                        2,
                    ),
                }
            )

        return sorted(
            result,
            key=lambda row: row["Remaining Minutes"],
            reverse=True,
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