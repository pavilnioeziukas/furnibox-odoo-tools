import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.config import OdooConfig
from core.furnix_part_classifier import FurnixPartClassifier
from core.odoo_client import OdooClient, OdooConnectionError


SO_NUMBER = "US262126469REG"
PO_NUMBER = "P04357"

BOM_FILE = Path("output") / f"bom_explosion_{SO_NUMBER}.json"
OUTPUT_FILE = (
    Path("output")
    / f"furnix_detail_probe_{SO_NUMBER}_{PO_NUMBER}.json"
)


def many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])

    return None


def many2one_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1])

    return ""


def load_bom_rows() -> list[dict[str, Any]]:
    if not BOM_FILE.exists():
        raise RuntimeError(
            f"Nerastas BOM išskleidimo failas: {BOM_FILE}. "
            "Pirmiausia paleisk bom_explosion_probe."
        )

    data = json.loads(
        BOM_FILE.read_text(encoding="utf-8")
    )

    return list(data.get("explosion_rows", []))


def main() -> None:
    client = OdooClient(OdooConfig.from_env())

    try:
        client.connect()

        bom_rows = load_bom_rows()

        leaf_rows = [
            row
            for row in bom_rows
            if row.get("is_leaf")
        ]

        furnix_rows = [
            row
            for row in leaf_rows
            if FurnixPartClassifier.is_furnix_detail(
                row.get("component_sku")
            )
        ]

        required_by_sku: dict[str, float] = defaultdict(float)
        origins_by_sku: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for row in furnix_rows:
            sku = str(row.get("component_sku") or "")
            required_qty = float(
                row.get("required_qty") or 0
            )

            required_by_sku[sku] += required_qty

            origins_by_sku[sku].append(
                {
                    "group_name": row.get("group_name"),
                    "root_sku": row.get("root_sku"),
                    "required_qty": required_qty,
                    "path": row.get("path"),
                }
            )

        purchase_orders = client.search_read(
            model="purchase.order",
            domain=[
                ["name", "=", PO_NUMBER],
            ],
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
            raise RuntimeError(
                f"PO nerastas: {PO_NUMBER}"
            )

        if len(purchase_orders) > 1:
            raise RuntimeError(
                f"Rasti keli PO numeriu {PO_NUMBER}"
            )

        purchase_order = purchase_orders[0]

        primary_sale_name = many2one_name(
            purchase_order.get("sale_primary_id")
        )

        if primary_sale_name != SO_NUMBER:
            raise RuntimeError(
                "PO Primary Sale Order nesutampa: "
                f"tikėtasi {SO_NUMBER}, "
                f"gauta {primary_sale_name}"
            )

        po_line_ids = [
            int(line_id)
            for line_id in purchase_order.get(
                "order_line",
                [],
            )
        ]

        po_lines = client.read(
            model="purchase.order.line",
            record_ids=po_line_ids,
            fields=[
                "product_id",
                "product_qty",
                "component_sticker_info",
            ],
        )

        product_ids = sorted(
            {
                product_id
                for line in po_lines
                if (
                    product_id := many2one_id(
                        line.get("product_id")
                    )
                )
                is not None
            }
        )

        products = client.read(
            model="product.product",
            record_ids=product_ids,
            fields=[
                "default_code",
                "display_name",
            ],
        )

        products_by_id = {
            int(product["id"]): product
            for product in products
        }

        po_by_sku: dict[str, float] = defaultdict(float)
        po_details_by_sku: dict[str, list[dict[str, Any]]] = (
            defaultdict(list)
        )

        for line in po_lines:
            product_id = many2one_id(
                line.get("product_id")
            )

            product = products_by_id.get(
                product_id or -1,
                {},
            )

            sku = str(
                product.get("default_code") or ""
            )

            po_qty = float(
                line.get("product_qty") or 0
            )

            po_by_sku[sku] += po_qty

            po_details_by_sku[sku].append(
                {
                    "po_line_id": line.get("id"),
                    "product_name": product.get(
                        "display_name"
                    ),
                    "po_qty": po_qty,
                    "component_sticker_info": line.get(
                        "component_sticker_info"
                    ),
                }
            )

        all_skus = sorted(
            set(required_by_sku)
            | set(po_by_sku)
        )

        comparison_rows: list[dict[str, Any]] = []

        for sku in all_skus:
            required_qty = required_by_sku.get(
                sku,
                0.0,
            )

            po_qty = po_by_sku.get(
                sku,
                0.0,
            )

            difference = po_qty - required_qty

            if sku not in required_by_sku:
                status = "EXTRA"
            elif sku not in po_by_sku:
                status = "MISSING"
            elif abs(difference) > 0.000001:
                status = "QTY MISMATCH"
            else:
                status = "PASS"

            comparison_rows.append(
                {
                    "sku": sku,
                    "classification_reason": (
                        FurnixPartClassifier
                        .classification_reason(sku)
                    ),
                    "required_qty": required_qty,
                    "po_qty": po_qty,
                    "difference": difference,
                    "status": status,
                    "origins": origins_by_sku.get(
                        sku,
                        [],
                    ),
                    "po_lines": po_details_by_sku.get(
                        sku,
                        [],
                    ),
                }
            )

        result = {
            "so_number": SO_NUMBER,
            "po_number": PO_NUMBER,
            "po_state": purchase_order.get("state"),
            "vendor": purchase_order.get("partner_id"),
            "bom_leaf_rows": len(leaf_rows),
            "classified_furnix_rows": len(furnix_rows),
            "classified_unique_skus": len(required_by_sku),
            "po_lines": len(po_lines),
            "po_unique_skus": len(po_by_sku),
            "comparison": comparison_rows,
        }

        OUTPUT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        OUTPUT_FILE.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        print(f"\nSO: {SO_NUMBER}")
        print(f"PO: {PO_NUMBER}")
        print(
            f"PO būsena: "
            f"{purchase_order.get('state')}"
        )
        print(
            f"Tiekėjas: "
            f"{purchase_order.get('partner_id')}"
        )
        print(
            f"Visų leaf BOM eilučių: "
            f"{len(leaf_rows)}"
        )
        print(
            f"Atrinktų Furnix kilmės eilučių: "
            f"{len(furnix_rows)}"
        )
        print(
            f"Unikalių atrinktų SKU: "
            f"{len(required_by_sku)}"
        )
        print(
            f"PO eilučių: {len(po_lines)}"
        )
        print(
            f"Unikalių PO SKU: "
            f"{len(po_by_sku)}"
        )

        print("\nPALYGINIMAS")
        print("=" * 110)

        print(
            f"{'STATUS':<15}"
            f"{'SKU':<48}"
            f"{'REQUIRED':<14}"
            f"{'PO QTY':<14}"
            f"{'DIFFERENCE'}"
        )

        print("-" * 110)

        for row in comparison_rows:
            print(
                f"{row['status']:<15}"
                f"{row['sku'][:46]:<48}"
                f"{row['required_qty']:<14}"
                f"{row['po_qty']:<14}"
                f"{row['difference']}"
            )

        status_counts: dict[str, int] = defaultdict(int)

        for row in comparison_rows:
            status_counts[row["status"]] += 1

        print("\nSTATUSŲ SUVESTINĖ")
        print("=" * 50)

        for status in [
            "PASS",
            "MISSING",
            "EXTRA",
            "QTY MISMATCH",
        ]:
            print(
                f"{status:<15}"
                f"{status_counts.get(status, 0)}"
            )

        print(f"\nRezultatas: {OUTPUT_FILE}")

    except (OdooConnectionError, RuntimeError) as exc:
        print(f"\nKlaida: {exc}")
    except Exception as exc:
        print(f"\nNenumatyta klaida: {exc}")


if __name__ == "__main__":
    main()