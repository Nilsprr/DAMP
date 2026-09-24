"""League scoring: THE place to change how points are awarded.

The admin runs in the browser, so it can't call Python. Instead the build turns
`points_for` into a lookup table (`points_table`, served as /admin/poang.json)
and the table editor reads both its preview and the points it saves from that
table. The preview therefore always matches what gets saved, and this function
stays the only definition of the rules.

Points are stored in each table file when it is saved. After changing this
function (and deploying), existing tables keep their old points until you
re-apply it:
  - admin: LP-sidan → "Räkna om poäng", or
  - CLI:   uv run flask --app damp recalc-points
"""

MAX_TABLE_SIZE = 30  # largest table the admin can score


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
    return table_size - placement + 1 + bonus + wipes   #wipes alltid 0 just nu


def points_table(max_size: int = MAX_TABLE_SIZE) -> dict[str, list[list[float]]]:
    """`points_for` for every table size, placement and wipe count the admin can enter.

    table[str(size)][placement - 1][wipes], for sizes 2..max_size and wipes 0..size-1.
    """
    return {
        str(size): [[points_for(placement, size, wipes) for wipes in range(size)] for placement in range(1, size + 1)]
        for size in range(2, max_size + 1)
    }
