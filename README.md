# yamagata-forest-resource-mesh-2026

Yamagata Prefecture extract of 全国森林資源メッシュ (Forestry Agency, MAFF), frozen on Hugging Face as
`yuiseki/yamagata-forest-resource-mesh-2026`. Survey: https://github.com/yuiseki/akita-beech-oak-sources. The scripts are the same as in the other
prefectures of the series (`akita-forest-resource-mesh-2026` and its siblings); only `scripts/rfm_pref.py` differs.

Scripts run in order (`uv run python scripts/NN_*.py`); `data/` is not in git.

1. `01_download.py` the sheets that touch Yamagata, the 森林計画対象森林レイヤ of Yamagata, the terms and the data definition (`--plan` only chooses the sheets)
2. `02_profile_raw.py` raw profile of the whole sheets; results in `docs/`
3. `03_extract.py`, `04_profile.py` keep the cells whose centre is inside Yamagata and profile them
4. `05_card.py` card, licence, provenance; `06_verify.py` second-engine check against the raw sheets
5. `src/publish.py --push` upload in one commit; `07_verify_hub.py` read back at the fixed revision (`docs/revision.md`)
