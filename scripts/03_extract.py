#!/usr/bin/env python3
"""Keep the 20 m cells of the raw sheets whose centre lies inside this prefecture, one GeoParquet per sheet.

Rule (recorded in the card): cells are not cut; a cell belongs to the prefecture when its centre is inside
(or on the boundary of) one of the KSJ N03 (2026-01-01) polygons of the prefecture; the polygons are
used as they are, not dissolved, and the centres are looked up in an STRtree of them. The original 11
attributes keep their names and values. Added columns: sheet, source_fid (fid inside the sheet), cell_x,
cell_y (lower-left corner in the CRS of the mesh, metres), and three columns taken from the
森林計画対象森林レイヤ of the prefecture by the cell centre: layer_ownership (民国別),
layer_municipality_code5 (市町村コード5桁), layer_municipality_name (市町村名称).

    uv run python scripts/03_extract.py   # writes data/parquet/sheet=<name>/part.parquet and docs/extract_log.json
"""

import json
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rfm
import shapely
from pyproj import Transformer
from shapely import STRtree

ROOT = Path(__file__).parents[1]
P = rfm.PREF


def main() -> int:
    run = sorted((ROOT / "data" / "raw").glob("*/MANIFEST.json"))[-1].parent
    z = ROOT / "data" / "docs" / P.n03_name
    shp = next(n for n in zipfile.ZipFile(z).namelist() if n.endswith(".shp"))
    n03 = gpd.read_file(f"zip://{z}!{shp}")
    assert set(n03["N03_001"]) == {P.ja} and n03.crs.to_epsg() == 6668
    pref_polys = STRtree(n03.to_crs(P.crs).geometry.values)
    lay_path = run / "gpkg" / P.layer_gpkg
    layer = gpd.read_file(lay_path, layer=rfm.layer_name(lay_path, P.ja))
    assert layer.crs.to_epsg() == 6668, layer.crs
    tree = STRtree(layer.geometry.values)
    to_geo = Transformer.from_crs(P.crs, 6668, always_xy=True)
    out_dir = ROOT / "data" / "parquet"
    log = {
        "cutter": f"KSJ N03 {rfm.N03_VERSION} {P.code} ({P.en}), {len(n03)} polygons, not dissolved",
        "sheets": {},
        "layer_polygons": len(layer),
    }
    total = 0
    for p in sorted((run / "gpkg").glob("fr_mesh20m_*_2025.gpkg")):
        sheet = rfm.sheet_of(p)
        df = pyogrio.read_dataframe(p, fid_as_index=True, use_arrow=True)
        crs = df.crs.to_epsg() if df.crs else None
        assert crs == P.crs, (p.name, crs)
        b = shapely.bounds(df.geometry.values)
        cx, cy = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
        hit, _ = pref_polys.query(shapely.points(cx, cy), predicate="intersects")
        sel = np.zeros(len(df), dtype=bool)
        sel[hit] = True
        if not sel.any():
            log["sheets"][sheet] = {"read": len(df), "kept": 0}
            continue
        d = df[sel].copy()
        b, cx, cy = b[sel], cx[sel], cy[sel]
        d.insert(0, "source_fid", d.index.astype("int64"))
        d.insert(0, "sheet", sheet)
        d["cell_x"] = np.rint(b[:, 0]).astype("int64")
        d["cell_y"] = np.rint(b[:, 1]).astype("int64")
        lon, lat = to_geo.transform(cx, cy)
        pts = shapely.points(lon, lat)
        ii, jj = tree.query(pts, predicate="within")
        first = pd.Series(jj, index=ii).groupby(level=0).first()
        n_multi = int((pd.Series(ii).value_counts() > 1).sum())
        match = np.full(len(d), -1)
        match[first.index.values] = first.values
        for col, src in (("layer_ownership", "民国別"), ("layer_municipality_code5", "市町村コード5桁"),
                         ("layer_municipality_name", "市町村名称")):  # fmt: skip
            vals = layer[src].values
            d[col] = np.where(match >= 0, vals[np.maximum(match, 0)], None)
        d = d.reset_index(drop=True)
        (out_dir / f"sheet={sheet}").mkdir(parents=True, exist_ok=True)
        d.to_parquet(
            out_dir / f"sheet={sheet}" / "part.parquet",
            compression="zstd",
            write_covering_bbox=True,
            index=False,
        )
        log["sheets"][sheet] = {"read": len(df), "kept": len(d), "no_layer_polygon": int((match < 0).sum()),
                                "cells_in_several_layer_polygons": n_multi}  # fmt: skip
        total += len(d)
        print(sheet, log["sheets"][sheet], flush=True)
    log["rows"] = total
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "extract_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1) + "\n"
    )
    print("rows", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
