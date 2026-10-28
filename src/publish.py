#!/usr/bin/env python3
"""Push the card, licence, provenance, the prefecture Parquet (one file per sheet), the docs and the source manifest to the Hub in one commit.

uv run python src/publish.py             # dry run: list the files and their sizes
uv run python src/publish.py --push      # prints the commit sha and writes docs/revision.json
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rfm  # noqa: E402

DATA = ROOT / "data"
P = rfm.PREF
REPO = P.hub_repo
DOCS = [
    f"{P.profile_stem}.md",
    f"{P.profile_stem}.json",
    "download_plan.json",
    "raw_profile.md",
    "raw_profile.json",
    "extract_log.json",
    "verify_local.json",
]


def run_name() -> str:
    return sorted((DATA / "raw").glob("*/MANIFEST.json"))[-1].parent.name


def collect() -> dict[str, Path]:
    card = (DATA / "README.md").read_text(encoding="utf-8")
    if "license_name: pdl-1.0" not in card:
        raise SystemExit("the card does not declare PDL1.0")
    run = sorted((DATA / "raw").glob("*/MANIFEST.json"))[-1].parent
    prof = json.loads((ROOT / "docs" / f"{P.profile_stem}.json").read_text())
    if f"{prof['rows']:,}" not in card or f"raw/{run.name}/" not in card:
        raise SystemExit("the card does not give the row count or the run")
    ver = json.loads((ROOT / "docs" / "verify_local.json").read_text())["totals"]
    if ver["selected_again"] != prof["rows"] or ver["mine"] != prof["rows"]:
        raise SystemExit("the local verification does not match the profile")
    files = {"README.md": DATA / "README.md", "LICENSE": DATA / "LICENSE", "provenance.yaml": DATA / "provenance.yaml",
             f"raw/{run.name}/MANIFEST.json": run / "MANIFEST.json"}  # fmt: skip
    for p in sorted(run.glob("ckan_*.json")):
        files[f"raw/{run.name}/{p.name}"] = p
    for d in sorted((DATA / "parquet").glob("sheet=*")):
        files[f"parquet/{d.name.split('=')[1]}.parquet"] = d / "part.parquet"
    files |= {f"docs/{n}": ROOT / "docs" / n for n in DOCS}
    missing = [k for k, v in files.items() if not v.is_file()]
    if missing:
        raise SystemExit(f"missing: {missing}")
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    files = collect()
    total = sum(p.stat().st_size for p in files.values())
    print(f"{a.repo}\n  {len(files)} files, {total:,} bytes")
    if not a.push:
        print("\ndry run. pass --push to upload")
        return 0
    from huggingface_hub import CommitOperationAdd, HfApi

    api = HfApi()
    api.create_repo(a.repo, repo_type="dataset", exist_ok=True, private=False)
    ops = [CommitOperationAdd(path_in_repo=k, path_or_fileobj=str(p)) for k, p in files.items()]
    info = api.create_commit(
        a.repo,
        ops,
        repo_type="dataset",
        commit_message=f"{P.en} extract of 全国森林資源メッシュ (run {run_name()})",
    )
    sums = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
    (ROOT / "docs" / "revision.json").write_text(
        json.dumps({"repo": a.repo, "revision": info.oid, "sha256": sums}, indent=1) + "\n"
    )
    print("pushed", a.repo, "revision", info.oid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
