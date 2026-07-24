from core.config import OdooConfig
from core.odoo_client import OdooClient, OdooConnectionError
from core.report_registry import ReportRegistry
from reports import register_reports


def create_client() -> OdooClient:
    config = OdooConfig.from_env()
    return OdooClient(config)


def test_connection(client: OdooClient) -> None:
    print("\nTikrinamas prisijungimas prie Odoo...")

    try:
        uid = client.connect()
        version = client.common.version()

        print("Prisijungimas sėkmingas.")
        print(f"Vartotojo ID: {uid}")
        print(f"Odoo versija: {version.get('server_version', 'Nežinoma')}")

    except OdooConnectionError as exc:
        print(f"Prisijungimo klaida: {exc}")


def show_reports_menu(registry: ReportRegistry) -> None:
    while True:
        reports = registry.get_reports()

        print("\n====================================")
        print("ATASKAITOS")
        print("====================================")

        for index, report in enumerate(reports, start=1):
            print(f"{index}. {report.name}")

        print("0. Grįžti")

        choice = input("\nPasirinkite ataskaitą: ").strip()

        if choice == "0":
            return

        try:
            selected_index = int(choice) - 1
        except ValueError:
            print("\nNeteisingas pasirinkimas.")
            continue

        if selected_index < 0 or selected_index >= len(reports):
            print("\nNeteisingas pasirinkimas.")
            continue

        try:
            reports[selected_index].run()
        except OdooConnectionError as exc:
            print(f"\nOdoo klaida: {exc}")
        except Exception as exc:
            print(f"\nNenumatyta ataskaitos klaida: {exc}")


def show_main_menu(
    client: OdooClient,
    report_registry: ReportRegistry,
) -> None:
    while True:
        print("\n====================================")
        print("FURNIBOX ODOO TOOLS")
        print("====================================")
        print("1. Tikrinti Odoo prisijungimą")
        print("2. Ataskaitos")
        print("3. Patikros")
        print("4. Importai")
        print("0. Baigti")

        choice = input("\nPasirinkite veiksmą: ").strip()

        if choice == "1":
            test_connection(client)
        elif choice == "2":
            show_reports_menu(report_registry)
        elif choice in {"3", "4"}:
            print("\nŠis meniu punktas dar neįgyvendintas.")
        elif choice == "0":
            print("\nPrograma baigta.")
            return
        else:
            print("\nNeteisingas pasirinkimas.")


def main() -> None:
    try:
        client = create_client()

        report_registry = ReportRegistry(client)
        register_reports(report_registry)

        show_main_menu(client, report_registry)

    except ValueError as exc:
        print(f"\nKonfigūracijos klaida: {exc}")
    except Exception as exc:
        print(f"\nProgramos paleidimo klaida: {exc}")


if __name__ == "__main__":
    main()