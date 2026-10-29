#!/usr/bin/env python3
"""Check the cells of this prefecture against the raw sheets with a second engine (DuckDB spatial), sheet by sheet:
the same cells are selected (centre inside the prefecture), the 11 attributes, the geometry and the cell corner
are equal, and the three layer columns agree with a point-in-polygon test done again.

    uv run python scripts/06_verify.py                    # all sheets
    uv run python scripts/06_verify.py --part 0 --of 4    # every 4th sheet, writes docs/verify_part0.json
    uv run python scripts/06_verify.py --merge --of 4     # merges the parts into docs/verify_local.json
Exits 1 on any difference.
"""

import json
import sys
import zipfile
from pathlib import Path

import duckdb
import pyogrio
import rfm

ROOT = Path(__file__).parents[1]
ATTRS = rfm.MESH_COLUMNS
P = rfm.PREF
CHK = " or ".join(f'm."{c}" is distinct from s."{c}"' for c in ATTRS)


def main() -> int:
    args = sys.argv[1:]
    of = int(args[args.index("--of") + 1]) if "--of" in args else 1
    part = int(args[args.index("--part") + 1]) if "--part" in args else None
    if "--merge" in args:
        return merge(of)
    run = sorted((ROOT / "data" / "raw").glob("*/MANIFEST.json"))[-1].parent
    z = ROOT / "data" / "docs" / P.n03_name
    shp = next(n for n in zipfile.ZipFile(z).namelist() if n.endswith(".shp"))
    con = duckdb.connect()
    con.execute("install spatial; load spatial; set memory_limit='5GB'")
    con.execute(f"create table pref6668 as select geom g from ST_Read('/vsizip/{z}/{shp}')")
    con.execute(
        f"create table pref as select row_number() over () i, ST_Transform(g, 'EPSG:6668', 'EPSG:{P.crs}', always_xy := true) g from pref6668"
    )
    # Testing 750,000 centres against a few thousand complex polygons is slow (hours for a long coast line), so the
    # polygons are cut once into 5 km tiles; a centre intersects the polygons exactly when it intersects a tile
    # (the area check below shows that the tiles add up to the polygons).
    step = 5000
    x0, y0, x1, y1 = con.execute(
        "select min(ST_XMin(g)), min(ST_YMin(g)), max(ST_XMax(g)), max(ST_YMax(g)) from pref"
    ).fetchone()
    nx, ny = int((x1 - x0) // step) + 1, int((y1 - y0) // step) + 1
    con.execute(
        f"create table grid as select ST_MakeEnvelope({x0} + i * {step}, {y0} + j * {step}, {x0} + (i + 1) * {step}, "
        f"{y0} + (j + 1) * {step}) b from range({nx}) t(i), range({ny}) u(j)"
    )
    con.execute(
        "create table tiles as select ST_Intersection(p.g, gr.b) g from pref p join grid gr on ST_Intersects(p.g, gr.b)"
    )
    con.execute("delete from tiles where g is null or ST_IsEmpty(g)")
    a_pref, a_tiles = con.execute(
        "select (select sum(ST_Area(g)) from pref), (select sum(ST_Area(g)) from tiles)"
    ).fetchone()
    if abs(a_pref - a_tiles) > 1e-9 * a_pref:
        raise SystemExit(f"the tiles do not add up to the polygons: {a_pref} against {a_tiles}")
    lay = run / "gpkg" / P.layer_gpkg
    lay_layer = rfm.layer_name(lay, P.ja)
    con.execute(
        f"create table lay as select 民国別 own, 市町村コード5桁 code5, 市町村名称 mname, geom from ST_Read('{lay}', layer='{lay_layer}')"
    )
    tot = dict.fromkeys(
        [
            "source_rows",
            "selected_again",
            "mine",
            "only_mine",
            "only_source",
            "attribute_diff",
            "geometry_diff",
            "corner_diff",
            "layer_diff",
            "layer_value_not_among_matches",
        ],
        0,
    )
    per = {}
    allp = sorted((run / "gpkg").glob("fr_mesh20m_*_2025.gpkg"))
    for p in allp if part is None else allp[part::of]:
        sheet = rfm.sheet_of(p)
        layer = [str(x[0]) for x in pyogrio.list_layers(p) if x[1] is not None][0]
        mine_path = ROOT / "data" / "parquet" / f"sheet={sheet}" / "part.parquet"
        con.execute("drop table if exists s")
        con.execute(
            f"""create temp table s as select s.* , ST_Centroid(s.geom) c from ST_Read('{p}', layer='{layer}') s"""
        )
        con.execute("drop table if exists sel")
        con.execute(
            f"create temp table sel as select s.*, ST_Transform(s.c, 'EPSG:{P.crs}', 'EPSG:6668', always_xy := true) c6668 from s where s.fid in (select s2.fid from s s2 join tiles a on ST_Intersects(a.g, s2.c))"
        )
        r = {
            "source_rows": con.execute("select count(*) from s").fetchone()[0],
            "selected_again": con.execute("select count(*) from sel").fetchone()[0],
        }
        if not mine_path.exists():
            r |= {"mine": 0, "only_mine": 0, "only_source": r["selected_again"]}
        else:
            con.execute("drop table if exists m")
            con.execute(f"create temp table m as select * from read_parquet('{mine_path}')")
            q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
            r["mine"] = q("select count(*) from m")
            r["only_mine"] = q(
                "select count(*) from m where source_fid not in (select fid from sel)"
            )
            r["only_source"] = q(
                "select count(*) from sel where fid not in (select source_fid from m)"
            )
            r["attribute_diff"] = q(
                f"select count(*) from m join sel s on s.fid = m.source_fid where {CHK}"
            )
            r["geometry_diff"] = q(
                "select count(*) from m join sel s on s.fid = m.source_fid where ST_AsWKB(m.geometry) <> ST_AsWKB(s.geom)"
            )
            r["corner_diff"] = q(
                "select count(*) from m join sel s on s.fid = m.source_fid where m.cell_x <> round(ST_XMin(s.geom))::bigint or m.cell_y <> round(ST_YMin(s.geom))::bigint or m.sheet <> '"
                + sheet
                + "'"
            )
            # layer columns again: the polygons of the layer that contain the cell centre
            con.execute("drop table if exists hits")
            con.execute("""create temp table hits as select sel.fid, l.own, l.code5, l.mname
                           from sel join lay l on ST_Within(sel.c6668, l.geom)""")
            r["layer_diff"] = (
                q("""select count(*) from m where
                (select count(*) from hits h where h.fid = m.source_fid) = 0 and m.layer_ownership is not null""")
                + q("""select count(*) from m where
                (select count(*) from hits h where h.fid = m.source_fid) > 0 and m.layer_ownership is null""")
            )
            r["layer_value_not_among_matches"] = (
                q("""select count(*) from m where m.layer_ownership is not null and not exists
                (select 1 from hits h where h.fid = m.source_fid and h.own is not distinct from m.layer_ownership and h.code5 is not distinct from m.layer_municipality_code5 and h.mname is not distinct from m.layer_municipality_name)""")
            )
        per[sheet] = r
        for k, v in r.items():
            tot[k] += v
        print(sheet, r, flush=True)
    res = {"totals": tot, "per_sheet": per}
    (ROOT / "docs").mkdir(exist_ok=True)
    (
        ROOT / "docs" / ("verify_local.json" if part is None else f"verify_part{part}.json")
    ).write_text(json.dumps(res, indent=1) + "\n")
    bad = {
        k: tot[k]
        for k in (
            "only_mine",
            "only_source",
            "attribute_diff",
            "geometry_diff",
            "corner_diff",
            "layer_diff",
            "layer_value_not_among_matches",
        )
        if tot[k]
    }
    if bad or tot["selected_again"] != tot["mine"]:
        print("DIFFERENCES:", bad, tot, file=sys.stderr)
        return 1
    print("OK", tot)
    return 0


def merge(of: int) -> int:
    parts = [json.loads((ROOT / "docs" / f"verify_part{i}.json").read_text()) for i in range(of)]
    per = {k: v for p in parts for k, v in p["per_sheet"].items()}
    tot = {k: sum(v.get(k, 0) for v in per.values()) for k in parts[0]["totals"]}
    expected = len(
        list(
            (sorted((ROOT / "data" / "raw").glob("*/MANIFEST.json"))[-1].parent / "gpkg").glob(
                "fr_mesh20m_*_2025.gpkg"
            )
        )
    )
    (ROOT / "docs" / "verify_local.json").write_text(
        json.dumps({"totals": tot, "per_sheet": dict(sorted(per.items()))}, indent=1) + "\n"
    )
    bad = {
        k: tot[k]
        for k in (
            "only_mine",
            "only_source",
            "attribute_diff",
            "geometry_diff",
            "corner_diff",
            "layer_diff",
            "layer_value_not_among_matches",
        )
        if tot[k]
    }
    if len(per) != expected or bad or tot["selected_again"] != tot["mine"]:
        print("DIFFERENCES:", len(per), expected, bad, tot, file=sys.stderr)
        return 1
    print("OK", tot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
