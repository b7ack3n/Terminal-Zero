"""Define, save, and materialise a room over the store.

    python scripts/room_demo.py

A room is just a saved manifest; materialising it queries the shared store.
This proves the substrate the visualiser and gen-AI head will stand on.
"""

from terminal_zero import geo, room
from terminal_zero.store import connect


def main() -> None:
    conn = connect()

    # Define a room: the US + state semiconductor-manufacturing slice, 2019-2024.
    definition = room.RoomDefinition(
        name="US Semiconductor Manufacturing 2019-2024",
        subject_ids=["NAICS:334413"],
        sources=["bls-qcew"],
        year_start=2019,
        year_end=2024,
        note="Semiconductor & Related Device Manufacturing (NAICS 334413), QCEW.",
    )
    room.save(conn, definition)
    print(f"saved rooms: {room.list_rooms(conn)}")

    # Coverage — what the room actually contains (honesty first).
    s = room.summary(conn, definition)
    print("\n=== room coverage ===")
    for k, v in s.items():
        print(f"  {k:<14}: {v}")

    # Materialise and show the US employment series pulled from the room.
    rows = room.materialise(conn, definition)
    print(f"\n=== materialised {len(rows)} observations ===")
    print("US employment over time (from the room):")
    for r in rows:
        if r["geo"] == "US" and r["concept"] == "annual_avg_emplvl":
            print(f"  {r['fiscal_year']}  {r['value']:>10,.0f} employees "
                  f"[{r['source']}]")

    # A room overlaps freely with a narrower one — same store, no copy.
    latest = room.RoomDefinition(
        name="Semiconductors — states, 2024 employment",
        subject_ids=["NAICS:334413"],
        concepts=["annual_avg_emplvl"],
        year_start=2024, year_end=2024,
    )
    top = [r for r in room.materialise(conn, latest) if r["geo"].startswith("STATE:")]
    top.sort(key=lambda r: r["value"], reverse=True)
    print("\ntop 5 states, 2024 (a second, overlapping room):")
    for r in top[:5]:
        print(f"  {geo.label(r['geo']):<16}{r['value']:>10,.0f}")


if __name__ == "__main__":
    main()
