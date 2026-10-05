"""
research_discovery/discovery_runner.py

Orchestration layer that bridges the discovery inputs with the frozen ResearchEngine.
"""

from __future__ import annotations

import logging
from typing import Any

from market_data.config import MarketDataConfig, config as default_config
from research.research_runner import ResearchRunner
from research_discovery.data_adapter import DiscoveryDataAdapter
from research_discovery.experiment_registry import ExperimentRegistry
from research_discovery.models import DiscoverySpec, ExperimentStatus

logger = logging.getLogger(__name__)


class DiscoveryRunner:
    """
    Executes a DiscoverySpec using the frozen ResearchRunner.
    Ensures registration and correct data routing.
    """

    def __init__(self, cfg: MarketDataConfig = default_config) -> None:
        self.cfg = cfg
        self.registry = ExperimentRegistry(cfg)
        self.data_adapter = DiscoveryDataAdapter(cfg)
        # Inject the discovery data adapter into the frozen runner
        self.frozen_runner = ResearchRunner(cfg, data_adapter=self.data_adapter)

    def run(self, spec: DiscoverySpec, compute_statistics: bool = True, group_by: list[str] | None = None) -> tuple[list[Any], list[Any]]:
        """
        Register and run the discovery experiment.
        """
        logger.info("DiscoveryRunner: Starting experiment %s", spec.experiment_id)
        
        # 1. Registration
        try:
            self.registry.register(spec)
        except ValueError as e:
            logger.error("Registration failed: %s", e)
            raise

        self.registry.update_status(spec.experiment_id, ExperimentStatus.RUNNING)

        # 2. Execution (delegated to frozen runner)
        try:
            # The frozen runner expects a ResearchSpec, which is embedded inside DiscoverySpec
            results, stats = self.frozen_runner.run(
                spec=spec.research_spec,
                compute_statistics=compute_statistics,
                group_by=group_by,
            )
            
            # 3. Success
            self.registry.update_status(spec.experiment_id, ExperimentStatus.COMPLETE)
            logger.info("DiscoveryRunner: Experiment %s COMPLETE.", spec.experiment_id)
            return results, stats

        except Exception as e:
            # 4. Failure
            self.registry.update_status(spec.experiment_id, ExperimentStatus.FAILED)
            logger.error("DiscoveryRunner: Experiment %s FAILED: %s", spec.experiment_id, e)
            raise
