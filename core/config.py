import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class OdooConfig:
    url: str
    database: str
    username: str
    api_key: str

    @classmethod
    def from_env(cls) -> "OdooConfig":
        config = cls(
            url=os.getenv("ODOO_URL", "").strip().rstrip("/"),
            database=os.getenv("ODOO_DATABASE", "").strip(),
            username=os.getenv("ODOO_USERNAME", "").strip(),
            api_key=os.getenv("ODOO_API_KEY", "").strip(),
        )

        missing = [
            name
            for name, value in {
                "ODOO_URL": config.url,
                "ODOO_DATABASE": config.database,
                "ODOO_USERNAME": config.username,
                "ODOO_API_KEY": config.api_key,
            }.items()
            if not value
        ]

        if missing:
            raise ValueError(
                "Trūksta .env parametrų: " + ", ".join(missing)
            )

        return config