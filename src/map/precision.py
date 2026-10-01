"""Precision of derived longitude/latitude products, never source coordinates."""
from __future__ import annotations

import math

WGS84_DECIMAL_PLACES = 9


def wgs84_coordinates(value):
    """Round derived degrees to 1e-9 (about 0.11 mm at the equator).

    The maximum per-axis rounding is half that grid. This is a serialization
    tolerance, not a claim of source accuracy. Handle scalar and vector PROJ
    results because Shapely uses both forms of its transform callback.
    """
    if isinstance(value, (tuple, list)):
        return [wgs84_coordinates(item) for item in value]
    if not math.isfinite(value):
        raise ValueError('Non-finite projected longitude/latitude')
    rounded = round(float(value), WGS84_DECIMAL_PLACES)
    return 0.0 if rounded == 0 else rounded
