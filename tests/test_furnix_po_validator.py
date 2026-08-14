import unittest

from core.models import BomError
from tests.helpers import (
    FakeExecutionEngine,
    FakeExplosionResult,
    FakeOdooClient,
    explosion_row,
)
from validators.furnix_po_validator import (
    FurnixPoComparisonRow,
    FurnixPoValidationResult,
    FurnixPoValidator,
)


DETAIL_SKU = "EU-SIDE-SREW-720x560-WW"


def client_with_pos(po_specs, *, po_count=1):
    purchase_orders = []
    po_lines = []
    products = []
    for index, spec in enumerate(po_specs, start=1):
        line_id = 100 + index
        product_id = 200 + index
        po_lines.append({
            "id": line_id,
            "product_id": [product_id, spec.get("sku", DETAIL_SKU)],
            "product_qty": spec.get("qty", 1),
            "component_sticker_info": spec.get(
                "sticker", "A-1, ABC123, SO001 [QTY: 1]"
            ),
        })
        products.append({
            "id": product_id,
            "default_code": spec.get("sku", DETAIL_SKU),
            "display_name": spec.get("sku", DETAIL_SKU),
        })
    if po_specs:
        purchase_orders = [
            {
                "id": 10 + index,
                "name": f"P{index:05d}",
                "state": "draft",
                "partner_id": [99, "Furnix, UAB"],
                "sale_primary_id": 1,
                "order_line": [line["id"] for line in po_lines],
            }
            for index in range(1, po_count + 1)
        ]
    return FakeOdooClient({
        "sale.order": [{"id": 1, "name": "SO001"}],
        "purchase.order": purchase_orders,
        "purchase.order.line": po_lines,
        "product.product": products,
    })


def validate(po_specs, *, required_qty=1, bom_errors=None, po_count=1):
    explosion = FakeExplosionResult(
        leaf_rows=[] if bom_errors else [explosion_row(DETAIL_SKU, required_qty)],
        errors=bom_errors or [],
    )
    return FurnixPoValidator(
        client_with_pos(po_specs, po_count=po_count), FakeExecutionEngine(explosion)
    ).validate("SO001")


class FurnixPoValidatorTests(unittest.TestCase):
    def test_mo_po_summary_is_independent_from_catalog_status(self):
        result = FurnixPoValidationResult(
            so_number="SO001",
            status="QTY MISMATCH",
            rows=[
                FurnixPoComparisonRow(
                    sku=DETAIL_SKU,
                    product_name="",
                    required_qty=3,
                    po_qty=2,
                    difference=-1,
                    status="QTY MISMATCH",
                    mo_demand_qty=2,
                    mo_po_status="MATCH",
                )
            ],
        )
        self.assertEqual(result.mo_po_status, "PASS")
        self.assertEqual(result.mo_po_mismatch_count, 0)

    def test_pass(self):
        self.assertEqual(validate([{}]).status, "PASS")

    def test_no_po(self):
        self.assertEqual(validate([]).status, "NO PO")

    def test_multiple_po(self):
        self.assertEqual(validate([{}], po_count=2).status, "MULTIPLE PO")

    def test_missing_detail(self):
        result = validate([{"sku": "NOT-A-FURNIX-ITEM"}])
        self.assertEqual(result.status, "MISSING")
        self.assertEqual(result.missing_count, 1)

    def test_extra_detail(self):
        result = validate(
            [{}, {"sku": "EU-PNL-100x200-WW", "sticker": "C-1, SO001 [QTY: 1]"}]
        )
        self.assertEqual(result.status, "EXTRA")
        self.assertEqual(result.extra_count, 1)

    def test_quantity_mismatch(self):
        result = validate([{"qty": 2}], required_qty=1)
        self.assertEqual(result.status, "QTY MISMATCH")
        self.assertEqual(result.qty_mismatch_count, 1)

    def test_bom_error(self):
        error = BomError(
            so_number="SO001", sale_line_id=1, group_name="A-1",
            root_sku="ROOT", error="BOM sugadintas",
        )
        result = validate([{}], bom_errors=[error])
        self.assertEqual(result.status, "BOM ERROR")
        self.assertIn("BOM sugadintas", result.error)

    def test_sticker_error_affects_overall_status(self):
        result = validate([{"sticker": "A-2, ABC123, SO001 [QTY: 1]"}])
        self.assertEqual(result.status, "STICKER INFO ERROR")


if __name__ == "__main__":
    unittest.main()
