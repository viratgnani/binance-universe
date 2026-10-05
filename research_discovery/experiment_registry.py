"""
research_discovery/experiment_registry.py

File-backed registry for discovery experiments.
Prevents multiple testing amnesia by recording intent (exploratory vs confirmatory)
before the experiment is run.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from market_data.config import MarketDataConfig, config as default_config
from research_discovery.models import DiscoverySpec, ExperimentRegistryEntry, ExperimentStatus

logger = logging.getLogger(__name__)


class ExperimentRegistry:
    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self.registry_dir = Path(cfg.OHLCV_DIR).parent / "discovery_experiments"
        self.registry_file = self.registry_dir / "registry.jsonl"
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def register(self, spec: DiscoverySpec) -> ExperimentRegistryEntry:
        """
        Register a new experiment.
        Raises ValueError if experiment_id already exists.
        """
        existing = self.get_entry(spec.experiment_id)
        if existing:
            raise ValueError(f"Experiment ID '{spec.experiment_id}' is already registered.")

        entry = ExperimentRegistryEntry(
            experiment_id=spec.experiment_id,
            status=ExperimentStatus.REGISTERED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            spec_summary={
                "description": spec.description,
                "universe_name": spec.universe_name,
                "dataset_period": spec.dataset_period,
                "is_exploratory": spec.is_exploratory,
                "hypotheses_count": spec.hypotheses_count,
            }
        )
        self._append_entry(entry)
        return entry

    def update_status(self, experiment_id: str, status: ExperimentStatus) -> None:
        """
        Update the status of an existing experiment.
        """
        entries = self.list_entries()
        updated = False
        
        for entry in entries:
            if entry.experiment_id == experiment_id:
                entry.status = status
                entry.updated_at = datetime.now(timezone.utc)
                updated = True
                break
                
        if not updated:
            raise ValueError(f"Experiment ID '{experiment_id}' not found.")
            
        # Rewrite the entire file (it's small)
        self._write_all(entries)

    def get_entry(self, experiment_id: str) -> ExperimentRegistryEntry | None:
        for entry in self.list_entries():
            if entry.experiment_id == experiment_id:
                return entry
        return None

    def list_entries(self) -> list[ExperimentRegistryEntry]:
        if not self.registry_file.exists():
            return []
            
        entries = []
        with self.registry_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(ExperimentRegistryEntry.model_validate_json(line))
                except ValidationError as e:
                    logger.error("Failed to parse registry entry: %s", e)
        return entries

    def _append_entry(self, entry: ExperimentRegistryEntry) -> None:
        with self.registry_file.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def _write_all(self, entries: list[ExperimentRegistryEntry]) -> None:
        with self.registry_file.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(entry.model_dump_json() + "\n")
