"""Deterministic design inputs shared across kernel, validation, export and E2E.

All cylinders extend along +Z. Setting/prong additions edit the supplied body;
the returned ref remains usable. These helpers call production, not a fake CAD.
"""
SETTING = {'center': [10.0, 0.0], 'radius': 1.5, 'base_z': 1.8, 'height': 1.2}
PRONGS = {'center': [10.0, 0.0], 'orbit_radius': 1.0, 'base_z': 2.8,
          'height': 2.0, 'count': 4, 'start_angle_degrees': 0.0}
PRONG_CENTERS = [[11.0,0.0], [10.0,1.0], [9.0,0.0], [10.0,-1.0]]
SEAT = {'center': [10.0,0.0], 'radius': 0.65, 'depth': 0.5, 'top_z': 3.0}
HOLE = {'center': [-8.75,0.0], 'radius': 0.2}


def ring_with_setting(case, prong_diameter=0.8, seat=False, hole=False):
    ref = case.ring()
    ref = case.ok('add_setting', ref=ref, **SETTING)['ref']
    if seat:
        ref = case.ok('cut_recess', ref=ref, **SEAT)['ref']
    ref = case.ok('repeat_prongs', ref=ref, diameter=prong_diameter, **PRONGS)['ref']
    if hole:
        ref = case.ok('cut_through_hole', ref=ref, **HOLE)['ref']
    return ref
