"""League scoring: THE place to change how points are awarded.

`points_for` is called both for the live preview in the admin night editor and
when a night is committed, so the preview always matches what gets saved.

Points are stored on each result at commit time. After changing this function,
existing results keep their old points until you re-apply it:
  - admin: LP-sidan → "Räkna om poäng", or
  - CLI:   uv run flask --app damp recalc-points
"""


def points_for(placement: int, table_size: int, wipes: int = 0) -> float:
    """Points for finishing `placement` (1 = winner) at a table of `table_size` players.

    May return decimals (e.g. 14.5); they're stored and shown as-is.

    `wipes` is how many players this player knocked out. It is not used yet,
    but it's passed in so a future rule can reward it.

    Current rule: scales with table size. Last place gets 1 and the winner gets
    `table_size`, e.g. at 8 players: 8, 7, 6, 5, 4, 3, 2, 1.
    """
    bonus = 4 - placement
    bonus = bonus if bonus > 0 else 0
    return table_size - placement + 1 + bonus
