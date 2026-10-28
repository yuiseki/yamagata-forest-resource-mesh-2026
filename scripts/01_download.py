#!/usr/bin/env python3
"""Download the part of 全国森林資源メッシュ that touches this prefecture, and its 森林計画対象森林レイヤ.

    uv run python scripts/01_download.py --plan   # choose the sheets, write docs/download_plan.json, stop
    uv run python scripts/01_download.py          # the whole download

Steps: read the CKAN records and stop if the licence text, the terms PDFs or the CRS statement are gone;
save the terms PDFs and the sheet index; cut the sheet index with the prefecture boundary (KSJ N03, a
cutter only) to choose the sheets; download and unpack those sheets (an archive that a sibling
repository of the series already holds is hard-linked after its size, record date and sha256 are
checked); write MANIFEST.json with sha256, size and HTTP headers.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import geopandas as gpd
import rfm

ROOT = Path(__file__).parents[1]
P = rfm.PREF


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": rfm.UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def probe(url: str) -> tuple[str, dict]:
    out = subprocess.run(
        ["curl", "-sS", "-L", "-A", rfm.UA, "-r", "0-0", "-D", "-", "-o", "/dev/null",
         "-w", "\n@@%{url_effective}", url],
        check=True, capture_output=True, text=True,
    ).stdout.replace("\r", "")  # fmt: skip
    final = out.rsplit("@@", 1)[1].strip()
    last = [h for h in out.split("\n\n") if h.startswith("HTTP/")][-1]
    pick = {}
    for line in last.splitlines()[1:]:
        k, _, v = line.partition(":")
        if k.lower() in ("etag", "last-modified", "content-range"):
            pick[k.lower()] = v.strip()
    return final, pick


def fetch(url: str, dest: Path, connections: int = 2) -> dict:
    """Resumable ranged download; the signed link is resolved again whenever a round falls short."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(6):
        try:
            final, head = probe(url)
        except subprocess.CalledProcessError:  # a burst of requests was answered with 403 once
            time.sleep(30 * (attempt + 1))
            continue
        total = int(head["content-range"].rsplit("/", 1)[1])
        done = dest.exists() and dest.stat().st_size == total
        if done and not dest.with_name(dest.name + ".aria2").exists():
            return head
        subprocess.run(["aria2c", "-c", "-x", str(connections), "-s", str(connections), "-k", "4M",
                        "--user-agent", rfm.UA, "--summary-interval=0", "--console-log-level=warn",
                        "-d", str(dest.parent), "-o", dest.name, final], check=False)  # fmt: skip
    raise SystemExit(f"could not fetch {url}")


def read_n03(zpath: Path) -> gpd.GeoDataFrame:
    """The polygons of the KSJ N03 zip (the shapefile inside; GeoJSON copies are ignored)."""
    shp = next(n for n in zipfile.ZipFile(zpath).namelist() if n.endswith(".shp"))
    return gpd.read_file(f"zip://{zpath}!{shp}")


def record(ckan_id: str) -> dict:
    return json.loads(get(rfm.CKAN + ckan_id))["result"]


def check_record(rec: dict, crs: int | None = None) -> None:
    if "公共データ利用規約（第1.0版）" not in rec["notes"]:
        raise SystemExit(f"{rec['name']}: the PDL1.0 statement is gone from the record")
    if not any("重要情報" in r["name"] for r in rec["resources"]):
        raise SystemExit(f"{rec['name']}: the 重要情報 PDF is gone from the record")
    if crs is not None and f"EPSG：{crs}" not in rec["notes"]:
        raise SystemExit(f"{rec['name']}: the record does not state EPSG {crs}")


def sibling_runs() -> list[Path]:
    """Raw run directories of the other repositories of the series, newest first."""
    mine = (ROOT / "data" / "raw").resolve()
    runs = [
        d for d in ROOT.parent.glob("*-forest-resource-mesh-2026/data/raw/*")
        if d.is_dir() and d.parent.resolve() != mine and (d / "MANIFEST.json").is_file()
    ]  # fmt: skip
    return sorted(runs, reverse=True)


def main() -> int:
    plan_only = "--plan" in sys.argv
    run = date.today().strftime("%Y%m%d")
    out = ROOT / "data" / "raw" / run
    docs = ROOT / "data" / "docs"
    out.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    mesh, layer = record(P.mesh_id), record(rfm.LAYER_ID)
    check_record(mesh, P.crs)
    check_record(layer)
    keep = ("id", "name", "title", "license_id", "license_title", "metadata_created",
            "metadata_modified", "author", "notes")  # fmt: skip
    manifest = {
        "run": run,
        "prefecture": {"code": P.code, "ja": P.ja, "mesh_record": P.mesh_id},
        "files": {},
    }
    for rec in (mesh, layer):
        meta = {k: rec.get(k) for k in keep}
        meta["resources"] = [{k: r.get(k) for k in ("name", "format", "url", "size", "last_modified")}
                             for r in rec["resources"] if r["format"] in ("PDF", "gpkg", "7z", "")]  # fmt: skip
        (out / f"ckan_{rec['name']}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1) + "\n"
        )
    # terms, definition and index (the PDFs are read for the licence check; they are not republished)
    for rec in (mesh, layer):
        for r in rec["resources"]:
            if r["format"] == "PDF" or (r["format"] == "gpkg" and "mesh_index" in r["url"]):
                name = f"{rec['name']}__{r['url'].rsplit('/', 1)[1]}"
                (docs / name).write_bytes(get(r["url"]))
                manifest["files"][name] = {"url": r["url"], "sha256": rfm.sha256(docs / name)}
    n03 = docs / P.n03_name
    n03.write_bytes(get(P.n03_url))
    manifest["files"][n03.name] = {
        "url": P.n03_url,
        "sha256": rfm.sha256(n03),
        "role": "cutter only",
    }
    # choose the sheets that touch the prefecture
    idx_name = next(n for n in manifest["files"] if n.endswith("kei_mesh_index.gpkg"))
    sheets = gpd.read_file(docs / idx_name)
    pref = read_n03(n03)
    assert set(pref["N03_001"]) == {P.ja}, set(pref["N03_001"])
    cutter = pref.to_crs(sheets.crs).geometry.union_all()
    chosen = rfm.choose_sheets(sheets, cutter)
    by_name = {r["name"]: r for r in mesh["resources"] if r["format"] == "7z"}
    absent = [s for s in chosen if rfm.archive_name(s) not in by_name]
    if absent:
        raise SystemExit(f"sheets in the index but not in the record: {absent}")
    runs = sibling_runs()
    plan = {"prefecture": P.ja, "mesh_record": P.mesh_id, "index_crs": sheets.crs.to_epsg(), "sheets": chosen,
            "bytes_by_record": sum(by_name[rfm.archive_name(s)]["size"] for s in chosen),
            "layer_bytes_by_record": next(r for r in layer["resources"] if r["name"] == P.layer_file)["size"]}  # fmt: skip
    print(
        len(chosen),
        "sheets touch",
        P.ja,
        "; bytes by the record:",
        plan["bytes_by_record"],
        flush=True,
    )
    manifest["sheets"] = chosen
    if plan_only:
        (ROOT / "docs").mkdir(exist_ok=True)
        (ROOT / "docs" / "download_plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=1) + "\n"
        )
        return 0
    for sheet in chosen:
        name = rfm.archive_name(sheet)
        r = by_name[name]
        dest = out / name
        shared = (
            None if dest.exists() else rfm.find_reusable(name, r["size"], r["last_modified"], runs)
        )
        if shared is not None:
            os.link(shared, dest)
            src = json.loads((shared.parent / "MANIFEST.json").read_text())["files"][name]
            manifest["files"][name] = {
                **src,
                "reused_from": str(shared.parent.relative_to(ROOT.parent)),
            }
        else:
            head = fetch(r["url"], dest)
            time.sleep(2)  # the host answered 403 to a burst of requests once
            manifest["files"][name] = {"url": r["url"], "size": dest.stat().st_size,
                                       "sha256": rfm.sha256(dest), "record_last_modified": r["last_modified"],
                                       "http": head}  # fmt: skip
        if not (out / "gpkg" / name.replace(".7z", ".gpkg")).exists():
            subprocess.run(
                ["7z", "x", "-y", f"-o{out / 'gpkg'}", str(dest)], check=True, capture_output=True
            )
        print(name, manifest["files"][name]["size"], "reused" if shared else "fetched", flush=True)
    lr = next(r for r in layer["resources"] if r["name"] == P.layer_file)
    # the record gives ".../download/www.geospatial.jpfr_layer_<code>_2025.7z", which answers 500; the
    # same resource under its plain file name works
    layer_url = lr["url"].replace("/download/www.geospatial.jp", "/download/")
    head = fetch(layer_url, out / P.layer_file)
    subprocess.run(
        ["7z", "x", "-y", f"-o{out / 'gpkg'}", str(out / P.layer_file)],
        check=True,
        capture_output=True,
    )
    manifest["files"][P.layer_file] = {"url": layer_url, "size": (out / P.layer_file).stat().st_size,
                                       "sha256": rfm.sha256(out / P.layer_file),
                                       "record_last_modified": lr["last_modified"], "http": head}  # fmt: skip
    manifest["gpkg"] = sorted(p.name for p in (out / "gpkg").rglob("*.gpkg"))
    (out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "download_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=1) + "\n"
    )
    print("wrote", out / "MANIFEST.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
