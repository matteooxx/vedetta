"""Faceted filtering for the postings list.

Several values may be selected per facet — two locations, four employers — and each
facet's own options are counted **as if that facet were not filtered**. That is the
standard behaviour of a good filter panel and the reason it is worth building
properly: if picking Ireland made every other place read zero, you could never tell
whether Poland had anything until you had already given up on Ireland.

Everything lives in the query string, so a filtered view is a URL that can be
bookmarked, shared or reopened.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# facet name -> (query parameter, SQL fragment template)
# Each fragment is written to accept a list of values.
FACETS = ("employer", "place", "skill", "label", "triage", "mode", "age")

AGE_DAYS = {"24h": 1, "3d": 3, "7d": 7, "30d": 30}
AGE_LABELS = {"24h": "Last 24 hours", "3d": "Last 3 days",
              "7d": "Last 7 days", "30d": "Last 30 days"}
MODE_LABELS = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On site"}
def _triage_labels() -> dict:
    """Labels come from the stage ladder, so the facet cannot drift from it."""
    from .triage import STAGES
    labels = {s.key: s.label for s in STAGES}
    labels["none"] = "Not triaged"
    return labels


TRIAGE_LABELS = _triage_labels()


@dataclass
class Selection:
    """What the reader has chosen. Lists, because facets are multi-select."""
    scope: str = "workable"           # workable | excluded | all
    state: str = "open"               # open | closed | all
    q: str = ""
    employer: list[str] = field(default_factory=list)
    place: list[str] = field(default_factory=list)
    label: list[str] = field(default_factory=list)
    triage: list[str] = field(default_factory=list)
    skill: list[str] = field(default_factory=list)
    mode: list[str] = field(default_factory=list)
    age: list[str] = field(default_factory=list)

    @classmethod
    def from_request(cls, args) -> "Selection":
        return cls(
            scope=args.get("scope", "workable"),
            state=args.get("state", "open"),
            q=(args.get("q") or "").strip(),
            employer=[v for v in args.getlist("employer") if v],
            place=[v for v in args.getlist("place") if v],
            label=[v for v in args.getlist("label") if v],
            skill=[v for v in args.getlist("skill") if v],
            triage=[v for v in args.getlist("triage") if v],
            mode=[v for v in args.getlist("mode") if v],
            age=[v for v in args.getlist("age") if v],
        )

    @property
    def active_count(self) -> int:
        return sum(len(getattr(self, name)) for name in FACETS) + (1 if self.q else 0)

    def as_params(self, **overrides) -> dict:
        """Query parameters for a link, with facet lists preserved."""
        params = {"scope": self.scope, "state": self.state}
        if self.q:
            params["q"] = self.q
        for name in FACETS:
            values = list(getattr(self, name))
            if values:
                params[name] = values
        params.update(overrides)
        return {k: v for k, v in params.items() if v not in (None, "", [])}

    def toggled(self, facet: str, value: str) -> dict:
        """Parameters for the link that adds or removes one value."""
        values = list(getattr(self, facet))
        values = [v for v in values if v != value] if value in values else values + [value]
        return self.as_params(**{facet: values})

    def is_on(self, facet: str, value: str) -> bool:
        return value in getattr(self, facet)


def _clauses(selection: Selection, skip: str | None = None) -> tuple[list[str], list]:
    """WHERE fragments for everything selected, optionally skipping one facet.

    `skip` is what makes the per-option counts useful: a facet's own options are
    counted against every *other* filter.
    """
    where: list[str] = []
    params: list = []

    if selection.state == "open":
        where.append("p.closed_run IS NULL")
    elif selection.state == "closed":
        where.append("p.closed_run IS NOT NULL")

    if selection.scope == "workable":
        where.append("p.workable = 1")
    elif selection.scope == "excluded":
        where.append("p.workable = 0")

    if selection.q:
        where.append("(p.title LIKE ? OR e.display_name LIKE ? OR p.location LIKE ?)")
        params += [f"%{selection.q}%"] * 3

    if skip != "employer" and selection.employer:
        marks = ",".join("?" * len(selection.employer))
        where.append(f"e.key IN ({marks})")
        params += selection.employer

    if skip != "place" and selection.place:
        # A chosen value matches a posting three ways, and all three are needed for
        # the count beside it to be the truth:
        #
        #   the place itself          "Dublin" against a posting tagged Dublin
        #   another spelling of it    the same posting tagged "County Dublin"
        #   something inside it       "Ireland" against a posting tagged only Galway
        #
        # The last one is the point. Ireland used to match only postings that wrote
        # the word Ireland, so the filter said 43 and the panel said Dublin 37 beside
        # it, and picking both found nothing that picking Ireland alone had not.
        marks = ",".join("?" * len(selection.place))
        where.append(
            f"EXISTS (SELECT 1 FROM posting_place pp "
            f"LEFT JOIN place_meta m ON m.place = pp.place "
            f"WHERE pp.posting_id = p.id AND ("
            f"coalesce(m.canon, pp.place) IN ({marks}) "
            f"OR m.parent IN ({marks})))")
        params += selection.place + selection.place

    if skip != "skill" and selection.skill:
        marks = ",".join("?" * len(selection.skill))
        where.append(f"EXISTS (SELECT 1 FROM posting_skill ps "
                     f"WHERE ps.posting_id = p.id AND ps.term IN ({marks}))")
        params += selection.skill

    if skip != "label" and selection.label:
        marks = ",".join("?" * len(selection.label))
        where.append(f"EXISTS (SELECT 1 FROM label l "
                     f"WHERE l.posting_id = p.id AND l.rule_id IN ({marks}))")
        params += selection.label

    if skip != "triage" and selection.triage:
        wanted = [v for v in selection.triage if v != "none"]
        parts = []
        if wanted:
            marks = ",".join("?" * len(wanted))
            parts.append(f"EXISTS (SELECT 1 FROM triage t WHERE t.posting_id = p.id "
                         f"AND t.state IN ({marks}))")
            params += wanted
        if "none" in selection.triage:
            parts.append("NOT EXISTS (SELECT 1 FROM triage t WHERE t.posting_id = p.id)")
        if parts:
            where.append("(" + " OR ".join(parts) + ")")

    if skip != "mode" and selection.mode:
        parts = []
        if "remote" in selection.mode:
            parts.append("p.is_remote = 1")
        if "hybrid" in selection.mode:
            parts.append("p.is_hybrid = 1")
        if "onsite" in selection.mode:
            parts.append("(p.is_remote = 0 AND p.is_hybrid = 0)")
        if parts:
            where.append("(" + " OR ".join(parts) + ")")

    if skip != "age" and selection.age:
        days = [AGE_DAYS[v] for v in selection.age if v in AGE_DAYS]
        if days:
            # The widest window selected wins: picking "last 24 hours" and
            # "last 7 days" means the last 7 days, not an empty intersection.
            where.append("p.published_at >= date('now', ?)")
            params.append(f"-{max(days)} days")

    return where, params


def _sql(selection: Selection, skip: str | None, select: str, tail: str = "") -> tuple[str, list]:
    where, params = _clauses(selection, skip)
    sql = (f"SELECT {select} FROM posting p JOIN employer e ON e.id = p.employer_id"
           + (" WHERE " + " AND ".join(where) if where else "") + " " + tail)
    return sql, params


def page(conn, selection: Selection, limit: int = 200) -> list[dict]:
    sql, params = _sql(selection, None, "p.*, e.display_name AS employer, e.key AS employer_key, "
                       "(SELECT state FROM triage t WHERE t.posting_id = p.id) AS triage",
                       "ORDER BY p.id DESC LIMIT ?")
    rows = [dict(r) for r in conn.execute(sql, params + [limit]).fetchall()]
    for row in rows:
        row["labels"] = [dict(x) for x in conn.execute(
            """SELECT kind, severity, value, explain, produced_by, rule_id
               FROM label WHERE posting_id=? ORDER BY severity, rule_id""",
            (row["id"],)).fetchall()]
        row["places"] = [x[0] for x in conn.execute(
            "SELECT place FROM posting_place WHERE posting_id=? ORDER BY place",
            (row["id"],)).fetchall()]
        row["skills_have"] = [x[0] for x in conn.execute(
            "SELECT term FROM posting_skill WHERE posting_id=? AND have=1 ORDER BY term",
            (row["id"],)).fetchall()]
        row["skills_missing"] = [x[0] for x in conn.execute(
            "SELECT term FROM posting_skill WHERE posting_id=? AND have=0 ORDER BY term",
            (row["id"],)).fetchall()]
    return rows


def total(conn, selection: Selection) -> int:
    sql, params = _sql(selection, None, "count(*)")
    return conn.execute(sql, params).fetchone()[0]


def scope_counts(conn, selection: Selection) -> dict:
    """Counts for workable / excluded / all under the current filters.

    Always shown. A posting folded out of view behind a visible number is a fold; a
    posting dropped without a number is the failure this project exists to prevent.
    """
    probe = Selection(**{**selection.__dict__, "scope": "all"})
    sql, params = _sql(probe, None,
                       "sum(CASE WHEN p.workable=1 THEN 1 ELSE 0 END) AS workable, "
                       "sum(CASE WHEN p.workable=0 THEN 1 ELSE 0 END) AS excluded")
    row = conn.execute(sql, params).fetchone()
    workable = row["workable"] or 0
    excluded = row["excluded"] or 0
    return {"workable": workable, "excluded": excluded, "all": workable + excluded}



def place_tree(conn, selection: Selection) -> list[dict]:
    """The location facet, as a two-level tree instead of one flat list.

    Returns the top level in order - regions first, then countries by size, then
    anything no country could be found for - each row carrying its `children`.

    Every count is of DISTINCT POSTINGS, which is why the country rows need their own
    query rather than a sum over their children: a posting tagged both "Ireland" and
    "Dublin" must count once, and most are tagged both.
    """
    where, params = _clauses(selection, "place")
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    rolled = conn.execute(
        "SELECT coalesce(m.parent, coalesce(m.canon, pp.place)) AS top, "
        "       count(DISTINCT pp.posting_id) AS n "
        "FROM posting_place pp "
        "LEFT JOIN place_meta m ON m.place = pp.place "
        "JOIN posting p ON p.id = pp.posting_id "
        "JOIN employer e ON e.id = p.employer_id"
        + clause + " GROUP BY top", params).fetchall()

    leaves = conn.execute(
        "SELECT coalesce(m.parent, coalesce(m.canon, pp.place)) AS top, "
        "       coalesce(m.canon, pp.place) AS value, "
        "       coalesce(m.kind, 'place') AS kind, "
        "       count(DISTINCT pp.posting_id) AS n "
        "FROM posting_place pp "
        "LEFT JOIN place_meta m ON m.place = pp.place "
        "JOIN posting p ON p.id = pp.posting_id "
        "JOIN employer e ON e.id = p.employer_id"
        + clause + " GROUP BY top, value, kind", params).fetchall()

    totals = {row["top"]: row["n"] for row in rolled}
    kinds: dict[str, str] = {}
    children: dict[str, list[dict]] = {}
    for row in leaves:
        if row["value"] == row["top"]:
            kinds[row["top"]] = row["kind"]
            continue
        children.setdefault(row["top"], []).append(
            {"value": row["value"], "label": row["value"], "n": row["n"]})

    tops: list[dict] = []
    for top, n in totals.items():
        kids = sorted(children.get(top, []), key=lambda c: (-c["n"], c["label"]))
        tops.append({"value": top, "label": top, "n": n,
                     "kind": kinds.get(top, "place"), "children": kids})

    # Regions first and labelled as such: they are not places the reader could move
    # to, they are postings open to a whole region, and mixing them in with countries
    # is half of what made the flat list unreadable.
    order = {"region": 0, "country": 1, "place": 2}
    tops.sort(key=lambda t: (order.get(t["kind"], 3), -t["n"], t["label"]))
    return tops


def options(conn, selection: Selection) -> dict:
    """Every facet's options with counts, each computed ignoring its own facet."""
    out: dict[str, list[dict]] = {}

    sql, params = _sql(selection, "employer", "e.key AS value, e.display_name AS label, "
                       "count(*) AS n", "GROUP BY e.key ORDER BY n DESC, e.display_name")
    out["employer"] = [dict(r) for r in conn.execute(sql, params).fetchall()]

    out["place"] = place_tree(conn, selection)

    where, params = _clauses(selection, "skill")
    sql = ("SELECT ps.term AS value, ps.term AS label, max(ps.have) AS have, "
           "count(DISTINCT ps.posting_id) AS n "
           "FROM posting_skill ps JOIN posting p ON p.id = ps.posting_id "
           "JOIN employer e ON e.id = p.employer_id"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " GROUP BY ps.term ORDER BY n DESC, ps.term LIMIT 40")
    out["skill"] = [dict(r) for r in conn.execute(sql, params).fetchall()]

    where, params = _clauses(selection, "label")
    sql = ("SELECT l.rule_id AS value, min(l.explain) AS label, min(l.severity) AS severity, "
           "count(DISTINCT l.posting_id) AS n "
           "FROM label l JOIN posting p ON p.id = l.posting_id "
           "JOIN employer e ON e.id = p.employer_id"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " GROUP BY l.rule_id ORDER BY n DESC LIMIT 40")
    out["label"] = [dict(r) for r in conn.execute(sql, params).fetchall()]

    sql, params = _sql(selection, "triage",
                       "coalesce((SELECT state FROM triage t WHERE t.posting_id=p.id), 'none') "
                       "AS value, count(*) AS n", "GROUP BY value ORDER BY n DESC")
    out["triage"] = [{"value": r["value"], "label": TRIAGE_LABELS.get(r["value"], r["value"]),
                      "n": r["n"]} for r in conn.execute(sql, params).fetchall()]

    sql, params = _sql(selection, "mode",
                       "sum(p.is_remote) AS remote, sum(p.is_hybrid) AS hybrid, "
                       "sum(CASE WHEN p.is_remote=0 AND p.is_hybrid=0 THEN 1 ELSE 0 END) AS onsite")
    row = conn.execute(sql, params).fetchone()
    out["mode"] = [{"value": key, "label": MODE_LABELS[key], "n": row[key] or 0}
                   for key in ("remote", "hybrid", "onsite") if (row[key] or 0) > 0]

    out["age"] = []
    for key, days in AGE_DAYS.items():
        probe = Selection(**{**selection.__dict__, "age": [key]})
        sql, params = _sql(probe, None, "count(*)")
        out["age"].append({"value": key, "label": AGE_LABELS[key],
                           "n": conn.execute(sql, params).fetchone()[0]})

    return out
