import re
from dataclasses import dataclass


DIMENSION_PATTERN = re.compile(
    r"(?<!\d)\d+(?:[.,]\d+)?x\d+(?:[.,]\d+)?(?!\d)",
    re.IGNORECASE,
)

DETAIL_TYPES = (
    "SINKSTIFFENER",
    "SIDESINKL",
    "SIDESINKR",
    "WALLSIDE",
    "STIFFENER",
    "TOPSIDE",
    "CUTBACK",
    "BOTVEN",
    "TOPVEN",
    "SHELF",
    "SIDE",
    "BACK",
    "BOT",
    "TOP",
)


@dataclass(frozen=True)
class FurnixPartClassification:
    is_furnix_detail: bool
    rule: str
    normalized_sku: str
    has_dimensions: bool
    detail_type: str


class FurnixPartClassifier:
    """Atpažįsta Furnix plokštines detales pagal SKU struktūrą."""

    @staticmethod
    def normalize_sku(
        sku: str | None,
    ) -> str:
        return str(sku or "").strip().upper()

    @classmethod
    def has_dimensions(
        cls,
        sku: str | None,
    ) -> bool:
        normalized = cls.normalize_sku(sku)

        return bool(
            DIMENSION_PATTERN.search(normalized)
        )

    @classmethod
    def detect_detail_type(
        cls,
        sku: str | None,
    ) -> str:
        normalized = cls.normalize_sku(sku)

        for detail_type in DETAIL_TYPES:
            if detail_type in normalized:
                return detail_type

        if "-PNL-" in normalized:
            return "PNL"

        return ""

    @classmethod
    def classify(
        cls,
        sku: str | None,
    ) -> FurnixPartClassification:
        normalized = cls.normalize_sku(sku)
        has_dimensions = cls.has_dimensions(
            normalized
        )
        detail_type = cls.detect_detail_type(
            normalized
        )

        if (
            "SREW" in normalized
            and has_dimensions
        ):
            return FurnixPartClassification(
                is_furnix_detail=True,
                rule="SREW + dimensions",
                normalized_sku=normalized,
                has_dimensions=True,
                detail_type=detail_type,
            )

        if (
            "-PNL-" in normalized
            and has_dimensions
        ):
            return FurnixPartClassification(
                is_furnix_detail=True,
                rule="PNL + dimensions",
                normalized_sku=normalized,
                has_dimensions=True,
                detail_type="PNL",
            )

        return FurnixPartClassification(
            is_furnix_detail=False,
            rule="No Furnix detail rule matched",
            normalized_sku=normalized,
            has_dimensions=has_dimensions,
            detail_type=detail_type,
        )

    @classmethod
    def is_furnix_detail(
        cls,
        sku: str | None,
    ) -> bool:
        return cls.classify(
            sku
        ).is_furnix_detail

    @classmethod
    def classification_reason(
        cls,
        sku: str | None,
    ) -> str:
        return cls.classify(
            sku
        ).rule