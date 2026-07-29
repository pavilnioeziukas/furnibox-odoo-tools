from core.bom_engine import BomEngine
from core.bom_repository import BomRepository
from core.bom_selector import BomSelector
from core.config import OdooConfig
from core.odoo_client import (
    OdooClient,
    OdooConnectionError,
)
from validators.furnix_po_validator import (
    FurnixPoValidator,
)


SO_NUMBER = "US262126469REG"


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
        engine = BomEngine(
            repository,
            selector,
        )

        validator = FurnixPoValidator(
            client,
            engine,
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

        if result.error:
            print(
                f"Klaida:           "
                f"{result.error}"
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

        print()
        print("=" * 150)

        print(
            f"{'ROW STATUS':<16}"
            f"{'STICKER STATUS':<22}"
            f"{'SKU':<48}"
            f"{'REQUIRED':<12}"
            f"{'PO QTY':<12}"
            f"{'DIFF'}"
        )

        print("-" * 150)

        for row in result.rows:
            print(
                f"{row.status:<16}"
                f"{row.sticker_status:<22}"
                f"{row.sku[:46]:<48}"
                f"{row.required_qty:<12}"
                f"{row.po_qty:<12}"
                f"{row.difference}"
            )

            if row.sticker_error:
                print(
                    f"{'':<16}"
                    f"{'':<22}"
                    f"Sticker klaida: "
                    f"{row.sticker_error}"
                )

        print()
        print("=" * 100)

        if result.status == "PASS":
            print(
                "PO GALIMA TVIRTINTI IR SIŲSTI TIEKĖJUI."
            )
        else:
            print(
                "PO TVIRTINTI NEGALIMA. "
                "PIRMIAUSIA REIKIA IŠTAISYTI KLAIDAS."
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