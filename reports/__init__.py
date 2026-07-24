from core.report_registry import ReportRegistry
from reports.so_po_arrival import SoPoArrivalReport
from reports.work_center_diagnostics import WorkCenterDiagnostics
from reports.work_center_load import WorkCenterLoadReport


def register_reports(registry: ReportRegistry) -> None:
    registry.register(SoPoArrivalReport)
    registry.register(WorkCenterDiagnostics)
    registry.register(WorkCenterLoadReport)