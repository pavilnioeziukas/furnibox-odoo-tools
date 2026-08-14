from typing import Any

from core.config import OdooConfig
from core.odoo_client import OdooClient, OdooConnectionError


SO_NUMBER = "US262126469REG"


def get_many2one_name(value: Any) -> str:
    if isinstance(value, list) and len(value) > 1:
        return str(value[1])

    return ""


def main() -> None:
    client = OdooClient(OdooConfig.from_env())

    try:
        client.connect()

        sales_orders = client.search_read(
            model="sale.order",
            domain=[["name", "=", SO_NUMBER]],
            fields=[
                "name",
                "order_line",
            ],
            limit=2,
        )

        if not sales_orders:
            raise RuntimeError(f"SO nerastas: {SO_NUMBER}")

        if len(sales_orders) > 1:
            raise RuntimeError(
                f"Rasti keli SO tuo pačiu numeriu: {SO_NUMBER}"
            )

        sale_order = sales_orders[0]
        sale_line_ids = sale_order.get("order_line", [])

        if not sale_line_ids:
            raise RuntimeError(
                f"SO neturi eilučių: {SO_NUMBER}"
            )

        sale_lines = client.read(
            model="sale.order.line",
            record_ids=sale_line_ids,
            fields=[
                "sequence",
                "group_name",
                "product_id",
                "product_template_id",
                "name",
                "product_uom_qty",
                "display_type",
            ],
        )

        product_ids = [
            line["product_id"][0]
            for line in sale_lines
            if isinstance(line.get("product_id"), list)
            and line["product_id"]
        ]

        products_by_id: dict[int, dict[str, Any]] = {}

        if product_ids:
            products = client.read(
                model="product.product",
                record_ids=list(set(product_ids)),
                fields=[
                    "default_code",
                    "display_name",
                    "product_tmpl_id",
                    "categ_id",
                ],
            )

            products_by_id = {
                product["id"]: product
                for product in products
            }

        print(f"\nSO: {SO_NUMBER}")
        print(f"SO eilučių: {len(sale_lines)}")

        print("\n" + "=" * 160)
        print(
            f"{'SEQ':<8}"
            f"{'GROUP':<12}"
            f"{'SKU':<30}"
            f"{'QTY':<10}"
            f"{'PRODUCT':<60}"
            f"{'CATEGORY'}"
        )
        print("=" * 160)

        for line in sorted(
            sale_lines,
            key=lambda item: (
                item.get("sequence", 0),
                item.get("id", 0),
            ),
        ):
            display_type = line.get("display_type")

            if display_type:
                print(
                    f"{line.get('sequence', '')!s:<8}"
                    f"{line.get('group_name', '')!s:<12}"
                    f"{'[DISPLAY LINE]':<30}"
                    f"{'':<10}"
                    f"{line.get('name', '')}"
                )
                continue

            product_value = line.get("product_id")
            product_id = (
                product_value[0]
                if isinstance(product_value, list)
                and product_value
                else None
            )

            product = (
                products_by_id.get(product_id, {})
                if product_id is not None
                else {}
            )

            sku = product.get("default_code") or ""
            product_name = (
                product.get("display_name")
                or get_many2one_name(product_value)
                or line.get("name", "")
            )
            category = get_many2one_name(
                product.get("categ_id")
            )

            print(
                f"{line.get('sequence', '')!s:<8}"
                f"{line.get('group_name', '')!s:<12}"
                f"{sku:<30}"
                f"{line.get('product_uom_qty', '')!s:<10}"
                f"{product_name[:58]:<60}"
                f"{category}"
            )

    except (OdooConnectionError, RuntimeError) as exc:
        print(f"\nKlaida: {exc}")
    except Exception as exc:
        print(f"\nNenumatyta klaida: {exc}")


if __name__ == "__main__":
    main()