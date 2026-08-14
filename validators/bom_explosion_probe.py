import csv
import json
from pathlib import Path
from typing import Any

from core.config import OdooConfig
from core.odoo_client import OdooClient, OdooConnectionError


SO_NUMBER = "US262126469REG"

OUTPUT_JSON = Path("output") / f"bom_explosion_{SO_NUMBER}.json"
OUTPUT_CSV = Path("output") / f"bom_explosion_{SO_NUMBER}.csv"


def many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])

    return None


def many2one_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1])

    return ""


class BomExplosionProbe:
    def __init__(self, client: OdooClient) -> None:
        self.client = client

        self.products: dict[int, dict[str, Any]] = {}
        self.boms: dict[int, dict[str, Any]] = {}
        self.bom_lines: dict[int, dict[str, Any]] = {}

        self.rows: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def load_products(self, product_ids: list[int]) -> None:
        missing_ids = sorted(
            set(product_ids) - set(self.products)
        )

        if not missing_ids:
            return

        records = self.client.read(
            model="product.product",
            record_ids=missing_ids,
            fields=[
                "default_code",
                "display_name",
                "product_tmpl_id",
                "categ_id",
                "seller_ids",
            ],
        )

        for record in records:
            self.products[int(record["id"])] = record

    def load_boms(self, bom_ids: list[int]) -> None:
        missing_ids = sorted(
            set(bom_ids) - set(self.boms)
        )

        if not missing_ids:
            return

        records = self.client.read(
            model="mrp.bom",
            record_ids=missing_ids,
            fields=[
                "active",
                "code",
                "product_id",
                "product_tmpl_id",
                "product_qty",
                "product_uom_id",
                "type",
                "sequence",
                "bom_line_ids",
                "write_date",
            ],
        )

        for record in records:
            self.boms[int(record["id"])] = record

    def load_bom_lines(self, line_ids: list[int]) -> None:
        missing_ids = sorted(
            set(line_ids) - set(self.bom_lines)
        )

        if not missing_ids:
            return

        records = self.client.read(
            model="mrp.bom.line",
            record_ids=missing_ids,
            fields=[
                "bom_id",
                "product_id",
                "product_qty",
                "product_uom_id",
                "sequence",
                "child_bom_id",
            ],
        )

        for record in records:
            self.bom_lines[int(record["id"])] = record

    def get_product(self, product_id: int) -> dict[str, Any]:
        self.load_products([product_id])

        product = self.products.get(product_id)

        if not product:
            raise RuntimeError(
                f"Nepavyko nuskaityti produkto ID {product_id}"
            )

        return product

    def product_sku(self, product_id: int) -> str:
        product = self.get_product(product_id)
        return str(product.get("default_code") or "")

    def product_name(self, product_id: int) -> str:
        product = self.get_product(product_id)
        return str(product.get("display_name") or "")

    def select_top_level_bom(
        self,
        product_id: int,
    ) -> dict[str, Any]:
        product = self.get_product(product_id)

        product_tmpl_id = many2one_id(
            product.get("product_tmpl_id")
        )

        if product_tmpl_id is None:
            raise RuntimeError(
                f"Produktas {product_id} neturi product template"
            )

        candidate_fields = [
            "active",
            "code",
            "product_id",
            "product_tmpl_id",
            "product_qty",
            "product_uom_id",
            "type",
            "sequence",
            "bom_line_ids",
            "write_date",
        ]

        variant_boms = self.client.search_read(
            model="mrp.bom",
            domain=[
                ["active", "=", True],
                ["product_id", "=", product_id],
            ],
            fields=candidate_fields,
            order="sequence asc, id asc",
        )

        if variant_boms:
            candidates = variant_boms
        else:
            candidates = self.client.search_read(
                model="mrp.bom",
                domain=[
                    ["active", "=", True],
                    ["product_id", "=", False],
                    ["product_tmpl_id", "=", product_tmpl_id],
                ],
                fields=candidate_fields,
                order="sequence asc, id asc",
            )

        if not candidates:
            raise RuntimeError(
                "BOM nerastas produktui "
                f"{self.product_sku(product_id)} "
                f"(product ID {product_id})"
            )

        minimum_sequence = min(
            int(bom.get("sequence") or 0)
            for bom in candidates
        )

        selected_candidates = [
            bom
            for bom in candidates
            if int(bom.get("sequence") or 0)
            == minimum_sequence
        ]

        if len(selected_candidates) != 1:
            candidate_ids = [
                bom.get("id")
                for bom in selected_candidates
            ]

            raise RuntimeError(
                "Neaiškus aktyvaus BOM pasirinkimas produktui "
                f"{self.product_sku(product_id)}: "
                f"sequence={minimum_sequence}, "
                f"BOM IDs={candidate_ids}"
            )

        selected = selected_candidates[0]
        self.boms[int(selected["id"])] = selected

        return selected

    def add_error(
        self,
        *,
        group_name: str,
        root_sku: str,
        message: str,
        path: list[str],
    ) -> None:
        self.errors.append(
            {
                "group_name": group_name,
                "root_sku": root_sku,
                "status": "BOM ERROR",
                "error": message,
                "path": " > ".join(path),
            }
        )

    def explode_bom(
        self,
        *,
        group_name: str,
        sale_line_id: int,
        root_product_id: int,
        root_qty: float,
        current_bom_id: int,
        required_parent_qty: float,
        level: int,
        path: list[str],
        visited_bom_ids: set[int],
    ) -> None:
        if current_bom_id in visited_bom_ids:
            raise RuntimeError(
                f"Aptiktas BOM ciklas: BOM ID {current_bom_id}"
            )

        next_visited = set(visited_bom_ids)
        next_visited.add(current_bom_id)

        self.load_boms([current_bom_id])
        bom = self.boms.get(current_bom_id)

        if not bom:
            raise RuntimeError(
                f"Nepavyko nuskaityti BOM ID {current_bom_id}"
            )

        if not bom.get("active"):
            raise RuntimeError(
                f"Sub-BOM ID {current_bom_id} nėra aktyvus"
            )

        bom_base_qty = float(bom.get("product_qty") or 0)

        if bom_base_qty <= 0:
            raise RuntimeError(
                f"BOM ID {current_bom_id} turi netinkamą "
                f"product_qty={bom_base_qty}"
            )

        line_ids = [
            int(line_id)
            for line_id in bom.get("bom_line_ids", [])
        ]

        if not line_ids:
            raise RuntimeError(
                f"BOM ID {current_bom_id} neturi BOM eilučių"
            )

        self.load_bom_lines(line_ids)

        parent_product_id = (
            many2one_id(bom.get("product_id"))
        )

        if parent_product_id is not None:
            parent_sku = self.product_sku(parent_product_id)
        else:
            parent_sku = many2one_name(
                bom.get("product_tmpl_id")
            )

        sorted_lines = sorted(
            (
                self.bom_lines[line_id]
                for line_id in line_ids
                if line_id in self.bom_lines
            ),
            key=lambda line: (
                int(line.get("sequence") or 0),
                int(line.get("id") or 0),
            ),
        )

        for bom_line in sorted_lines:
            component_id = many2one_id(
                bom_line.get("product_id")
            )

            if component_id is None:
                raise RuntimeError(
                    f"BOM eilutė {bom_line.get('id')} "
                    "neturi produkto"
                )

            component_sku = self.product_sku(component_id)
            component_name = self.product_name(component_id)

            line_qty = float(
                bom_line.get("product_qty") or 0
            )

            required_qty = (
                required_parent_qty
                * line_qty
                / bom_base_qty
            )

            current_path = path + [component_sku]

            child_bom_id = many2one_id(
                bom_line.get("child_bom_id")
            )

            row = {
                "so_number": SO_NUMBER,
                "sale_line_id": sale_line_id,
                "group_name": group_name,
                "root_product_id": root_product_id,
                "root_sku": self.product_sku(
                    root_product_id
                ),
                "root_so_qty": root_qty,
                "level": level,
                "parent_sku": parent_sku,
                "component_product_id": component_id,
                "component_sku": component_sku,
                "component_name": component_name,
                "bom_id": current_bom_id,
                "bom_reference": bom.get("code") or "",
                "bom_type": bom.get("type") or "",
                "bom_sequence": bom.get("sequence"),
                "bom_base_qty": bom_base_qty,
                "bom_line_id": bom_line.get("id"),
                "bom_line_qty": line_qty,
                "required_qty": required_qty,
                "child_bom_id": child_bom_id,
                "is_leaf": child_bom_id is None,
                "path": " > ".join(current_path),
            }

            self.rows.append(row)

            if child_bom_id is not None:
                self.explode_bom(
                    group_name=group_name,
                    sale_line_id=sale_line_id,
                    root_product_id=root_product_id,
                    root_qty=root_qty,
                    current_bom_id=child_bom_id,
                    required_parent_qty=required_qty,
                    level=level + 1,
                    path=current_path,
                    visited_bom_ids=next_visited,
                )

    def process_sale_line(
        self,
        sale_line: dict[str, Any],
    ) -> None:
        group_name = str(
            sale_line.get("group_name") or ""
        )

        product_id = many2one_id(
            sale_line.get("product_id")
        )

        if product_id is None:
            self.add_error(
                group_name=group_name,
                root_sku="",
                message="SO eilutė neturi produkto",
                path=[],
            )
            return

        root_sku = self.product_sku(product_id)
        root_qty = float(
            sale_line.get("product_uom_qty") or 0
        )

        try:
            selected_bom = self.select_top_level_bom(
                product_id
            )

            selected_bom_id = int(
                selected_bom["id"]
            )

            self.explode_bom(
                group_name=group_name,
                sale_line_id=int(sale_line["id"]),
                root_product_id=product_id,
                root_qty=root_qty,
                current_bom_id=selected_bom_id,
                required_parent_qty=root_qty,
                level=1,
                path=[root_sku],
                visited_bom_ids=set(),
            )

        except RuntimeError as exc:
            self.add_error(
                group_name=group_name,
                root_sku=root_sku,
                message=str(exc),
                path=[root_sku],
            )

    def write_outputs(self) -> None:
        OUTPUT_JSON.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        result = {
            "so_number": SO_NUMBER,
            "explosion_rows": self.rows,
            "errors": self.errors,
        }

        OUTPUT_JSON.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        csv_fields = [
            "so_number",
            "sale_line_id",
            "group_name",
            "root_sku",
            "root_so_qty",
            "level",
            "parent_sku",
            "component_sku",
            "component_name",
            "bom_id",
            "bom_reference",
            "bom_type",
            "bom_sequence",
            "bom_base_qty",
            "bom_line_id",
            "bom_line_qty",
            "required_qty",
            "child_bom_id",
            "is_leaf",
            "path",
        ]

        with OUTPUT_CSV.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=csv_fields,
                delimiter=";",
            )

            writer.writeheader()

            for row in self.rows:
                writer.writerow(
                    {
                        field: row.get(field, "")
                        for field in csv_fields
                    }
                )


def main() -> None:
    client = OdooClient(OdooConfig.from_env())
    probe = BomExplosionProbe(client)

    try:
        client.connect()

        sale_orders = client.search_read(
            model="sale.order",
            domain=[
                ["name", "=", SO_NUMBER],
            ],
            fields=[
                "name",
                "order_line",
            ],
            limit=2,
        )

        if not sale_orders:
            raise RuntimeError(
                f"SO nerastas: {SO_NUMBER}"
            )

        if len(sale_orders) > 1:
            raise RuntimeError(
                f"Rasti keli SO numeriu {SO_NUMBER}"
            )

        sale_line_ids = sale_orders[0].get(
            "order_line",
            [],
        )

        sale_lines = client.read(
            model="sale.order.line",
            record_ids=sale_line_ids,
            fields=[
                "group_name",
                "product_id",
                "product_uom_qty",
                "display_type",
            ],
        )

        grouped_sale_lines = [
            line
            for line in sale_lines
            if line.get("group_name")
            and not line.get("display_type")
        ]

        grouped_sale_lines.sort(
            key=lambda line: (
                str(line.get("group_name") or ""),
                int(line.get("id") or 0),
            )
        )

        for sale_line in grouped_sale_lines:
            probe.process_sale_line(sale_line)

        probe.write_outputs()

        leaf_rows = [
            row
            for row in probe.rows
            if row.get("is_leaf")
        ]

        print(f"\nSO: {SO_NUMBER}")
        print(
            f"Grupuotų SO eilučių: "
            f"{len(grouped_sale_lines)}"
        )
        print(
            f"Visų BOM išskleidimo eilučių: "
            f"{len(probe.rows)}"
        )
        print(
            f"Galutinių komponentų eilučių: "
            f"{len(leaf_rows)}"
        )
        print(
            f"BOM klaidų: {len(probe.errors)}"
        )

        print(f"\nJSON: {OUTPUT_JSON}")
        print(f"CSV:  {OUTPUT_CSV}")

        if probe.errors:
            print("\nBOM ERRORS")
            print("=" * 100)

            for error in probe.errors:
                print(
                    f"{error.get('group_name')} | "
                    f"{error.get('root_sku')} | "
                    f"{error.get('error')}"
                )

        print("\nLEAF COMPONENTS")
        print("=" * 180)

        print(
            f"{'GROUP':<10}"
            f"{'ROOT SKU':<30}"
            f"{'LVL':<6}"
            f"{'COMPONENT SKU':<42}"
            f"{'REQUIRED':<12}"
            f"{'BOM TYPE':<12}"
            f"{'PATH'}"
        )

        print("-" * 180)

        for row in leaf_rows:
            print(
                f"{str(row.get('group_name')):<10}"
                f"{str(row.get('root_sku'))[:28]:<30}"
                f"{str(row.get('level')):<6}"
                f"{str(row.get('component_sku'))[:40]:<42}"
                f"{str(row.get('required_qty')):<12}"
                f"{str(row.get('bom_type')):<12}"
                f"{row.get('path')}"
            )

    except (OdooConnectionError, RuntimeError) as exc:
        print(f"\nKlaida: {exc}")
    except Exception as exc:
        print(f"\nNenumatyta klaida: {exc}")


if __name__ == "__main__":
    main()