"""Tiny monocular spatial hints: bearing from image x, distance from box size."""
from mischief_common.object_geometry import enrich_spatial


def enrich(obj, hfov_deg=130.0):
    return enrich_spatial(obj, hfov_deg)
