from typing import Any

from core.bom_repository import BomRepository
from core.odoo_helpers import many2one_id


class BomSelectionError(RuntimeError):
    """Nepavyko vienareikšmiškai parinkti produkto BOM."""


class BomSelector:
    def __init__(self, repository: BomRepository) -> None:
        self.repository = repository

    def select_for_product(
        self,
        product_id: int,
        *,
        product_sku: str = "",
    ) -> dict[str, Any]:
        product = self.repository.get_product(product_id)

        actual_sku = str(
            product.get("default_code")
            or product_sku
            or product_id
        )

        product_tmpl_id = many2one_id(
            product.get("product_tmpl_id")
        )

        if product_tmpl_id is None:
            raise BomSelectionError(
                f"Produktas {actual_sku} neturi product template"
            )

        variant_boms = self.repository.find_variant_boms(
            product_id
        )

        if variant_boms:
            candidates = variant_boms
            selection_scope = "product variant"
        else:
            candidates = self.repository.find_template_boms(
                product_tmpl_id
            )
            selection_scope = "product template"

        if not candidates:
            raise BomSelectionError(
                f"BOM nerastas produktui {actual_sku}"
            )

        minimum_sequence = min(
            int(bom.get("sequence") or 0)
            for bom in candidates
        )

        best_candidates = [
            bom
            for bom in candidates
            if int(bom.get("sequence") or 0)
            == minimum_sequence
        ]

        if len(best_candidates) != 1:
            candidate_ids = [
                int(bom["id"])
                for bom in best_candidates
            ]

            raise BomSelectionError(
                "Neaiškus aktyvaus BOM pasirinkimas produktui "
                f"{actual_sku}: "
                f"scope={selection_scope}, "
                f"sequence={minimum_sequence}, "
                f"BOM IDs={candidate_ids}"
            )

        return best_candidates[0]