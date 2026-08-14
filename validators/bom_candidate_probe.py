from typing import Any

from core.config import OdooConfig
from core.odoo_client import OdooClient, OdooConnectionError


SO_NUMBER = "US262126469REG"


def many2one_id(value: Any) -> int | None:
    if isinstance(value, list) and value:
        return int(value[0])

    return None


def many2one_name(value: Any) -> str:
    if isinstance(value, list) and len(value) > 1:
        return str(value[1])

    return ""


def require_fields(
    client: OdooClient,
    model: str,
    required_fields: list[str],
) -> None:
    fields = client.execute(
        model=model,
        method="fields_get",
        args=[],
        kwargs={
            "attributes": ["string", "type", "relation"],
        },
    )

    missing = [
        field_name
        for field_name in required_fields
        if field_name not in fields
    ]

    if missing:
        raise RuntimeError(
            f"Modelyje {model} nerasti laukai: {', '.join(missing)}"
        )


def main() -> None:
    client = OdooClient(OdooConfig.from_env())

    try:
        client.connect()

        require_fields(
            client,
            "sale.order.line",
            [
                "order_id",
                "group_name",
                "product_id",
                "product_uom_qty",
            ],
        )

        require_fields(
            client,
            "product.product",
            [
                "default_code",
                "product_tmpl_id",
            ],
        )

        require_fields(
            client,
            "mrp.bom",
            [
                "active",
                "code",
                "product_id",
                "product_tmpl_id",
                "product_qty",
                "type",
                "sequence",
                "bom_line_ids",
                "previous_bom_id",
                "create_date",
                "write_date",
            ],
        )

        sale_orders = client.search_read(
            model="sale.order",
            domain=[["name", "=", SO_NUMBER]],
            fields=["name", "order_line"],
            limit=2,
        )

        if not sale_orders:
            raise RuntimeError(f"SO nerastas: {SO_NUMBER}")

        if len(sale_orders) > 1:
            raise RuntimeError(
                f"Rasti keli SO tuo pačiu numeriu: {SO_NUMBER}"
            )

        sale_line_ids = sale_orders[0].get("order_line", [])

        sale_lines = client.read(
            model="sale.order.line",
            record_ids=sale_line_ids,
            fields=[
                "group_name",
                "product_id",
                "product_uom_qty",
            ],
        )

        grouped_lines = [
            line
            for line in sale_lines
            if line.get("group_name")
            and many2one_id(line.get("product_id")) is not None
        ]

        product_ids = sorted(
            {
                many2one_id(line.get("product_id"))
                for line in grouped_lines
                if many2one_id(line.get("product_id")) is not None
            }
        )

        products = client.read(
            model="product.product",
            record_ids=product_ids,
            fields=[
                "default_code",
                "display_name",
                "product_tmpl_id",
            ],
        )

        products_by_id = {
            product["id"]: product
            for product in products
        }

        print(f"\nSO: {SO_NUMBER}")
        print(f"Grupuotų SO eilučių: {len(grouped_lines)}")

        for sale_line in grouped_lines:
            product_id = many2one_id(sale_line.get("product_id"))

            if product_id is None:
                continue

            product = products_by_id.get(product_id)

            if not product:
                print(
                    f"\nKLAIDA: nepavyko nuskaityti produkto ID {product_id}"
                )
                continue

            product_tmpl_id = many2one_id(
                product.get("product_tmpl_id")
            )

            if product_tmpl_id is None:
                print(
                    f"\nKLAIDA: produktas {product_id} neturi template ID"
                )
                continue

            bom_domain = [
                "|",
                ["product_id", "=", product_id],
                "&",
                ["product_id", "=", False],
                ["product_tmpl_id", "=", product_tmpl_id],
            ]

            boms = client.search_read(
                model="mrp.bom",
                domain=bom_domain,
                fields=[
                    "active",
                    "code",
                    "product_id",
                    "product_tmpl_id",
                    "product_qty",
                    "type",
                    "sequence",
                    "bom_line_ids",
                    "previous_bom_id",
                    "create_date",
                    "write_date",
                ],
                order="sequence asc, write_date desc, id desc",
            )

            print("\n" + "=" * 130)
            print(
                f"GROUP: {sale_line.get('group_name')} | "
                f"SO QTY: {sale_line.get('product_uom_qty')} | "
                f"SKU: {product.get('default_code')} | "
                f"PRODUCT: {product.get('display_name')}"
            )
            print("=" * 130)

            if not boms:
                print("BOM KANDIDATŲ NERASTA")
                continue

            print(
                f"{'ID':<8}"
                f"{'ACTIVE':<9}"
                f"{'SEQ':<7}"
                f"{'TYPE':<14}"
                f"{'BOM QTY':<10}"
                f"{'LINES':<8}"
                f"{'VARIANT':<32}"
                f"{'REFERENCE':<24}"
                f"{'WRITE DATE'}"
            )
            print("-" * 130)

            for bom in boms:
                print(
                    f"{bom.get('id', '')!s:<8}"
                    f"{bom.get('active', '')!s:<9}"
                    f"{bom.get('sequence', '')!s:<7}"
                    f"{bom.get('type', '')!s:<14}"
                    f"{bom.get('product_qty', '')!s:<10}"
                    f"{len(bom.get('bom_line_ids', []))!s:<8}"
                    f"{many2one_name(bom.get('product_id'))[:30]:<32}"
                    f"{str(bom.get('code') or '')[:22]:<24}"
                    f"{bom.get('write_date', '')}"
                )

    except (OdooConnectionError, RuntimeError) as exc:
        print(f"\nKlaida: {exc}")
    except Exception as exc:
        print(f"\nNenumatyta klaida: {exc}")


if __name__ == "__main__":
    main()