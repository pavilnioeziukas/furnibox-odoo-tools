from typing import Any

from core.bom_repository import (
    BomRepository,
    BomRepositoryError,
)
from core.bom_selector import (
    BomSelectionError,
    BomSelector,
)
from core.models import (
    BomError,
    BomExplosionResult,
    ExplosionRow,
)
from core.odoo_helpers import (
    many2one_id,
    many2one_name,
)


class BomEngine:
    def __init__(
        self,
        repository: BomRepository,
        selector: BomSelector,
    ) -> None:
        self.repository = repository
        self.selector = selector

    def explode_sales_order(
        self,
        so_number: str,
        *,
        only_grouped_lines: bool = True,
    ) -> BomExplosionResult:
        result = BomExplosionResult(
            so_number=so_number,
        )

        sale_orders = self.repository.client.search_read(
            model="sale.order",
            domain=[
                ["name", "=", so_number],
            ],
            fields=[
                "name",
                "order_line",
            ],
            limit=2,
        )

        if not sale_orders:
            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=None,
                    group_name="",
                    root_sku="",
                    error=f"SO nerastas: {so_number}",
                )
            )
            return result

        if len(sale_orders) > 1:
            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=None,
                    group_name="",
                    root_sku="",
                    error=(
                        "Rasti keli SO tuo paÄ¨iu numeriu: "
                        f"{so_number}"
                    ),
                )
            )
            return result

        sale_line_ids = [
            int(line_id)
            for line_id in sale_orders[0].get(
                "order_line",
                [],
            )
        ]

        if not sale_line_ids:
            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=None,
                    group_name="",
                    root_sku="",
                    error=f"SO neturi eiluÄ¨iÅ³: {so_number}",
                )
            )
            return result

        sale_lines = self.repository.client.read(
            model="sale.order.line",
            record_ids=sale_line_ids,
            fields=[
                "group_name",
                "product_id",
                "product_uom_qty",
                "display_type",
                "sequence",
            ],
        )

        processable_lines = []

        for sale_line in sale_lines:
            if sale_line.get("display_type"):
                continue

            if only_grouped_lines and not sale_line.get(
                "group_name"
            ):
                continue

            processable_lines.append(sale_line)

        processable_lines.sort(
            key=lambda line: (
                int(line.get("sequence") or 0),
                int(line.get("id") or 0),
            )
        )

        for sale_line in processable_lines:
            self._process_sale_line(
                so_number=so_number,
                sale_line=sale_line,
                result=result,
            )

        return result

    def _process_sale_line(
        self,
        *,
        so_number: str,
        sale_line: dict[str, Any],
        result: BomExplosionResult,
    ) -> None:
        sale_line_id = int(sale_line["id"])
        group_name = str(
            sale_line.get("group_name") or ""
        )

        product_id = many2one_id(
            sale_line.get("product_id")
        )

        if product_id is None:
            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_sku="",
                    error="SO eilutÄ— neturi produkto",
                )
            )
            return

        try:
            product = self.repository.get_product(
                product_id
            )

            root_sku = str(
                product.get("default_code") or ""
            )

            root_qty = float(
                sale_line.get("product_uom_qty")
                or 0
            )

            if root_qty <= 0:
                raise RuntimeError(
                    f"SO eilutÄ—s kiekis netinkamas: {root_qty}"
                )

            selected_bom = (
                self.selector.select_for_product(
                    product_id,
                    product_sku=root_sku,
                )
            )

            selected_bom_id = int(
                selected_bom["id"]
            )

            self._explode_bom(
                so_number=so_number,
                sale_line_id=sale_line_id,
                group_name=group_name,
                root_product_id=product_id,
                root_sku=root_sku,
                root_qty=root_qty,
                current_bom_id=selected_bom_id,
                required_parent_qty=root_qty,
                level=1,
                path=[root_sku],
                visited_bom_ids=set(),
                result=result,
            )

        except (
            BomRepositoryError,
            BomSelectionError,
            RuntimeError,
        ) as exc:
            root_sku = ""

            try:
                product = self.repository.get_product(
                    product_id
                )
                root_sku = str(
                    product.get("default_code") or ""
                )
            except BomRepositoryError:
                pass

            result.errors.append(
                BomError(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_sku=root_sku,
                    error=str(exc),
                    path=root_sku,
                )
            )

    def _resolve_bom_parent_sku(
        self,
        bom: dict[str, Any],
    ) -> str:
        """Grąžina tikrą BOM tėvinio produkto SKU.

        Odoo BOM dažnai turi tik product_tmpl_id, todėl many2one
        pavadinimas nėra tinkamas stabilus palyginimo raktas.
        """
        parent_product_id = many2one_id(
            bom.get("product_id")
        )

        if parent_product_id is not None:
            parent_product = self.repository.get_product(
                parent_product_id
            )

            return str(
                parent_product.get("default_code")
                or parent_product.get("display_name")
                or parent_product_id
            ).strip()

        template_id = many2one_id(
            bom.get("product_tmpl_id")
        )

        if template_id is None:
            raise RuntimeError(
                f"BOM ID {bom.get('id')} neturi produkto template."
            )

        variants = self.repository.client.search_read(
            model="product.product",
            domain=[
                ["product_tmpl_id", "=", template_id],
                ["default_code", "!=", False],
            ],
            fields=[
                "default_code",
                "active",
            ],
            limit=3,
        )

        active_variants = [
            row
            for row in variants
            if row.get("active", True)
            and str(row.get("default_code") or "").strip()
        ]

        candidates = active_variants or [
            row
            for row in variants
            if str(row.get("default_code") or "").strip()
        ]

        if len(candidates) != 1:
            raise RuntimeError(
                "Negalima vienareikšmiškai nustatyti BOM tėvinio SKU: "
                f"BOM ID {bom.get('id')}, template ID {template_id}, "
                f"variantų su SKU {len(candidates)}."
            )

        return str(
            candidates[0].get("default_code")
            or ""
        ).strip()

    def _explode_bom(
        self,
        *,
        so_number: str,
        sale_line_id: int,
        group_name: str,
        root_product_id: int,
        root_sku: str,
        root_qty: float,
        current_bom_id: int,
        required_parent_qty: float,
        level: int,
        path: list[str],
        visited_bom_ids: set[int],
        result: BomExplosionResult,
    ) -> None:
        if current_bom_id in visited_bom_ids:
            raise RuntimeError(
                f"Aptiktas BOM ciklas: BOM ID "
                f"{current_bom_id}"
            )

        next_visited = set(visited_bom_ids)
        next_visited.add(current_bom_id)

        bom = self.repository.get_bom(
            current_bom_id
        )

        if not bom.get("active"):
            raise RuntimeError(
                f"BOM ID {current_bom_id} nÄ—ra aktyvus"
            )

        bom_base_qty = float(
            bom.get("product_qty") or 0
        )

        if bom_base_qty <= 0:
            raise RuntimeError(
                f"BOM ID {current_bom_id} turi "
                f"netinkamÄ… product_qty={bom_base_qty}"
            )

        bom_line_ids = [
            int(line_id)
            for line_id in bom.get(
                "bom_line_ids",
                [],
            )
        ]

        if not bom_line_ids:
            raise RuntimeError(
                f"BOM ID {current_bom_id} "
                "neturi BOM eiluÄ¨iÅ³"
            )

        bom_lines_by_id = (
            self.repository.get_bom_lines(
                bom_line_ids
            )
        )

        parent_sku = self._resolve_bom_parent_sku(
            bom
        )

        bom_lines = sorted(
            bom_lines_by_id.values(),
            key=lambda line: (
                int(line.get("sequence") or 0),
                int(line.get("id") or 0),
            ),
        )

        for bom_line in bom_lines:
            component_id = many2one_id(
                bom_line.get("product_id")
            )

            if component_id is None:
                raise RuntimeError(
                    f"BOM eilutÄ— "
                    f"{bom_line.get('id')} "
                    "neturi komponento"
                )

            component = (
                self.repository.get_product(
                    component_id
                )
            )

            component_sku = str(
                component.get("default_code") or ""
            )

            component_name = str(
                component.get("display_name") or ""
            )

            bom_line_qty = float(
                bom_line.get("product_qty") or 0
            )

            if bom_line_qty < 0:
                raise RuntimeError(
                    f"BOM eilutÄ— "
                    f"{bom_line.get('id')} turi "
                    f"netinkamÄ… kiekÄÆ "
                    f"{bom_line_qty}"
                )

            required_qty = (
                required_parent_qty
                * bom_line_qty
                / bom_base_qty
            )

            child_bom_id = many2one_id(
                bom_line.get("child_bom_id")
            )

            current_path = path + [
                component_sku
                or component_name
                or str(component_id)
            ]

            result.rows.append(
                ExplosionRow(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_product_id=root_product_id,
                    root_sku=root_sku,
                    root_so_qty=root_qty,
                    level=level,
                    parent_sku=parent_sku,
                    component_product_id=component_id,
                    component_sku=component_sku,
                    component_name=component_name,
                    bom_id=current_bom_id,
                    bom_reference=str(
                        bom.get("code") or ""
                    ),
                    bom_type=str(
                        bom.get("type") or ""
                    ),
                    bom_sequence=int(
                        bom.get("sequence") or 0
                    ),
                    bom_base_qty=bom_base_qty,
                    bom_line_id=int(
                        bom_line["id"]
                    ),
                    bom_line_qty=bom_line_qty,
                    required_qty=required_qty,
                    child_bom_id=child_bom_id,
                    is_leaf=child_bom_id is None,
                    path=" > ".join(
                        current_path
                    ),
                )
            )

            if child_bom_id is not None:
                self._explode_bom(
                    so_number=so_number,
                    sale_line_id=sale_line_id,
                    group_name=group_name,
                    root_product_id=root_product_id,
                    root_sku=root_sku,
                    root_qty=root_qty,
                    current_bom_id=child_bom_id,
                    required_parent_qty=required_qty,
                    level=level + 1,
                    path=current_path,
                    visited_bom_ids=next_visited,
                    result=result,
                )