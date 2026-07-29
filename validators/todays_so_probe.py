from datetime import datetime, timedelta, timezone

from core.config import OdooConfig
from core.odoo_client import OdooClient, OdooConnectionError


def main() -> None:
    client = OdooClient(OdooConfig.from_env())

    try:
        client.connect()

        # Lietuva vasarą = UTC+3
        lt = timezone(timedelta(hours=3))

        today_lt = datetime.now(lt).date()

        start_lt = datetime.combine(
            today_lt,
            datetime.min.time(),
            tzinfo=lt,
        )

        end_lt = start_lt + timedelta(days=1)

        start_utc = start_lt.astimezone(timezone.utc)
        end_utc = end_lt.astimezone(timezone.utc)

        print(f"\nTikrinama diena: {today_lt}")
        print(f"UTC intervalas:")
        print(f"  nuo {start_utc}")
        print(f"  iki  {end_utc}")

        sale_orders = client.search_read(
            model="sale.order",
            domain=[
                [
                    "create_date",
                    ">=",
                    start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                ],
                [
                    "create_date",
                    "<",
                    end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                ],
            ],
            fields=[
                "name",
                "state",
                "partner_id",
                "create_date",
                "amount_total",
            ],
            order="create_date asc",
        )

        print(f"\nRasta SO: {len(sale_orders)}")
        print("=" * 130)

        print(
            f"{'SO':<22}"
            f"{'STATE':<15}"
            f"{'CREATED':<22}"
            f"{'CUSTOMER'}"
        )

        print("-" * 130)

        for so in sale_orders:
            partner = so.get("partner_id")

            customer = ""

            if (
                isinstance(partner, (list, tuple))
                and len(partner) > 1
            ):
                customer = partner[1]

            print(
                f"{so.get('name',''):<22}"
                f"{so.get('state',''):<15}"
                f"{so.get('create_date',''):<22}"
                f"{customer}"
            )

    except OdooConnectionError as exc:
        print(exc)


if __name__ == "__main__":
    main()