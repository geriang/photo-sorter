def classify(has_people: int | None, blur_ok: bool = True) -> tuple[str, float, str]:
    """Minimal default scoring: returns (type, score, reason).

    Placeholder for Milestone 4. Blur and duplicate signals are not wired in yet,
    so the score only reflects whether the photo contains people.
    """
    if has_people:
        return "people", 0.8, "keep: contains people"
    return "misc", 0.5, "maybe: no people detected"


def apply_default_scoring(conn, keep_above: float = 0.7, toss_below: float = 0.3) -> int:
    rows = conn.execute("SELECT sha256, has_people FROM photos").fetchall()
    for row in rows:
        ptype, score, reason = classify(row["has_people"])
        value = "keep" if score > keep_above else "toss" if score < toss_below else "maybe"
        conn.execute(
            "UPDATE photos SET type = ?, value = ?, score = ?, reason = ? WHERE sha256 = ?",
            (ptype, value, score, reason, row["sha256"]),
        )
    conn.commit()
    return len(rows)
