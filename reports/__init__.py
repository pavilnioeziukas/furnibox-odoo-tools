from core.report_registry import ReportRegistry
from reports.category_load import CategoryLoadReport
from reports.furnix_po_validation_report import (
    FurnixPoValidationReport,
)
from reports.so_po_arrival import SoPoArrivalReport
from reports.stock_by_location import StockByLocationReport
from reports.work_center_diagnostics import (
    WorkCenterDiagnostics,
)
from reports.work_center_load import WorkCenterLoadReport


def register_reports(
    registry: ReportRegistry,
) -> None:
    registry.register(SoPoArrivalReport)
    registry.register(WorkCenterDiagnostics)
    registry.register(WorkCenterLoadReport)
    registry.register(CategoryLoadReport)
    registry.register(FurnixPoValidationReport)
    registry.register(StockByLocationReport)