"""
market_data/ob_quality.py

Generates quality reports for Order Book V2 ingestion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from market_data.ob_manager import OrderBookManager

logger = logging.getLogger(__name__)


@dataclass
class OBQualityReport:
    symbols_requested: int
    symbols_synchronized: int
    symbols_failed: int
    total_events: int
    total_checkpoints: int
    total_gaps: int
    total_resyncs: int
    total_invalid: int
    total_crossed: int
    duration_sec: float
    details: dict[str, Any]

    def print_report(self) -> None:
        print("\n============================================================")
        print("MARKET DATA V2 FINAL REPORT")
        print(f"\nDuration: {self.duration_sec:.1f}s")
        print(f"\nSymbols requested    : {self.symbols_requested}")
        print(f"Symbols synchronized : {self.symbols_synchronized}")
        print(f"Symbols failed       : {self.symbols_failed}")
        print(f"\nRaw events captured  : {self.total_events}")
        print(f"Checkpoints captured : {self.total_checkpoints}")
        print(f"\nSequence gaps          : {self.total_gaps}")
        print(f"Resynchronizations     : {self.total_resyncs}")
        print(f"Invalid updates        : {self.total_invalid}")
        print(f"Crossed-book anomalies : {self.total_crossed}")
        print("\nSymbol Details:")
        for sym, det in self.details.items():
            safe_sym = str(sym).encode('ascii', 'replace').decode('ascii')
            sync_str = "PASS" if det["synchronized"] else "FAIL"
            print(f"  {safe_sym} synchronization: {sync_str}")
            if det["resyncs"] > 0 or det["gaps"] > 0:
                print(f"    -> Resyncs: {det['resyncs']}, Gaps: {det['gaps']}, Events: {det['events']}")
        
        status = "PRODUCTION READY" if self.symbols_failed == 0 and self.total_resyncs == 0 else "NEEDS INVESTIGATION"
        print(f"\nOverall:\n{status}")
        print("============================================================\n")


def generate_ob_quality_report(
    manager: OrderBookManager,
    duration_sec: float,
    total_checkpoints_written: int,
) -> OBQualityReport:
    """
    Generates a report from the active manager state.
    """
    total_events = 0
    total_gaps = 0
    total_resyncs = 0
    total_invalid = 0
    total_crossed = 0
    
    details: dict[str, Any] = {}
    
    symbols_synchronized = 0
    
    for symbol, sync_mgr in manager.sync_managers.items():
        sym_events = sync_mgr.events_processed
        sym_resyncs = sync_mgr.resync_count
        
        sym_gaps = sum(1 for v in sync_mgr.violations_history if v.violation_type == "SEQUENCE_GAP")
        sym_inv = sum(1 for v in sync_mgr.violations_history if v.violation_type in ("INVALID_PRICE", "INVALID_QTY"))
        sym_cross = sum(1 for v in sync_mgr.violations_history if v.violation_type == "CROSSED_BOOK")
        
        total_events += sym_events
        total_resyncs += sym_resyncs
        total_gaps += sym_gaps
        total_invalid += sym_inv
        total_crossed += sym_cross
        
        is_synced = sync_mgr.local_book.synchronized
        if is_synced:
            symbols_synchronized += 1
            
        details[symbol] = {
            "synchronized": is_synced,
            "events": sym_events,
            "resyncs": sym_resyncs,
            "gaps": sym_gaps,
            "invalid": sym_inv,
            "crossed": sym_cross,
        }
        
    symbols_requested = len(manager.symbols)
    symbols_failed = symbols_requested - symbols_synchronized
    
    return OBQualityReport(
        symbols_requested=symbols_requested,
        symbols_synchronized=symbols_synchronized,
        symbols_failed=symbols_failed,
        total_events=total_events,
        total_checkpoints=total_checkpoints_written,
        total_gaps=total_gaps,
        total_resyncs=total_resyncs,
        total_invalid=total_invalid,
        total_crossed=total_crossed,
        duration_sec=duration_sec,
        details=details,
    )
