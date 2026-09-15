"""Tank height/volume conversions; dimensions in centimetres, volume in litres."""

from math import acos, pi, sqrt

from .model import number

SHAPES = {"rectangle", "vertical_cylinder", "horizontal_cylinder", "sphere", "table"}


def validate_geometry(config, capacity):
    if config.get("shape") not in SHAPES:
        raise ValueError("Unknown tank geometry")
    height = config.get("height_cm")
    if height is not None:
        number(height, positive=True)
    if config["shape"] == "table":
        points = config.get("points", [])
        if not 2 <= len(points) <= 200 or points[0] != [0, 0]:
            raise ValueError("Peiltabelle muss mit 0 cm / 0 L beginnen")
        previous = [-1, -1]
        for point in points:
            if len(point) != 2:
                raise ValueError("Peiltabelle: Höhe und Liter erforderlich")
            for value, old in zip(point, previous, strict=True):
                if number(value) <= old:
                    raise ValueError("Peiltabelle muss streng ansteigen")
            previous = point
        if previous != [height, capacity]:
            raise ValueError(
                "Letzter Tabellenpunkt muss Höhe und Kapazität entsprechen"
            )
    return config


def volume_fraction(shape, height_fraction):
    x = min(1.0, max(0.0, height_fraction))
    if shape == "horizontal_cylinder":
        y = 1 - 2 * x
        return (acos(y) - y * sqrt(max(0, 1 - y * y))) / pi
    if shape == "sphere":
        return x * x * (3 - 2 * x)
    return x


def interpolate(value, points):
    if not points[0][0] <= value <= points[-1][0]:
        raise ValueError("Messung außerhalb der Tankhöhe")
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if value <= x2:
            return y1 + (value - x1) / (x2 - x1) * (y2 - y1)
    return points[-1][1]


def to_liters(value, unit, config, capacity):
    number(value)
    validate_geometry(config, capacity)
    if unit == "L":
        liters = value
    elif unit == "%":
        liters = capacity * value / 100
    elif unit == "cm":
        height = config.get("height_cm")
        if not height or value > height:
            raise ValueError("Tankhöhe fehlt oder Messung liegt außerhalb")
        liters = (
            interpolate(value, config["points"])
            if config["shape"] == "table"
            else capacity * volume_fraction(config["shape"], value / height)
        )
    else:
        raise ValueError("Unbekannte Messeinheit")
    if liters > capacity:
        raise ValueError("Messung über Tankkapazität")
    return liters


def fill_height(liters, config, capacity):
    fraction = min(1, max(0, liters / capacity))
    if config["shape"] == "table":
        return (
            interpolate(fraction * capacity, [[v, h] for h, v in config["points"]])
            / config["height_cm"]
        )
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if volume_fraction(config["shape"], mid) < fraction:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
