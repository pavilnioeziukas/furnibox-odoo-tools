from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.odoo_client import OdooClient


class BomRepositoryError(RuntimeError):
    """Nepavyko nuskaityti BOM duomenų iš Odoo."""


class BomRepository:
    PRODUCT_FIELDS = [
        "default_code",
        "display_name",
        "product_tmpl_id",
        "categ_id",
    ]

    BOM_FIELDS = [
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

    BOM_LINE_FIELDS = [
        "bom_id",
        "product_id",
        "product_qty",
        "product_uom_id",
        "sequence",
        "child_bom_id",
    ]

    def __init__(self, client: "OdooClient") -> None:
        self.client = client

        self._products: dict[int, dict[str, Any]] = {}
        self._boms: dict[int, dict[str, Any]] = {}
        self._bom_lines: dict[int, dict[str, Any]] = {}

    def get_product(
        self,
        product_id: int,
    ) -> dict[str, Any]:
        if product_id not in self._products:
            records = self.client.read(
                model="product.product",
                record_ids=[product_id],
                fields=self.PRODUCT_FIELDS,
            )

            if not records:
                raise BomRepositoryError(
                    f"Nepavyko nuskaityti produkto ID {product_id}"
                )

            self._products[product_id] = records[0]

        return self._products[product_id]

    def get_products(
        self,
        product_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        missing_ids = sorted(
            set(product_ids) - set(self._products)
        )

        if missing_ids:
            records = self.client.read(
                model="product.product",
                record_ids=missing_ids,
                fields=self.PRODUCT_FIELDS,
            )

            for record in records:
                self._products[int(record["id"])] = record

            unresolved_ids = [
                product_id
                for product_id in missing_ids
                if product_id not in self._products
            ]

            if unresolved_ids:
                raise BomRepositoryError(
                    "Nepavyko nuskaityti produktų ID: "
                    + ", ".join(
                        str(product_id)
                        for product_id in unresolved_ids
                    )
                )

        return {
            product_id: self._products[product_id]
            for product_id in product_ids
        }

    def get_bom(
        self,
        bom_id: int,
    ) -> dict[str, Any]:
        if bom_id not in self._boms:
            records = self.client.read(
                model="mrp.bom",
                record_ids=[bom_id],
                fields=self.BOM_FIELDS,
            )

            if not records:
                raise BomRepositoryError(
                    f"Nepavyko nuskaityti BOM ID {bom_id}"
                )

            self._boms[bom_id] = records[0]

        return self._boms[bom_id]

    def get_boms(
        self,
        bom_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        missing_ids = sorted(
            set(bom_ids) - set(self._boms)
        )

        if missing_ids:
            records = self.client.read(
                model="mrp.bom",
                record_ids=missing_ids,
                fields=self.BOM_FIELDS,
            )

            for record in records:
                self._boms[int(record["id"])] = record

            unresolved_ids = [
                bom_id
                for bom_id in missing_ids
                if bom_id not in self._boms
            ]

            if unresolved_ids:
                raise BomRepositoryError(
                    "Nepavyko nuskaityti BOM ID: "
                    + ", ".join(
                        str(bom_id)
                        for bom_id in unresolved_ids
                    )
                )

        return {
            bom_id: self._boms[bom_id]
            for bom_id in bom_ids
        }

    def get_bom_line(
        self,
        bom_line_id: int,
    ) -> dict[str, Any]:
        if bom_line_id not in self._bom_lines:
            records = self.client.read(
                model="mrp.bom.line",
                record_ids=[bom_line_id],
                fields=self.BOM_LINE_FIELDS,
            )

            if not records:
                raise BomRepositoryError(
                    f"Nepavyko nuskaityti BOM eilutės ID "
                    f"{bom_line_id}"
                )

            self._bom_lines[bom_line_id] = records[0]

        return self._bom_lines[bom_line_id]

    def get_bom_lines(
        self,
        bom_line_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        missing_ids = sorted(
            set(bom_line_ids) - set(self._bom_lines)
        )

        if missing_ids:
            records = self.client.read(
                model="mrp.bom.line",
                record_ids=missing_ids,
                fields=self.BOM_LINE_FIELDS,
            )

            for record in records:
                self._bom_lines[int(record["id"])] = record

            unresolved_ids = [
                bom_line_id
                for bom_line_id in missing_ids
                if bom_line_id not in self._bom_lines
            ]

            if unresolved_ids:
                raise BomRepositoryError(
                    "Nepavyko nuskaityti BOM eilučių ID: "
                    + ", ".join(
                        str(bom_line_id)
                        for bom_line_id in unresolved_ids
                    )
                )

        return {
            bom_line_id: self._bom_lines[bom_line_id]
            for bom_line_id in bom_line_ids
        }

    def find_variant_boms(
        self,
        product_id: int,
    ) -> list[dict[str, Any]]:
        records = self.client.search_read(
            model="mrp.bom",
            domain=[
                ["active", "=", True],
                ["product_id", "=", product_id],
            ],
            fields=self.BOM_FIELDS,
            order="sequence asc, id asc",
        )

        for record in records:
            self._boms[int(record["id"])] = record

        return records

    def find_template_boms(
        self,
        product_tmpl_id: int,
    ) -> list[dict[str, Any]]:
        records = self.client.search_read(
            model="mrp.bom",
            domain=[
                ["active", "=", True],
                ["product_id", "=", False],
                ["product_tmpl_id", "=", product_tmpl_id],
            ],
            fields=self.BOM_FIELDS,
            order="sequence asc, id asc",
        )

        for record in records:
            self._boms[int(record["id"])] = record

        return records

    def clear_cache(self) -> None:
        self._products.clear()
        self._boms.clear()
        self._bom_lines.clear()
