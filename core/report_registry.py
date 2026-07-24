from core.odoo_client import OdooClient
from core.report_base import BaseReport


class ReportRegistry:
    def __init__(self, client: OdooClient) -> None:
        self.client = client
        self._report_classes: list[type[BaseReport]] = []

    def register(self, report_class: type[BaseReport]) -> None:
        if report_class in self._report_classes:
            return

        self._report_classes.append(report_class)

    def get_reports(self) -> list[BaseReport]:
        return [
            report_class(self.client)
            for report_class in self._report_classes
        ]