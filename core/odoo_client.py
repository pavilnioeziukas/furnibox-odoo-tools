import xmlrpc.client
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import OdooConfig


class OdooConnectionError(Exception):
    """Klaida jungiantis prie Odoo."""


class OdooReadOnlyError(Exception):
    """Bandymas per tik skaitymui skirtą klientą keisti Odoo duomenis."""


class OdooClient:
    ALLOWED_METHODS = frozenset({"fields_get", "read", "search", "search_read"})

    def __init__(self, config: "OdooConfig") -> None:
        self.config = config
        self.uid: int | None = None

        self.common = xmlrpc.client.ServerProxy(
            f"{self.config.url}/xmlrpc/2/common",
            allow_none=True,
        )

        self.models = xmlrpc.client.ServerProxy(
            f"{self.config.url}/xmlrpc/2/object",
            allow_none=True,
        )

    def connect(self) -> int:
        try:
            uid = self.common.authenticate(
                self.config.database,
                self.config.username,
                self.config.api_key,
                {},
            )
        except Exception as exc:
            raise OdooConnectionError(
                f"Nepavyko pasiekti Odoo serverio: {exc}"
            ) from exc

        if not uid:
            raise OdooConnectionError(
                "Odoo atmetė prisijungimą. Patikrink database, username ir API raktą."
            )

        self.uid = int(uid)
        return self.uid

    def _ensure_connected(self) -> int:
        if self.uid is None:
            return self.connect()

        return self.uid

    def execute(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        if method not in self.ALLOWED_METHODS:
            raise OdooReadOnlyError(
                f"Odoo metodas '{method}' neleidžiamas tik skaitymo režime."
            )

        uid = self._ensure_connected()

        try:
            return self.models.execute_kw(
                self.config.database,
                uid,
                self.config.api_key,
                model,
                method,
                args or [],
                kwargs or {},
            )
        except Exception as exc:
            raise OdooConnectionError(
                f"Odoo užklausa nepavyko: {model}.{method}: {exc}"
            ) from exc

    def search(
        self,
        model: str,
        domain: list[Any],
        *,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[int]:
        kwargs: dict[str, Any] = {}

        if limit is not None:
            kwargs["limit"] = limit

        if order:
            kwargs["order"] = order

        return self.execute(
            model=model,
            method="search",
            args=[domain],
            kwargs=kwargs,
        )

    def read(
        self,
        model: str,
        record_ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}

        if fields:
            kwargs["fields"] = fields

        return self.execute(
            model=model,
            method="read",
            args=[record_ids],
            kwargs=kwargs,
        )

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        *,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {}

        if fields:
            kwargs["fields"] = fields

        if limit is not None:
            kwargs["limit"] = limit

        if order:
            kwargs["order"] = order

        return self.execute(
            model=model,
            method="search_read",
            args=[domain],
            kwargs=kwargs,
        )