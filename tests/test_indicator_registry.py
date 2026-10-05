"""
tests/test_indicator_registry.py
"""

from indicators.registry import registry
from indicators.rsi import RsiCalculator

def test_registry_contains_rsi():
    assert "rsi" in registry.list_available()
    calc = registry.get_calculator("rsi")
    assert isinstance(calc, RsiCalculator)
    assert calc.name == "rsi"
    assert calc.version == "v1"

def test_registry_bidirectional():
    # REGISTRY -> IMPLEMENTATION
    for name in registry.list_available():
        calc = registry.get_calculator(name)
        assert calc is not None
        # IMPLEMENTATION -> REGISTRY
        assert calc.name == name
