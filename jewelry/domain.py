"""Jewelry domain operations.

These calls are the jewelry compatibility layer. The generic ``cad`` package
does not import this module. Ring, setting, recess, and prong construction stay
on the analytic kernel so the existing jewelry contract keeps its exact results.
"""

from __future__ import annotations


JEWELRY_OPERATIONS = (
    "create_ring",
    "modify_ring",
    "cut_through_hole",
    "cut_recess",
    "add_setting",
    "repeat_prongs",
)


def create_ring(kernel, inner_radius, outer_radius, width):
    return kernel.create_ring(inner_radius, outer_radius, width)


def modify_ring(kernel, body, arguments):
    return kernel.modify_ring(body, arguments)


def cut_through_hole(kernel, body, center, radius):
    return kernel.cut_through_hole(body, center, radius)


def cut_recess(kernel, body, center, radius, top_z, depth):
    return kernel.cut_recess(body, center, radius, top_z, depth)


def add_setting(kernel, body, center, radius, base_z, height):
    return kernel.add_setting(body, center, radius, base_z, height)


def repeat_prongs(kernel, body, center, orbit_radius, diameter, base_z, height, count, start_angle_degrees):
    return kernel.repeat_prongs(
        body, center, orbit_radius, diameter, base_z, height, count, start_angle_degrees,
    )
