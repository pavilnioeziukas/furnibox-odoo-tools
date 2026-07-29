from __future__ import annotations

from typing import Any, Protocol

from core.bom_engine import BomEngine


class BomProviderError(RuntimeError):
    """Nepavyko gauti arba išskleisti SO BOM duomenų."""


class BomProvider(Protocol):
    """BOM duomenų šaltinio sąsaja PO validatoriui."""

    def explode_sales_order(
        self,
        so_number: str,
    ) -> Any:
        """Išskleidžia vieno SO BOM ir grąžina suderinamą rezultatą."""
        ...


class OdooBomProvider:
    """Dabartinis BOM šaltinis, naudojantis Odoo BomEngine."""

    def __init__(
        self,
        bom_engine: BomEngine,
    ) -> None:
        self.bom_engine = bom_engine

    def explode_sales_order(
        self,
        so_number: str,
    ) -> Any:
        normalized_so_number = str(
            so_number or ""
        ).strip()

        if not normalized_so_number:
            raise BomProviderError(
                "Nenurodytas SO numeris."
            )

        try:
            return self.bom_engine.explode_sales_order(
                normalized_so_number,
                only_grouped_lines=True,
            )
        except Exception as exc:
            raise BomProviderError(
                "Nepavyko išskleisti SO BOM per Odoo: "
                f"{normalized_so_number}: {exc}"
            ) from exc