from core.report_registry import ReportRegistry
from reports.so_po_arrival import SoPoArrivalReport


def register_reports(registry: ReportRegistry) -> None:
    registry.register(SoPoArrivalReport)