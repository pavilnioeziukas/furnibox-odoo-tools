import unittest

from core.bom_engine import BomEngine
from core.models import BomExplosionResult


class FakeRepository:
    def __init__(self, boms, lines, products):
        self.boms = boms
        self.lines = lines
        self.products = products
        self.client = self

    def get_bom(self, bom_id):
        return self.boms[bom_id]

    def get_bom_lines(self, ids):
        return {line_id: self.lines[line_id] for line_id in ids}

    def get_product(self, product_id):
        return self.products[product_id]

    def search_read(self, **kwargs):
        return []


def bom(bom_id, parent_product_id, line_ids, *, qty=1):
    return {
        "id": bom_id, "active": True, "product_id": [parent_product_id, "Parent"],
        "product_tmpl_id": [parent_product_id + 1000, "Template"], "product_qty": qty,
        "bom_line_ids": line_ids, "code": "TEST", "type": "normal", "sequence": 0,
    }


def line(line_id, product_id, qty, child_bom_id=None):
    return {
        "id": line_id, "product_id": [product_id, "Component"], "product_qty": qty,
        "child_bom_id": [child_bom_id, "Child"] if child_bom_id else False, "sequence": 0,
    }


class BomEngineTests(unittest.TestCase):
    def run_explosion(self, repository, root_qty=1):
        result = BomExplosionResult(so_number="SO001")
        BomEngine(repository, selector=None)._explode_bom(
            so_number="SO001", sale_line_id=1, group_name="A-1", root_product_id=1,
            root_sku="ROOT", root_qty=root_qty, current_bom_id=100,
            required_parent_qty=root_qty, level=1, path=["ROOT"],
            visited_bom_ids=set(), result=result,
        )
        return result

    def test_multilevel_quantities_are_multiplied_and_scaled_by_bom_base_qty(self):
        repository = FakeRepository(
            boms={100: bom(100, 1, [1000], qty=2), 200: bom(200, 2, [2000], qty=1)},
            lines={1000: line(1000, 2, 4, 200), 2000: line(2000, 3, 3)},
            products={1: {"default_code": "ROOT"}, 2: {"default_code": "SUB"}, 3: {"default_code": "LEAF"}},
        )
        result = self.run_explosion(repository, root_qty=5)
        self.assertEqual([row.required_qty for row in result.rows], [10, 30])
        self.assertEqual([row.component_sku for row in result.leaf_rows], ["LEAF"])

    def test_cycle_is_rejected(self):
        repository = FakeRepository(
            boms={100: bom(100, 1, [1000]), 200: bom(200, 2, [2000])},
            lines={1000: line(1000, 2, 1, 200), 2000: line(2000, 1, 1, 100)},
            products={1: {"default_code": "ROOT"}, 2: {"default_code": "SUB"}},
        )
        with self.assertRaisesRegex(RuntimeError, "BOM ciklas"):
            self.run_explosion(repository)

    def test_empty_bom_is_rejected(self):
        repository = FakeRepository(
            boms={100: bom(100, 1, [])}, lines={}, products={1: {"default_code": "ROOT"}},
        )
        with self.assertRaisesRegex(RuntimeError, "neturi BOM"):
            self.run_explosion(repository)

    def test_zero_component_quantity_is_rejected(self):
        repository = FakeRepository(
            boms={100: bom(100, 1, [1000])}, lines={1000: line(1000, 2, 0)},
            products={1: {"default_code": "ROOT"}, 2: {"default_code": "LEAF"}},
        )
        with self.assertRaisesRegex(RuntimeError, "netinkam"):
            self.run_explosion(repository)

    def test_negative_component_quantity_is_rejected(self):
        repository = FakeRepository(
            boms={100: bom(100, 1, [1000])}, lines={1000: line(1000, 2, -1)},
            products={1: {"default_code": "ROOT"}, 2: {"default_code": "LEAF"}},
        )
        with self.assertRaisesRegex(RuntimeError, "netinkam"):
            self.run_explosion(repository)


if __name__ == "__main__":
    unittest.main()
