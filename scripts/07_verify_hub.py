#!/usr/bin/env python3
"""Read the repository back from the Hub at the recorded revision and check it against the profile and the local copy:
file checksums, rows per file, schema, CRS, extent, geometry validity, value counts and NULL counts.

    uv run python scripts/07_verify_hub.py   # needs docs/revision.json from src/publish.py --push
"""

import hashlib
import json
import sys
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import rfm
from huggingface_hub import hf_hub_download

ROOT = Path(__file__).parents[1]
P = rfm.PREF
TREE = rfm.TREE


def main() -> int:
    rev = json.loads((ROOT / "docs" / "revision.json").read_text())
    repo, sha = rev["repo"], rev["revision"]
    cache = ROOT / "data" / "hub_readback"
    bad, out = [], {"repo": repo, "revision": sha}
    for name, want in rev["sha256"].items():
        p = Path(hf_hub_download(repo, name, repo_type="dataset", revision=sha, local_dir=cache))
        h = hashlib.sha256()
        with p.open("rb") as f:
            while c := f.read(1 << 24):
                h.update(c)
        if h.hexdigest() != want:
            bad.append(f"checksum {name}")
    out["files_checked"] = len(rev["sha256"])
    prof = json.loads((ROOT / "docs" / f"{P.profile_stem}.json").read_text())
    log = json.loads((ROOT / "docs" / "extract_log.json").read_text())
    files = sorted((cache / "parquet").glob("*.parquet"))
    # column names and types only: the per-file metadata (extent, pandas info) differs by design
    cols = lambda f: [(x.name, str(x.type)) for x in pq.ParquetFile(f).schema_arrow]  # noqa: E731
    schemas = {tuple(cols(f)) for f in files}
    local = {
        f.parent.name.split("=")[1]: f
        for f in (ROOT / "data" / "parquet").glob("sheet=*/part.parquet")
    }
    if len(schemas) != 1 or {tuple(cols(f)) for f in local.values()} != schemas:
        bad.append("schema")
    out["schema"] = [f"{n}:{t}" for n, t in next(iter(schemas))]
    if sorted(f.stem for f in files) != sorted(local):
        bad.append("file list")
    geo = json.loads(pq.ParquetFile(files[0]).schema_arrow.metadata[b"geo"])
    crs = geo["columns"]["geometry"]["crs"]
    out["crs"] = crs["id"] if "id" in crs else str(crs)[:80]
    for f in files:
        n = pq.ParquetFile(f).metadata.num_rows
        if n != log["sheets"][f.stem]["kept"]:
            bad.append(f"rows {f.stem}")
    con = duckdb.connect()
    con.execute("install spatial; load spatial")
    con.execute(f"create view m as select * from read_parquet('{cache}/parquet/*.parquet')")
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    out["rows"] = q("select count(*) from m")
    out["invalid"] = q("select count(*) from m where not ST_IsValid(geometry)")
    out["extent"] = list(
        con.execute(
            "select min(cell_x), min(cell_y), max(cell_x) + 20, max(cell_y) + 20 from m"
        ).fetchone()
    )
    out["distinct_cells"] = q("select count(*) from (select distinct cell_x, cell_y from m)")
    out["non_null"] = {
        c: q(f'select count("{c}") from m')
        for c in TREE + ["林齢", "森林簿年月日", "樹冠高", "立木密度", "平均標高", "計測年月日"]
    }
    out["unique_values"] = {
        c: {
            k: int(v)
            for k, v in con.execute(
                f"select coalesce(cast(\"{c}\" as varchar), '<NULL>'), count(*) from m group by 1 order by 2 desc"
            ).fetchall()
        }
        for c in TREE + ["森林簿年月日"]
    }
    out["ownership"] = {
        k: int(v)
        for k, v in con.execute(
            "select coalesce(layer_ownership, '<NULL>'), count(*) from m group by 1 order by 2 desc"
        ).fetchall()
    }
    if out["rows"] != prof["rows"] or out["distinct_cells"] != prof["distinct_cells"]:
        bad.append("rows or distinct cells vs the profile")
    if out["invalid"]:
        bad.append("invalid geometry")
    if out["non_null"] != {k: v for k, v in prof["non_null"].items() if k in out["non_null"]}:
        bad.append("non-NULL counts vs the profile")
    for c in TREE + ["森林簿年月日"]:
        if out["unique_values"][c] != prof["unique_values"][c]:
            bad.append(f"unique values {c}")
    if out["ownership"] != prof["layer_ownership"]:
        bad.append("ownership counts")
    out["problems"] = bad
    (ROOT / "docs" / "verify_hub.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in out.items() if k != "unique_values"}, ensure_ascii=False, indent=1
        )
    )
    if bad:
        print("PROBLEMS:", bad, file=sys.stderr)
        return 1
    print("OK: the repository at", sha, "matches the profile and the local copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
