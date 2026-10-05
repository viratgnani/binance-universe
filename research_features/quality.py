"""
research_features/quality.py

Quality validation for FeatureRows.
"""

from __future__ import annotations

import math
from typing import Any
from pydantic import BaseModel

from research_features.models import FeatureRow


class ValidationResult(BaseModel):
    is_valid: bool
    violations: list[str]
    missing_data_count: int


class FeatureQualityValidator:
    """
    Validates FeatureRows for impossible values, anomalies, and basic sanity.
    Note: Strict look-ahead validation requires source data arrays, which is
    better done during integration tests, but we can do a sanity check on row data here.
    """
    
    def validate(self, rows: list[FeatureRow]) -> ValidationResult:
        violations: list[str] = []
        missing_count = 0
        
        if not rows:
            return ValidationResult(is_valid=True, violations=[], missing_data_count=0)
            
        # Check sequence
        for i in range(1, len(rows)):
            if rows[i].timestamp <= rows[i-1].timestamp:
                violations.append(f"Out of order or duplicate timestamp at row {i}: {rows[i].timestamp}")
                
        # Check individual rows
        for i, row in enumerate(rows):
            # Count missing data (Nones)
            for k, v in row.model_dump().items():
                if v is None:
                    missing_count += 1
                    
            # Impossible return check
            for ret_field in ["return_1m", "return_5m", "return_15m", "return_1h"]:
                val = getattr(row, ret_field)
                if val is not None:
                    if val < -0.9999 or val > 100.0:  # arbitrary sanity bounds
                        violations.append(f"Impossible return {val} at {row.timestamp}")
                        
            # Negative volatility check
            for vol_field in ["volatility_5m", "volatility_15m", "volatility_1h"]:
                val = getattr(row, vol_field)
                if val is not None and val < 0:
                    violations.append(f"Negative volatility {val} at {row.timestamp}")
                    
            # Negative volume check
            for v_field in ["volume_1m", "volume_5m", "volume_15m", "volume_1h"]:
                val = getattr(row, v_field)
                if val is not None and val < 0:
                    violations.append(f"Negative volume {val} at {row.timestamp}")
                    
            # Order book anomaly check
            best_bid = row.best_bid
            best_ask = row.best_ask
            if best_bid is not None and best_ask is not None:
                if best_bid >= best_ask:
                    violations.append(f"Crossed book: bid {best_bid} >= ask {best_ask} at {row.timestamp}")
                    
            spread = row.spread
            if spread is not None and spread < 0:
                violations.append(f"Negative spread {spread} at {row.timestamp}")
                
            for d_field in ["bid_depth_5", "ask_depth_5", "bid_depth_10", "ask_depth_10", "bid_depth_20", "ask_depth_20"]:
                val = getattr(row, d_field)
                if val is not None and val < 0:
                    violations.append(f"Negative depth {val} at {row.timestamp}")
                    
            for imb_field in ["depth_imbalance_5", "depth_imbalance_10", "depth_imbalance_20"]:
                val = getattr(row, imb_field)
                if val is not None and (val < -1.0 or val > 1.0):
                    violations.append(f"Invalid imbalance {val} at {row.timestamp}")

            # NaN / Inf check
            for k, v in row.model_dump().items():
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    violations.append(f"NaN/Inf in {k} at {row.timestamp}")
                    
        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            missing_data_count=missing_count
        )
