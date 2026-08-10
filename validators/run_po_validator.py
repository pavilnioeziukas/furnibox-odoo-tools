from core.bom_engine import BomEngine
from core.bom_repository import BomRepository
from core.bom_selector import BomSelector
from core.config import OdooConfig
from core.dataset_execution_engine import DatasetExecutionEngine
from core.odoo_client import (
    OdooClient,
    OdooConnectionError,
)
from validators.furnix_po_validator import (
    FurnixPoValidator,
)


# Paleidžiant kitam užsakymui keičiamas tik šis numeris.
SO_NUMBER = "DE262627062REG"


def main() -> None:
    client = OdooClient(
        OdooConfig.from_env()
    )

    try:
        client.connect()

        repository = BomRepository(
            client
        )
        selector = BomSelector(
            repository
        )
        odoo_engine = BomEngine(
            repository,
            selector,
        )

        execution_engine = DatasetExecutionEngine(
            client,
            odoo_engine,
            environment="production",
        )

        validator = FurnixPoValidator(
            client,
            execution_engine,
        )

        result = validator.validate(
            SO_NUMBER,
        )

        print()
        print("=" * 100)
        print("FURNIX PO VALIDATION")
        print("=" * 100)

        print(
            f"SO:               "
            f"{result.so_number}"
        )
        print(
            f"PO:               "
            f"{result.po_number}"
        )
        print(
            f"PO būsena:        "
            f"{result.po_state}"
        )
        print(
            f"Tiekėjas:         "
            f"{result.vendor_name}"
        )
        print(
            f"Furnix PO skaičius: "
            f"{result.furnix_po_count}"
        )
        print(
            f"Bendras statusas: "
            f"{result.status}"
        )
        print(
            f"Dataset ID:       "
            f"{result.dataset_id or '-'}"
        )
        print(
            f"Dataset batch:    "
            f"{result.batch_reference or '-'}"
        )
        print(
            f"Odoo fallback:    "
            f"{result.fallback_count}"
        )

        if result.error:
            print(
                f"Klaida:           "
                f"{result.error}"
            )

        if result.warnings:
            print()
            print("PERSPĖJIMAI:")
            for warning in result.warnings:
                print(f"- {warning}")

        if result.fallbacks:
            print()
            print("ODOO BOM FALLBACK:")
            for fallback in result.fallbacks:
                print(
                    "- "
                    f"{fallback.get('root_sku') or '-'}"
                    f" | grupė: {fallback.get('group_name') or '-'}"
                    f" | {fallback.get('reason') or ''}"
                )

        print()
        print(
            f"PASS:             "
            f"{result.pass_count}"
        )
        print(
            f"MISSING:          "
            f"{result.missing_count}"
        )
        print(
            f"EXTRA:            "
            f"{result.extra_count}"
        )
        print(
            f"QTY MISMATCH:     "
            f"{result.qty_mismatch_count}"
        )
        print(
            f"STICKER ERROR:    "
            f"{result.sticker_error_count}"
        )
        print(
            f"SUPPLY ISSUES:    "
            f"{result.supply_issue_count}"
        )

        print()
        print("=" * 220)

        print(
            f"{'ROW STATUS':<16}"
            f"{'STICKER STATUS':<22}"
            f"{'SKU':<48}"
            f"{'REQUIRED':<12}"
            f"{'PO QTY':<12}"
            f"{'RECEIVED':<12}"
            f"{'INPUT':<12}"
            f"{'SORTED':<12}"
            f"{'MO RES.':<12}"
            f"{'SUPPLY STATUS'}"
        )

        print("-" * 220)

        for row in result.rows:
            print(
                f"{row.status:<16}"
                f"{row.sticker_status:<22}"
                f"{row.sku[:46]:<48}"
                f"{row.required_qty:<12}"
                f"{row.po_qty:<12}"
                f"{row.received_qty:<12}"
                f"{row.input_custom_qty:<12}"
                f"{row.sorted_qty:<12}"
                f"{row.mo_reserved_qty:<12}"
                f"{row.supply_status}"
            )

            if row.sticker_error:
                print(
                    f"{'':<16}"
                    f"{'':<22}"
                    f"Sticker klaida: "
                    f"{row.sticker_error}"
                )

            if row.supply_error:
                print(f"{'':<40}Tiekimo priežastis: {row.supply_error}")
            if row.receipt_names or row.sorting_names or row.mo_names:
                print(
                    f"{'':<40}Receipt: {', '.join(row.receipt_names) or '-'}"
                    f" | Sorting: {', '.join(row.sorting_names) or '-'}"
                    f" | MO: {', '.join(row.mo_names) or '-'}"
                )

               print()
        print("=" * 100)

        if result.supply_issue_count == 0:
            print("TIEKIMO / REZERVACIJŲ BŪSENA: nėra neužbaigtų veiksmų sutampantiems SKU.")
        else:
            print(
                "TIEKIMO / REZERVACIJŲ BŪSENA: yra neužbaigtų veiksmų. "
                "Žr. SUPPLY STATUS eilutes."
            )

        if result.status == "PASS":
            print("DUOMENŲ BŪSENA: BOM ir PO sutampa.")
        else:
            print(
                "DUOMENŲ BŪSENA: nustatyti BOM–PO neatitikimai "
                "(MISSING / EXTRA / QTY MISMATCH). Jie vertintini atskirai nuo rezervacijų."
            )

    except OdooConnectionError as exc:
        print(
            f"\nOdoo klaida: {exc}"
        )
    except Exception as exc:
        print(
            f"\nNenumatyta klaida: {exc}"
        )


if __name__ == "__main__":
    main()