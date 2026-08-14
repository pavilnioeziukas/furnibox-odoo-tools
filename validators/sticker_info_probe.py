import json
from pathlib import Path
from typing import Any

from core.config import OdooConfig
from core.odoo_client import OdooClient, OdooConnectionError


SO_NUMBER = "US262126469REG"
PO_NUMBER = "P04357"

OUTPUT_FILE = Path("output") / f"sticker_info_probe_{PO_NUMBER}.json"


def require_fields(
    client: OdooClient,
    model: str,
    required_fields: list[str],
) -> None:
    metadata = client.execute(
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
        if field_name not in metadata
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
            "purchase.order",
            [
                "name",
                "state",
                "partner_id",
                "sale_primary_id",
                "order_line",
            ],
        )

        require_fields(
            client,
            "purchase.order.line",
            [
                "order_id",
                "product_id",
                "name",
                "product_qty",
                "product_uom",
                "component_sticker_info",
                "sale_order_id",
            ],
        )

        require_fields(
            client,
            "sale.order",
            [
                "name",
                "order_line",
            ],
        )

        require_fields(
            client,
            "sale.order.line",
            [
                "order_id",
                "product_id",
                "name",
                "product_uom_qty",
                "product_uom",
            ],
        )

        sales_orders = client.search_read(
            model="sale.order",
            domain=[["name", "=", SO_NUMBER]],
            fields=["name", "order_line"],
            limit=2,
        )

        if not sales_orders:
            raise RuntimeError(f"SO nerastas: {SO_NUMBER}")

        if len(sales_orders) > 1:
            raise RuntimeError(
                f"Rasti keli SO tuo pačiu numeriu: {SO_NUMBER}"
            )

        sale_order = sales_orders[0]

        purchase_orders = client.search_read(
            model="purchase.order",
            domain=[["name", "=", PO_NUMBER]],
            fields=[
                "name",
                "state",
                "partner_id",
                "sale_primary_id",
                "order_line",
            ],
            limit=2,
        )

        if not purchase_orders:
            raise RuntimeError(f"PO nerastas: {PO_NUMBER}")

        if len(purchase_orders) > 1:
            raise RuntimeError(
                f"Rasti keli PO tuo pačiu numeriu: {PO_NUMBER}"
            )

        purchase_order = purchase_orders[0]

        po_primary_sale = purchase_order.get("sale_primary_id")
        po_primary_sale_name = (
            po_primary_sale[1]
            if isinstance(po_primary_sale, list) and len(po_primary_sale) > 1
            else None
        )

        if po_primary_sale_name != SO_NUMBER:
            raise RuntimeError(
                "PO Primary Sale Order nesutampa. "
                f"PO={PO_NUMBER}, "
                f"tikėtasi={SO_NUMBER}, "
                f"gauta={po_primary_sale_name}"
            )

        po_line_ids = purchase_order.get("order_line", [])
        po_lines: list[dict[str, Any]] = []

        if po_line_ids:
            po_lines = client.read(
                model="purchase.order.line",
                record_ids=po_line_ids,
                fields=[
                    "order_id",
                    "product_id",
                    "name",
                    "product_qty",
                    "product_uom",
                    "component_sticker_info",
                    "sale_order_id",
                ],
            )

        so_line_ids = sale_order.get("order_line", [])
        so_lines: list[dict[str, Any]] = []

        if so_line_ids:
            so_lines = client.read(
                model="sale.order.line",
                record_ids=so_line_ids,
                fields=[
                    "order_id",
                    "product_id",
                    "name",
                    "product_uom_qty",
                    "product_uom",
                ],
            )

        result = {
            "sales_order": sale_order,
            "purchase_order": purchase_order,
            "purchase_order_lines": po_lines,
            "sales_order_lines": so_lines,
        }

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

        OUTPUT_FILE.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        print("\nPrisijungimas ir duomenų nuskaitymas sėkmingas.")
        print(f"SO: {SO_NUMBER}")
        print(f"PO: {PO_NUMBER}")
        print(f"PO būsena: {purchase_order.get('state')}")
        print(f"Tiekėjas: {purchase_order.get('partner_id')}")
        print(f"PO eilučių: {len(po_lines)}")
        print(f"SO eilučių: {len(so_lines)}")
        print(f"Rezultatas išsaugotas: {OUTPUT_FILE}")

        print("\nCOMPONENT STICKER INFO")
        print("=" * 100)

        for line in po_lines:
            product = line.get("product_id")
            product_name = (
                product[1]
                if isinstance(product, list) and len(product) > 1
                else str(product)
            )

            sticker_info = line.get("component_sticker_info")

            print(f"\nPO eilutės ID: {line.get('id')}")
            print(f"Produktas: {product_name}")
            print(f"Kiekis: {line.get('product_qty')}")
            print("Sticker Info pradžia:")
            print("-" * 100)
            print(sticker_info)
            print("-" * 100)
            print(f"Sticker Info repr: {sticker_info!r}")

    except (OdooConnectionError, RuntimeError) as exc:
        print(f"\nKlaida: {exc}")


if __name__ == "__main__":
    main()