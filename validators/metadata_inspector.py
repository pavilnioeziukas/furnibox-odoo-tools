from core.config import OdooConfig
from core.odoo_client import OdooClient, OdooConnectionError


MODELS = [
    "sale.order.line",
]

KEYWORDS = [
    "group",
    "name",
    "sequence",
    "product",
    "template",
    "bom",
    "type",
    "quantity",
    "qty",
    "sale",
    "position",
    "line",
    "code",
    "vendor",
    "supplier",
]


def main() -> None:
    client = OdooClient(OdooConfig.from_env())

    try:
        client.connect()

        for model in MODELS:
            fields = client.execute(
                model=model,
                method="fields_get",
                args=[],
                kwargs={
                    "attributes": [
                        "string",
                        "type",
                        "relation",
                        "required",
                        "readonly",
                    ],
                },
            )

            print(f"\n{'=' * 140}")
            print(model)
            print("=" * 140)

            matching_fields = []

            for technical_name, metadata in fields.items():
                label = metadata.get("string", "")
                relation = metadata.get("relation", "")

                searchable_text = (
                    f"{technical_name} "
                    f"{label} "
                    f"{relation}"
                ).lower()

                if any(
                    keyword in searchable_text
                    for keyword in KEYWORDS
                ):
                    matching_fields.append(
                        (technical_name, metadata)
                    )

            for technical_name, metadata in sorted(matching_fields):
                field_type = metadata.get("type", "")
                relation = metadata.get("relation", "")
                label = metadata.get("string", "")
                required = metadata.get("required", False)
                readonly = metadata.get("readonly", False)

                print(
                    f"{technical_name:45}"
                    f"{field_type:15}"
                    f"{str(relation):35}"
                    f"required={str(required):5} "
                    f"readonly={str(readonly):5} "
                    f"{label}"
                )

            print(f"\nRasta laukų: {len(matching_fields)}")

    except OdooConnectionError as exc:
        print(f"\nOdoo klaida: {exc}")
    except Exception as exc:
        print(f"\nNenumatyta klaida: {exc}")


if __name__ == "__main__":
    main()