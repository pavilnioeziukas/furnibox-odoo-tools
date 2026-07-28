from core.report_base import ReportBase


class MetadataInspectorReport(ReportBase):
    name = "Metadata Inspector"

    def run(self) -> None:
        models = [
            "purchase.order",
            "purchase.order.line",
            "sale.order",
            "sale.order.line",
            "mrp.bom",
            "mrp.bom.line",
        ]

        for model in models:
            print(f"\n{'=' * 80}")
            print(model)
            print("=" * 80)

            fields = self.client.execute(
                model=model,
                method="fields_get",
                kwargs={
                    "attributes": ["string", "type", "relation"],
                },
            )

            for technical_name in sorted(fields.keys()):
                field = fields[technical_name]

                print(
                    f"{technical_name:35}"
                    f"{field.get('type',''):15}"
                    f"{field.get('relation',''):30}"
                    f"{field.get('string','')}"
                )