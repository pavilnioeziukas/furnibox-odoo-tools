import unittest

from core.furnix_part_classifier import FurnixPartClassifier


class FurnixPartClassifierTests(unittest.TestCase):
    def test_srew_detail_with_dimensions_is_furnix_detail(self):
        result = FurnixPartClassifier.classify("eu-side-srew-720x560-ww")
        self.assertTrue(result.is_furnix_detail)
        self.assertEqual(result.rule, "SREW + dimensions")

    def test_panel_with_dimensions_is_furnix_detail(self):
        result = FurnixPartClassifier.classify("EU-PNL-1200x600-WW")
        self.assertTrue(result.is_furnix_detail)
        self.assertEqual(result.detail_type, "PNL")

    def test_detail_without_dimensions_is_not_furnix_detail(self):
        self.assertFalse(FurnixPartClassifier.is_furnix_detail("EU-SIDE-SREW-WW"))

    def test_packaging_exception_is_not_furnix_detail(self):
        self.assertFalse(FurnixPartClassifier.is_furnix_detail("N9566A"))


if __name__ == "__main__":
    unittest.main()
