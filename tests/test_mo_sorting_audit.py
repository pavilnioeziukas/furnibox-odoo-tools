import unittest

from core.mo_sorting_audit import (
    GroupedDocument,
    compare_mo_and_sorting_int,
    duplicate_sides,
    find_sale_group_field,
)
from tests.helpers import FakeExecutionEngine, FakeExplosionResult, FakeOdooClient
from validators.furnix_po_validator import FurnixPoValidator


def doc(document_id, name, group):
    return GroupedDocument(document_id, name, group)


class MoSortingComparisonTests(unittest.TestCase):
    def test_match_and_summary(self):
        result = compare_mo_and_sorting_int(
            [doc(1, "MO001", " A-1 "), doc(2, "MO002", "c-1")],
            [doc(3, "INT001", "a-1"), doc(4, "INT002", "C-1")],
        )
        self.assertEqual(result.status, "PASS")
        self.assertEqual((result.mo_count, result.int_count, result.matched_count), (2, 2, 2))

    def test_missing_both_directions(self):
        result = compare_mo_and_sorting_int(
            [doc(1, "MO001", "A-1")],
            [doc(2, "INT002", "C-1")],
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.missing_int_count, 1)
        self.assertEqual(result.missing_mo_count, 1)

    def test_duplicates_take_priority_and_count_each_side(self):
        result = compare_mo_and_sorting_int(
            [doc(1, "MO001", "A-1"), doc(2, "MO002", "A-1")],
            [doc(3, "INT001", "A-1"), doc(4, "INT002", "A-1")],
        )
        self.assertEqual(result.rows[0].status, "DUPLICATE_GROUP")
        self.assertEqual(duplicate_sides(result.rows), (1, 1))

    def test_blank_group_never_matches(self):
        result = compare_mo_and_sorting_int(
            [doc(1, "MO001", "")], [doc(2, "INT001", "")]
        )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.rows[0].status, "MISSING_GROUP")

    def test_field_is_resolved_from_exact_odoo_label(self):
        self.assertEqual(
            find_sale_group_field({"x_custom": {"string": "Sale Group Name", "type": "char"}}),
            "x_custom",
        )


class MoSortingOdooLoadingTests(unittest.TestCase):
    def test_primary_so_scope_and_only_sorting_int_are_compared(self):
        metadata = {
            "mrp.production": {
                "sale_primary_id": {"string": "Primary Sale Order", "type": "many2one"},
                "name": {"string": "Reference", "type": "char"},
                "state": {"string": "Status", "type": "selection"},
                "x_group": {"string": "Sale Group Name", "type": "char"},
            },
            "stock.picking": {
                "sale_primary_id": {"string": "Primary Sale Order", "type": "many2one"},
                "name": {"string": "Reference", "type": "char"},
                "state": {"string": "Status", "type": "selection"},
                "picking_type_id": {"string": "Operation Type", "type": "many2one"},
                "x_group": {"string": "Sale Group Name", "type": "char"},
            },
        }
        client = FakeOdooClient(
            {
                "mrp.production": [{"id": 1, "name": "MO001", "sale_primary_id": 7, "state": "confirmed", "x_group": "A-1"}],
                "stock.picking": [
                    {"id": 2, "name": "INT001", "sale_primary_id": 7, "state": "assigned", "x_group": "A-1"},
                    {"id": 3, "name": "WH/OUT/1", "sale_primary_id": 7, "state": "assigned", "x_group": "C-1"},
                ],
            },
            metadata,
        )
        validator = FurnixPoValidator(client, FakeExecutionEngine(FakeExplosionResult()))
        result = validator._audit_mo_sorting_int(sale_order_id=7)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.int_count, 1)
        self.assertTrue(any("quantity" in warning for warning in result.warnings))

    def test_missing_group_metadata_is_not_checked(self):
        client = FakeOdooClient({}, {"mrp.production": {}, "stock.picking": {}})
        result = FurnixPoValidator(
            client, FakeExecutionEngine(FakeExplosionResult())
        )._audit_mo_sorting_int(sale_order_id=7)
        self.assertEqual(result.status, "NOT_CHECKED")
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
