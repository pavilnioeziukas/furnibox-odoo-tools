from abc import ABC, abstractmethod

from core.odoo_client import OdooClient


class BaseReport(ABC):
    name: str = ""
    description: str = ""

    def __init__(self, client: OdooClient) -> None:
        self.client = client

    @abstractmethod
    def run(self) -> None:
        """Paleidžia ataskaitos generavimą."""
        raise NotImplementedError