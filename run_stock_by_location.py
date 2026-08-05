from core.config import OdooConfig
from core.odoo_client import OdooClient, OdooConnectionError
from reports.stock_by_location import StockByLocationReport


def main() -> int:
    try:
        config = OdooConfig.from_env()
        client = OdooClient(config)

        report = StockByLocationReport(client)
        report.run()

        return 0

    except ValueError as exc:
        print(f"Konfigūracijos klaida: {exc}")
        return 1

    except OdooConnectionError as exc:
        print(f"Odoo klaida: {exc}")
        return 1

    except Exception as exc:
        print(f"Ataskaitos generavimo klaida: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())