"""TDX Concept Keyword Expansion — standalone script.
Reads existing concept cache, expands with TDX keyword matching,
and saves back. Much faster than re-fetching all THS/EM data."""
import json, os, sys, time, logging
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tdx_concept_expand")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.tdx_adapter import get_tdx_adapter

# Copy from data_enrich_runner.py
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

def _extract_concept_keywords(concept_name: str) -> list[str]:
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
    cache_dir = Path.home() / ".lianghua" / "data_cache"
    concept_path = cache_dir / "stock_concept.json"
    source_path = cache_dir / "stock_concept_source.json"

    # Load existing cache
    concept_data = {}
    if concept_path.exists():
        with open(concept_path) as f:
            concept_data = json.load(f)
        concept_data.pop("_ts", None)
        logger.info(f"Loaded existing concept cache: {len(concept_data)} stocks")

    source_map = {}
    if source_path.exists():
        with open(source_path) as f:
            source_map = json.load(f)
        source_map.pop("_ts", None)
        logger.info(f"Loaded source map: {len(source_map)} concepts")

    # Add tdx key to source_map if missing
    for cname in list(source_map.keys()):
        if "tdx" not in source_map[cname]:
            source_map[cname]["tdx"] = False

    # Build set of all concept names from concept_data
    all_concept_names = set()
    for scode, concepts in concept_data.items():
        if isinstance(concepts, list):
            for c in concepts:
                all_concept_names.add(c)
    logger.info(f"Found {len(all_concept_names)} unique concepts")

    # Fetch TDX securities
    logger.info("Fetching TDX securities...")
    t0 = time.time()
    adapter = get_tdx_adapter()
    tdx_securities = adapter.fetch_all_securities(stock_only=True)
    elapsed = time.time() - t0
    logger.info(f"TDX: {len(tdx_securities)} securities fetched in {elapsed:.1f}s")

    # TDX keyword expansion
    result = {k: list(v) if isinstance(v, list) else v for k, v in concept_data.items()}
    total_added = 0
    concepts_filled = 0

    for idx, cname in enumerate(sorted(all_concept_names)):
        keywords = _extract_concept_keywords(cname)
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
            total_added += added
            concepts_filled += 1

    # Save
    result["_ts"] = time.time()
    with open(concept_path, "w") as f:
        json.dump(result, f, ensure_ascii=False)
    logger.info(f"Saved concept cache: {len(result)-1} stocks")

    source_map["_ts"] = time.time()
    with open(source_path, "w") as f:
        json.dump(source_map, f, ensure_ascii=False)
    logger.info(f"Saved source map: {len(source_map)-1} concepts")

    # Stats
    concept_counts = Counter()
    for scode, concepts in result.items():
        if scode == "_ts": continue
        for c in concepts:
            concept_counts[c] += 1

    # Distribution
    dist = Counter()
    for c, n in concept_counts.most_common():
        if n <= 50: dist[f"<=50"] = dist.get("<=50", 0) + 1
        elif n <= 100: dist["51-100"] = dist.get("51-100", 0) + 1
        else: dist["100+"] = dist.get("100+", 0) + 1

    concepts_with_tdx = sum(1 for s in source_map.values() if isinstance(s, dict) and s.get("tdx"))
    logger.info(f"Final: {len(concept_counts)} concepts, {len(result)-1} stocks")
    logger.info(f"TDX: expanded {concepts_filled} concepts, added {total_added} stock-concept pairs")
    logger.info(f"Concepts with TDX source: {concepts_with_tdx}")
    logger.info(f"Distribution: {dict(dist)}")

if __name__ == "__main__":
    main()
