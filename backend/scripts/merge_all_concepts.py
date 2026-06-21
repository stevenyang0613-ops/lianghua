"""Merge all available concept data sources into one cache.
Sources:
  1. Existing partial THS/EM cache (if any)
  2. TDX concept file (tdx_concepts.json) - TDX's own concept classification
  3. TDX keyword expansion on ALL concept names
"""
import json, os, sys, time, logging
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("merge_concepts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.tdx_adapter import get_tdx_adapter

_CACHE_DIR = Path.home() / ".lianghua" / "data_cache"

_CONCEPT_KEYWORD_MAP = {
    "AI": ["智能", "AI", "人工", "算法", "深度"],
    "芯片": ["芯片", "半导体", "集成", "微", "晶圆"],
    "新能源": ["新能源", "光伏", "风电", "锂电", "电池", "充电"],
    "汽车": ["汽车", "汽配", "整车", "新能源车", "电动"],
    "医药": ["医药", "药", "医疗", "生物", "基因", "健康"],
    "金融": ["银行", "保险", "证券", "金融", "信托", "期货"],
    "科技": ["科技", "信息", "软件", "数字", "数据", "互联", "计算"],
    "通信": ["通信", "5G", "6G", "光", "星", "卫星"],
    "军工": ["军工", "国防", "航天", "航空", "装备"],
    "消费": ["消费", "食品", "饮料", "酒", "乳", "零售"],
    "地产": ["地产", "房产", "物业", "园区"],
    "电力": ["电力", "能源", "电网", "发电", "电气"],
    "化工": ["化工", "化学", "化纤", "材料", "石化"],
    "金属": ["金属", "有色", "钢铁", "黄金", "矿业", "合金"],
    "传媒": ["传媒", "影视", "游戏", "广告", "文化", "娱乐"],
    "机械": ["机械", "设备", "装备", "精密", "制造"],
    "环保": ["环保", "环境", "节能", "减排", "碳"],
    "农业": ["农业", "牧", "渔", "种", "粮", "林"],
    "建筑": ["建筑", "工程", "建设", "基建", "路桥"],
}

def _extract_keywords(concept_name: str) -> list[str]:
    keywords = []
    for root, kws in _CONCEPT_KEYWORD_MAP.items():
        if root in concept_name:
            keywords.extend(kws)
    parts = concept_name.replace('/', ' ').replace('、', ' ').replace('·', ' ').split()
    for part in parts:
        part = part.strip()
        if len(part) >= 2 and part not in keywords:
            keywords.append(part)
    seen = set()
    return [k for k in keywords if not (k in seen or seen.add(k))][:5]

def main():
    result: dict[str, list[str]] = {}  # stock_code -> [concept_names]
    source_map: dict[str, dict[str, bool]] = {}  # concept_name -> {em, ths, tdx}
    all_concept_names: set[str] = set()

    # ── Source 1: Existing THS/EM cache (if any) ──
    concept_path = _CACHE_DIR / "stock_concept.json"
    if concept_path.exists():
        cached = json.load(open(concept_path))
        cached.pop("_ts", None)
        for scode, concepts in cached.items():
            if isinstance(concepts, list):
                result[scode] = concepts
                for c in concepts:
                    all_concept_names.add(c)
        logger.info(f"Source 1 (existing cache): {len(result)} stocks, {len(all_concept_names)} concepts")

    # ── Source 2: TDX concept file ──
    tdx_concept_path = _CACHE_DIR / "tdx_concepts.json"
    if tdx_concept_path.exists():
        tdx_data = json.load(open(tdx_concept_path))
        tdx_data.pop("_ts", None)
        tdx_concepts_added = 0
        for cname, stock_codes in tdx_data.items():
            if not isinstance(stock_codes, list):
                continue
            cname = str(cname).strip()
            if not cname or len(cname) > 20:  # Filter out garbage
                continue
            all_concept_names.add(cname)
            for scode in stock_codes:
                scode = str(scode).strip().zfill(6)
                if len(scode) == 6 and scode.isdigit():
                    if scode in result:
                        if cname not in result[scode]:
                            result[scode].append(cname)
                            tdx_concepts_added += 1
                    else:
                        result[scode] = [cname]
                        tdx_concepts_added += 1
            source_map.setdefault(cname, {"em": False, "ths": False, "tdx": False})["tdx"] = True
        logger.info(f"Source 2 (TDX concepts): {len(tdx_data)} boards, {tdx_concepts_added} stock-concept pairs")

    # ── Source 3: TDX keyword expansion ──
    logger.info("Source 3: TDX keyword expansion...")
    adapter = get_tdx_adapter()
    tdx_securities = adapter.fetch_all_securities(stock_only=True)
    logger.info(f"TDX securities: {len(tdx_securities)}")

    keyword_added = 0
    keyword_filled = 0
    for cname in sorted(all_concept_names):
        keywords = _extract_keywords(cname)
        if not keywords:
            continue
        added = 0
        for kw in keywords:
            for code, name in tdx_securities.items():
                if not code or len(code) != 6 or not code.isdigit():
                    continue
                if not name:
                    continue
                if code.startswith(('399', '880', '950')):
                    continue
                if kw.lower() in name.lower():
                    if code in result:
                        if cname not in result[code]:
                            result[code].append(cname)
                            added += 1
                    else:
                        result[code] = [cname]
                        added += 1
        if added > 0:
            source_map.setdefault(cname, {"em": False, "ths": False, "tdx": False})["tdx"] = True
            keyword_added += added
            keyword_filled += 1

    if keyword_added:
        logger.info(f"Source 3: expanded {keyword_filled} concepts, added {keyword_added} pairs")

    # ── Save ──
    save_result = dict(result)
    save_result["_ts"] = time.time()
    with open(_CACHE_DIR / "stock_concept.json", "w") as f:
        json.dump(save_result, f, ensure_ascii=False)

    save_source = dict(source_map)
    save_source["_ts"] = time.time()
    with open(_CACHE_DIR / "stock_concept_source.json", "w") as f:
        json.dump(save_source, f, ensure_ascii=False)

    # ── Stats ──
    concept_counts = Counter()
    for scode, concepts in result.items():
        for c in concepts:
            concept_counts[c] += 1

    concepts_with_tdx = sum(1 for s in source_map.values() if s.get("tdx"))
    logger.info(f"\n{'='*50}")
    logger.info(f"Final: {len(concept_counts)} concepts, {len(result)} stocks")
    logger.info(f"Concepts with TDX source: {concepts_with_tdx}")

    dist = Counter()
    for c, n in concept_counts.most_common(50):
        if n <= 20: dist["<=20"] = dist.get("<=20", 0) + 1
        elif n <= 50: dist["21-50"] = dist.get("21-50", 0) + 1
        elif n <= 100: dist["51-100"] = dist.get("51-100", 0) + 1
        elif n <= 200: dist["101-200"] = dist.get("101-200", 0) + 1
        else: dist["200+"] = dist.get("200+", 0) + 1
    logger.info(f"Distribution (top 50): {dict(sorted(dist.items()))}")
    logger.info(f"Top 10 concepts: {concept_counts.most_common(10)}")
    logger.info(f"{'='*50}")

if __name__ == "__main__":
    main()
