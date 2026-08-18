"""議会会議録から北谷町への言及を抜き出して地図に紐づける。

出力: docs/data/chatan_speeches.json

データ元は okinawa-civic-api の PostgreSQL（沖縄県議会 令和8年第1回2月定例会）。
北谷町議会そのものは会議録システムの robots.txt が API 配下を Disallow しているため
収集していない（許諾が取れたらここに足す）。

公開するのは「言及件数・1文の抜粋・原文へのリンク」までで、本文は載せない。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data"
DB = "okinawa_civic"

# 北谷町の字。地図側の区域名と対応づけるため、基準名とその表記ゆれを持つ。
AREAS = {
    "北前": ["北前"],
    "北谷": ["北谷一丁目", "北谷二丁目", "北谷１丁目", "北谷２丁目"],
    "玉上": ["玉上"],
    "吉原": ["吉原"],
    "桃原": ["桃原"],
    "桑江": ["桑江"],
    "伊平": ["伊平"],
    "上勢頭": ["上勢頭", "上勢"],
    "浜川": ["浜川"],
    "砂辺": ["砂辺"],
    "宮城": ["宮城"],
    "港": ["港"],
    "美浜": ["美浜"],
    "大村": ["大村"],
}

# 県内外の同名地名・人名を弾く。ここを外すと伊平屋村や宮城島を拾ってしまう。
BLOCKERS = [
    "伊平屋", "伊是名",           # 伊平
    "宮城島", "宮城県", "宮城力",  # 宮城（宮城力は企業局長の氏名）
    "大村市",
    "空port",                     # ダミー（下で個別に扱う）
]
PORT_BLOCKERS = ["空港", "港湾", "漁港", "港区", "港町", "那覇港", "中城湾港"]

CONTEXT = 40   # 「北谷」がこの文字数以内にあることを条件にする


def q(sql: str) -> list[dict]:
    """psql で JSON を取り出す。追加の依存を増やさないための割り切り。"""
    out = subprocess.run(
        ["psql", "-d", DB, "-tAc", f"select coalesce(json_agg(t), '[]') from ({sql}) t"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout.strip())


def sentence_around(text: str, pos: int, width: int = 120) -> str:
    """一致箇所を含む一文を切り出す。長すぎる場合は前後を詰める。"""
    flat = re.sub(r"[\s　]+", " ", text)
    # 平坦化で位置がずれるので、原文側で文境界を探してから平坦化する
    starts = [m.end() for m in re.finditer(r"[。？！]", text[:pos])]
    start = starts[-1] if starts else 0
    end_m = re.search(r"[。？！]", text[pos:])
    end = pos + end_m.end() if end_m else min(len(text), pos + width)
    s = re.sub(r"[\s　]+", " ", text[start:end]).strip()
    if len(s) > width:
        rel = pos - start
        a = max(0, rel - width // 2)
        s = ("…" if a > 0 else "") + s[a:a + width] + ("…" if a + width < len(s) else "")
    return s


def find_areas(text: str) -> dict[str, int]:
    """発言テキストから北谷町の字への言及を拾う。

    「北谷」が近くにあることを条件にし、同名の他地名は BLOCKERS で落とす。
    """
    hits: dict[str, int] = {}
    chatan = [m.start() for m in re.finditer("北谷", text)]
    if not chatan:
        return hits

    for base, variants in AREAS.items():
        for v in variants:
            for m in re.finditer(re.escape(v), text):
                i = m.start()
                window = text[max(0, i - 12): i + len(v) + 12]
                if any(b in window for b in BLOCKERS):
                    continue
                if base == "港" and any(b in window for b in PORT_BLOCKERS):
                    continue
                # 「北谷」は町名としても出るので、丁目つきの表記だけを字として扱う
                if base == "北谷" and not re.search(r"北谷[一二１２]丁目", window):
                    continue
                if not any(abs(c - i) <= CONTEXT for c in chatan):
                    continue
                hits[base] = hits.get(base, 0) + 1
                break  # 1発言につき1字1回で数える
    return hits


def main() -> None:
    rows = q("""
        select mt.date::text as date, mt.session, mt.title, mt.source_url,
               s.speaker_raw as speaker, s.role, s.text
        from speeches s
        join meetings mt on mt.id = s.meeting_id
        join municipalities m on m.id = mt.municipality_id
        where m.name = '沖縄県' and s.text like '%北谷%'
        order by mt.date, s.seq
    """)

    town, area_hits = [], {}
    for r in rows:
        text = r["text"]
        pos = text.find("北谷")
        item = {
            "date": r["date"],
            "title": r["title"] or r["session"],
            "speaker": r["speaker"],
            "role": r["role"],
            "excerpt": sentence_around(text, pos),
            "url": r["source_url"],
        }
        areas = find_areas(text)
        item["areas"] = sorted(areas)
        town.append(item)
        for a in areas:
            area_hits.setdefault(a, []).append(item)

    data = {
        "council": "沖縄県議会",
        "coverage": "令和8年第1回沖縄県議会（2月定例会）本会議",
        "note": (
            "沖縄県議会の会議録から「北谷」を含む発言を抽出したもの。"
            "字（あざ）まで特定できた発言だけを区域に紐づけている。"
            "北谷町議会の会議録は会議録検索システムの取得条件を確認中のため未収録。"
        ),
        "town_mentions": town,
        "area_counts": {k: len(v) for k, v in sorted(area_hits.items())},
        "area_mentions": {k: v for k, v in sorted(area_hits.items())},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chatan_speeches.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    print(f"北谷町に触れた発言 {len(town)} 件")
    print("字が特定できたもの: " + (
        " / ".join(f"{k} {len(v)}件" for k, v in area_hits.items()) or "なし"))
    for t in town:
        print(f"  {t['date']} {t['speaker']}: {t['excerpt'][:70]}  →{t['areas'] or '町全体'}")


if __name__ == "__main__":
    main()
