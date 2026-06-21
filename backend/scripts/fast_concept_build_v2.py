"""Fast concept cache build v2.
Strategy:
  1. Get ALL concept board NAMES from THS + EM (HTTP, no constituent fetching)
  2. Download TDX concept boards from block_gn.dat (pytdx direct)
  3. For EACH concept from THS/EM, use TDX keyword expansion to find stocks
  4. Merge all sources
  5. Save cache
Total time: ~2 minutes (vs 20+ minutes for full constituent fetch)
"""
import json, os, sys, time, logging, random, re as _re
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fast_concept_v2")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests as _req
from app.adapters.tdx_adapter import get_tdx_adapter

_CACHE_DIR = Path.home() / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

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

# ── Step 1: Get THS concept board names ──
def fetch_ths_board_names():
    boards = []
    try:
        r = _req.get("http://q.10jqka.com.cn/gn/", headers=_HEADERS, timeout=15)
        if r.status_code == 200:
            for match in _re.finditer(
                r'href="http://q\.10jqka\.com\.cn/gn/detail/code/(\d+)/"[^>]* target="_blank">([^<]+)</a>', r.text):
                name = match.group(2).strip()
                if name:
                    boards.append(name)
    except Exception as e:
        logger.warning(f"THS board list failed: {e}")
    return boards

def main():
    result: dict[str, list[str]] = {}
    source_map: dict[str, dict[str, bool]] = {}
    all_concept_names: set[str] = set()
    start_time = time.time()

    # ── Step 1: THS concept board names ──
    logger.info("Step 1: Fetching THS board names (HTTP)...")
    ths_names = fetch_ths_board_names()
    for name in ths_names:
        all_concept_names.add(name)
        source_map.setdefault(name, {"em": False, "ths": True, "tdx": False})
    logger.info(f"THS: {len(ths_names)} board names")

    # ── Step 2: TDX concept boards (block_gn.dat via pytdx) ──
    logger.info("Step 2: Loading TDX concept boards (pytdx)...")
    try:
        from pytdx.hq import TdxHq_API
        from pytdx.reader.block_reader import BlockReader, BlockReader_TYPE_GROUP
        api = TdxHq_API()
        ok = api.connect("180.153.18.170", 7709, time_out=3.0)
        if ok:
            meta = api.get_block_info_meta(b"block_gn.dat")
            if meta and meta.get("size"):
                size = meta["size"]
                one_chunk = 0x7530
                chunks = size // one_chunk + (1 if size % one_chunk else 0)
                file_content = bytearray()
                for seg in range(chunks):
                    start = seg * one_chunk
                    piece_data = api.get_block_info(b"block_gn.dat", start, size)
                    file_content.extend(piece_data)
                api.disconnect()
                blocks = BlockReader().get_data(file_content, BlockReader_TYPE_GROUP)
                tdx_boards = {}
                for b in blocks:
                    if b.get("block_type") != 2:
                        continue
                    name = b.get("blockname", "").strip()
                    codes = b.get("code_list", "")
                    if not name:
                        continue
                    valid = [c.strip() for c in codes.split(",") if c.strip() and len(c.strip())==6 
                             and c.strip().isdigit() and not c.strip().startswith(("399","880","950"))]
                    if valid:
                        tdx_boards[name] = valid
                logger.info(f"TDX boards: {len(tdx_boards)}")
                for cname, codes in tdx_boards.items():
                    all_concept_names.add(cname)
                    source_map.setdefault(cname, {"em": False, "ths": False, "tdx": False})["tdx"] = True
                    for code in codes:
                        if code in result:
                            if cname not in result[code]:
                                result[code].append(cname)
                        else:
                            result[code] = [cname]
                logger.info(f"TDX boards added: {sum(len(v) for v in tdx_boards.values())} stock-board pairs")
            else:
                api.disconnect()
        else:
            logger.warning("TDX connection failed")
    except Exception as e:
        logger.warning(f"TDX boards failed: {e}")

    # ── Step 3: Fetch ALL TDX securities for keyword matching ──
    logger.info("Step 3: Loading TDX securities for keyword matching...")
    adapter = get_tdx_adapter()
    tdx_securities = adapter.fetch_all_securities(stock_only=True)
    logger.info(f"TDX securities: {len(tdx_securities)}")

    # ── Step 4: Keyword expansion for EACH concept ──
    logger.info(f"Step 4: Keyword expanding {len(all_concept_names)} concepts...")
    keyword_added = 0
    keyword_filled = 0
    for idx, cname in enumerate(sorted(all_concept_names)):
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
        logger.info(f"Step 4: expanded {keyword_filled} concepts, added {keyword_added} pairs")

    # ── Save ──
    save_result = dict(result)
    save_result["_ts"] = time.time()
    with open(_CACHE_DIR / "stock_concept.json", "w") as f:
        json.dump(save_result, f, ensure_ascii=False)
    logger.info(f"Saved: {len(save_result)-1} stocks")

    save_source = dict(source_map)
    save_source["_ts"] = time.time()
    with open(_CACHE_DIR / "stock_concept_source.json", "w") as f:
        json.dump(save_source, f, ensure_ascii=False)
    logger.info(f"Saved source map: {len(save_source)-1} concepts")

    # ── Stats ──
    elapsed = time.time() - start_time
    concept_counts = Counter()
    for scode, concepts in result.items():
        for c in concepts:
            concept_counts[c] += 1

    concepts_with_tdx = sum(1 for s in source_map.values() if s.get("tdx"))
    concepts_with_ths = sum(1 for s in source_map.values() if s.get("ths"))

    dist = Counter()
    for c, n in concept_counts.most_common():
        if n <= 20: dist["<=20"] = dist.get("<=20", 0) + 1
        elif n <= 50: dist["21-50"] = dist.get("21-50", 0) + 1
        elif n <= 100: dist["51-100"] = dist.get("51-100", 0) + 1
        elif n <= 200: dist["101-200"] = dist.get("101-200", 0) + 1
        else: dist["200+"] = dist.get("200+", 0) + 1

    logger.info(f"\n{'='*50}")
    logger.info(f"Done in {elapsed:.0f}s")
    logger.info(f"Concepts: {len(concept_counts)} (THS={concepts_with_ths}, TDX-boards={len(tdx_boards) if 'tdx_boards' in dir() else '?'}, TDX-expanded={concepts_with_tdx})")
    logger.info(f"Stocks in concepts: {len(result)}")
    logger.info(f"Distribution: {dict(sorted(dist.items()))}")
    logger.info("Top 10 concepts:")
    for name, count in concept_counts.most_common(10):
        src = source_map.get(name, {})
        markers = []
        if src.get("ths"): markers.append("THS")
        if src.get("tdx"): markers.append("TDX")
        logger.info(f"  {count:4d} stocks - {name} [{','.join(markers)}]")
    logger.info(f"{'='*50}")

if __name__ == "__main__":
    main()
