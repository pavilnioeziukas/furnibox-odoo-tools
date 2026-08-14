from core.report_base import BaseReport


class WorkCenterDiagnostics(BaseReport):

    name = "Work Center Diagnostics"
    description = "Manufacturing Order diagnostika"

    def run(self):

        print("\n====================================")
        print("WORK CENTER DIAGNOSTICS")
        print("====================================")

        mo = self.client.search_read(
            model="mrp.production",
            domain=[
                ("state", "in", ["confirmed", "planned", "progress"]),
            ],
            fields=[
                "id",
                "name",
                "product_id",
                "bom_id",
                "state",
                "workorder_ids",
            ],
            limit=1,
        )

        if not mo:
            print("Aktyvių MO nerasta.")
            return

        mo = mo[0]

        print(f"\nMO: {mo['name']}")
        print(f"State: {mo['state']}")
        print(f"Product: {mo['product_id']}")
        print(f"BOM: {mo['bom_id']}")
        print(f"Work Orders: {mo['workorder_ids']}")

        if not mo["workorder_ids"]:
            print("\nWork Orders nėra.")
            return

        workorders = self.client.read(
            model="mrp.workorder",
            record_ids=mo["workorder_ids"],
            fields=[
                "name",
                "workcenter_id",
                "duration_expected",
                "duration",
                "state",
            ],
        )

        print("\n-------------------------------------")
        print("WORK ORDERS")
        print("-------------------------------------")

        total = 0

        for wo in workorders:

            wc = ""

            if wo["workcenter_id"]:
                wc = wo["workcenter_id"][1]

            expected = wo.get("duration_expected", 0)

            total += expected

            print(
                f"{wc:25}"
                f"{wo['name']:30}"
                f"{expected:8.1f} min"
                f"   {wo['state']}"
            )

        print("-------------------------------------")
        print(f"TOTAL EXPECTED: {total:.1f} min")