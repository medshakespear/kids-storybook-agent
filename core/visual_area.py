"""Shared size rules for single illustrations and substantial multi-panel artwork."""


def sufficient_visual_area(areas: list[float], minimum: float) -> bool:
    """Require total artwork plus a dominant visual or 2-4 substantial panels."""
    if not areas or sum(areas) + .01 < minimum:
        return False
    if max(areas) + .01 >= minimum * .55:
        return True
    # Multiple comparison, sequencing or sorting panels need equal prominence.
    # Tiny icon collections cannot satisfy this alternative.
    return 2 <= len(areas) <= 4 and min(areas) + .01 >= minimum * .75 / len(areas)
