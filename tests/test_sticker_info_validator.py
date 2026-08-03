import unittest

from core.sticker_info_validator import parse_sticker_info, validate_sticker_info


class StickerInfoValidatorTests(unittest.TestCase):
    def test_valid_assignment_passes(self):
        result = validate_sticker_info(
            so_number="SO001",
            po_qty=2,
            origins=[{"group_name": "A-1", "root_sku": "EU-C-CAB01-ABC123-A", "required_qty": 2}],
            sticker_values=["A-1, ABC123, SO001 [QTY: 2]"],
        )
        self.assertEqual(result.status, "PASS")

    def test_empty_value_is_error(self):
        result = validate_sticker_info(
            so_number="SO001",
            po_qty=1,
            origins=[{"group_name": "C-1", "root_sku": "SKU", "required_qty": 1}],
            sticker_values=[""],
        )
        self.assertEqual(result.status, "STICKER INFO ERROR")
        self.assertIn("tuščias", result.error)

    def test_quantity_sum_must_match_po(self):
        result = validate_sticker_info(
            so_number="SO001",
            po_qty=2,
            origins=[{"group_name": "C-1", "root_sku": "SKU", "required_qty": 1}],
            sticker_values=["C-1, SO001 [QTY: 1]"],
        )
        self.assertEqual(result.status, "STICKER INFO ERROR")
        self.assertIn("nesutampa su PO kiekiu", result.error)

    def test_wrong_assignment_is_error(self):
        result = validate_sticker_info(
            so_number="SO001",
            po_qty=1,
            origins=[{"group_name": "C-1", "root_sku": "SKU", "required_qty": 1}],
            sticker_values=["C-2, SO001 [QTY: 1]"],
        )
        self.assertEqual(result.status, "STICKER INFO ERROR")
        self.assertIn("trūksta priskyrimų", result.error)

    def test_decimal_comma_is_supported(self):
        assignments = parse_sticker_info("C-1, SO001 [QTY: 1,5]")
        self.assertEqual(assignments[0].qty, 1.5)


if __name__ == "__main__":
    unittest.main()
