from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


load_dotenv()


class ValidatedDatasetRepositoryError(RuntimeError):
    """Nepavyko rasti arba nuskaityti Validated Product Dataset."""


@dataclass(frozen=True)
class DatasetProduct:
    sku: str
    product_type: str
    bom_type: str
    level: int
    source_sku: str
    generated_from: str
    reform_category: str
    content_hash: str
    content_signature: str
    components: list[dict[str, Any]]
    operations: list[dict[str, Any]]


@dataclass(frozen=True)
class ValidatedDataset:
    schema_version: str
    dataset_id: str
    batch_reference: str
    environment: str
    created_at_utc: str
    source: dict[str, Any]
    statistics: dict[str, Any]
    products: list[DatasetProduct]

    def find_product(
        self,
        sku: str,
    ) -> DatasetProduct | None:
        normalized_sku = str(
            sku or ""
        ).strip().upper()

        if not normalized_sku:
            raise ValidatedDatasetRepositoryError(
                "Nenurodytas produkto SKU."
            )

        matches = [
            product
            for product in self.products
            if product.sku.strip().upper()
            == normalized_sku
        ]

        if not matches:
            return None

        if len(matches) > 1:
            raise ValidatedDatasetRepositoryError(
                "Dataset turi kelis produktus tuo pačiu SKU: "
                f"{normalized_sku}"
            )

        return matches[0]


class ValidatedDatasetRepository:
    def __init__(
        self,
        shared_root: Path | None = None,
    ) -> None:
        self.shared_root = (
            shared_root.resolve()
            if shared_root is not None
            else self._shared_data_root()
        )

    def environment_directory(
        self,
        environment: str,
    ) -> Path:
        normalized_environment = (
            self._normalize_environment(
                environment
            )
        )

        return (
            self.shared_root
            / "validated_datasets"
            / normalized_environment
        )

    def latest_path(
        self,
        environment: str,
    ) -> Path:
        return (
            self.environment_directory(
                environment
            )
            / "latest.json"
        )

    def load_latest(
        self,
        environment: str,
    ) -> ValidatedDataset:
        path = self.latest_path(
            environment
        )

        return self.load_file(path)

    def load_file(
        self,
        path: Path,
    ) -> ValidatedDataset:
        resolved_path = path.resolve()

        if not resolved_path.exists():
            raise ValidatedDatasetRepositoryError(
                "Dataset failas nerastas: "
                f"{resolved_path}"
            )

        try:
            raw_data = json.loads(
                resolved_path.read_text(
                    encoding="utf-8"
                )
            )
        except json.JSONDecodeError as exc:
            raise ValidatedDatasetRepositoryError(
                "Neteisingas Dataset JSON: "
                f"{resolved_path}: {exc}"
            ) from exc
        except OSError as exc:
            raise ValidatedDatasetRepositoryError(
                "Nepavyko nuskaityti Dataset: "
                f"{resolved_path}: {exc}"
            ) from exc

        self._validate_root(
            raw_data,
            resolved_path,
        )

        products = [
            self._build_product(product_data)
            for product_data in raw_data["products"]
        ]

        duplicate_skus = sorted(
            sku
            for sku in {
                product.sku.upper()
                for product in products
            }
            if sum(
                product.sku.upper() == sku
                for product in products
            ) > 1
        )

        if duplicate_skus:
            raise ValidatedDatasetRepositoryError(
                "Dataset kartojasi produktų SKU: "
                + ", ".join(duplicate_skus)
            )

        return ValidatedDataset(
            schema_version=str(
                raw_data["schema_version"]
            ),
            dataset_id=str(
                raw_data["dataset_id"]
            ),
            batch_reference=str(
                raw_data["batch_reference"]
            ),
            environment=str(
                raw_data["environment"]
            ).strip().lower(),
            created_at_utc=str(
                raw_data["created_at_utc"]
            ),
            source=dict(
                raw_data.get("source") or {}
            ),
            statistics=dict(
                raw_data.get("statistics") or {}
            ),
            products=products,
        )

    @staticmethod
    def _build_product(
        data: dict[str, Any],
    ) -> DatasetProduct:
        if not isinstance(data, dict):
            raise ValidatedDatasetRepositoryError(
                "Dataset produkto įrašas nėra JSON objektas."
            )

        sku = str(
            data.get("sku") or ""
        ).strip()

        if not sku:
            raise ValidatedDatasetRepositoryError(
                "Dataset produktas neturi SKU."
            )

        components = data.get(
            "components",
            [],
        )

        operations = data.get(
            "operations",
            [],
        )

        if not isinstance(components, list):
            raise ValidatedDatasetRepositoryError(
                f"Produkto {sku} components nėra sąrašas."
            )

        if not isinstance(operations, list):
            raise ValidatedDatasetRepositoryError(
                f"Produkto {sku} operations nėra sąrašas."
            )

        return DatasetProduct(
            sku=sku,
            product_type=str(
                data.get("product_type") or ""
            ),
            bom_type=str(
                data.get("bom_type") or ""
            ),
            level=int(
                data.get("level") or 0
            ),
            source_sku=str(
                data.get("source_sku") or ""
            ),
            generated_from=str(
                data.get("generated_from") or ""
            ),
            reform_category=str(
                data.get("reform_category") or ""
            ),
            content_hash=str(
                data.get("content_hash") or ""
            ),
            content_signature=str(
                data.get("content_signature") or ""
            ),
            components=[
                dict(component)
                for component in components
            ],
            operations=[
                dict(operation)
                for operation in operations
            ],
        )

    @staticmethod
    def _validate_root(
        data: Any,
        path: Path,
    ) -> None:
        if not isinstance(data, dict):
            raise ValidatedDatasetRepositoryError(
                "Dataset šaknis nėra JSON objektas: "
                f"{path}"
            )

        required_fields = [
            "schema_version",
            "dataset_id",
            "batch_reference",
            "environment",
            "created_at_utc",
            "source",
            "statistics",
            "products",
        ]

        missing_fields = [
            field
            for field in required_fields
            if field not in data
        ]

        if missing_fields:
            raise ValidatedDatasetRepositoryError(
                "Dataset trūksta laukų "
                f"{missing_fields}: {path}"
            )

        if not isinstance(
            data.get("products"),
            list,
        ):
            raise ValidatedDatasetRepositoryError(
                f"Dataset products nėra sąrašas: {path}"
            )

    @staticmethod
    def _shared_data_root() -> Path:
        raw_path = os.getenv(
            "FURNIBOX_SHARED_DATA",
            "",
        ).strip()

        if not raw_path:
            raise ValidatedDatasetRepositoryError(
                "Nenustatytas FURNIBOX_SHARED_DATA. "
                "Įrašyk bendro Furnibox duomenų katalogo "
                "kelią į .env."
            )

        return Path(
            raw_path
        ).expanduser().resolve()

    @staticmethod
    def _normalize_environment(
        environment: str,
    ) -> str:
        normalized = str(
            environment or ""
        ).strip().lower()

        if normalized == "prod":
            normalized = "production"

        if normalized not in {
            "stage",
            "production",
        }:
            raise ValidatedDatasetRepositoryError(
                f"Neleistina aplinka: {environment!r}"
            )

        return normalized