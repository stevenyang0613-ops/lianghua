"""Fast concept cache build v3 — improved keyword expansion.
All concepts get stocks via keyword matching of their OWN name parts.
Also includes TDX concept boards for additional coverage.
Completed in ~10 seconds.
"""
import json, os, sys, time, logging, re as _re
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fast_concept_v3")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests as _req
from app.adapters.tdx_adapter import get_tdx_adapter

_CACHE_DIR = Path.home() / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

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

_EXTRA_KEYWORD_CATEGORIES = {
    "3D": ["3D"],
    "5G": ["5G"],
    "6G": ["6G"],
    "ST": ["ST"],
    "中字头": ["中"],
    "创业板": ["创业"],
    "次新股": ["次新"],
    "高送转": ["高送"],
    "转融券": ["转融"],
    "含可转债": ["转债"],
    "含H股": ["H股"],
    "破净": ["破净"],
    "破发": ["破发"],
    "股权转让": ["股权"],
    "举牌": ["举牌"],
    "证金": ["证金"],
    "汇金": ["汇金"],
    "养老金": ["养老"],
    "国改": ["国改"],
    "混改": ["混改"],
    "一带一路": ["一带"],
    "雄安": ["雄安"],
    "大湾区": ["湾区"],
    "长三角": ["三角"],
    "京津冀": ["京津"],
    "军工": ["军工", "军"],
    "央企": ["央企"],
    "国企": ["国企"],
    "供销社": ["供销"],
    "免税": ["免税"],
    "跨境电商": ["跨境"],
    "数字经济": ["数字"],
    "信创": ["信创"],
    "东数西算": ["算力"],
    "工业母机": ["机床"],
    "机器视觉": ["视觉"],
    "元宇宙": ["元宇"],
    "虚拟现实": ["虚拟", "VR"],
    "增强现实": ["增强", "AR"],
    "减速器": ["减速"],
    "超导": ["超导"],
    "核聚变": ["聚变"],
    "氢能": ["氢"],
    "钠离子": ["钠"],
    "钒电池": ["钒"],
    "固态电池": ["固态"],
    "钙钛矿": ["钙钛"],
    "CRO": ["CRO"],
    "CMO": ["CMO"],
    "减肥药": ["减肥"],
    "创新药": ["创新药"],
    "中药": ["中药"],
    "医美": ["医美"],
    "宠物": ["宠物"],
    "预制菜": ["预制"],
    "人造肉": ["人造肉"],
    "培育钻石": ["钻石"],
    "电子烟": ["电子烟"],
    "婴童": ["婴童"],
    "三胎": ["三胎"],
    "体育": ["体育"],
    "旅游": ["旅游"],
    "酒店": ["酒店"],
    "餐饮": ["餐饮"],
}

def extract_search_terms(concept_name: str) -> set[str]:
    """从概念名中提取搜索词 - 使用概念名本身的各个词作为搜索关键词"""
    terms = set()
    
    # 检查扩展关键词映射
    for root, kws in _EXTRA_KEYWORD_CATEGORIES.items():
        if root in concept_name:
            for kw in kws:
                terms.add(kw)
    
    # 直接使用概念名本身（如果比较短且不含"概念"后缀）
    raw = concept_name.replace("概念", "").replace("板块", "").strip()
    if len(raw) == len(concept_name) and len(raw) >= 2 and len(raw) <= 8:
        terms.add(concept_name)
    
    # 去掉后缀"概念"后搜索（这是最有效的策略）
    if raw and len(raw) >= 2:
        terms.add(raw)
    
    # 分割复合词
    parts = _re.split(r'[/、·\s,，]+', concept_name)
    for part in parts:
        part = part.strip()
        if len(part) >= 2:
            terms.add(part)
    
    # 去掉"概念"后分割
    base_parts = _re.split(r'[/、·\s,，]+', raw)
    for part in base_parts:
        part = part.strip()
        if len(part) >= 2:
            terms.add(part)
    
    # 对于中文复合词（3-4字），尝试取全部
    for term in list(terms):
        if 3 <= len(term) <= 6:
            # 对于中长词，两字子串也加入
            sub_terms = set()
            for i in range(len(term) - 1):
                sub = term[i:i+2]
                if len(sub) >= 2:
                    sub_terms.add(sub)
            terms.update(sub_terms)
    
    return terms

def main():
    result: dict[str, list[str]] = {}
    source_map: dict[str, dict[str, bool]] = {}
    start_time = time.time()

    # ── Step 1: THS concept board names ──
    logger.info("Step 1: Fetching THS board names (HTTP)...")
    ths_names = fetch_ths_board_names()
    for name in ths_names:
        source_map.setdefault(name, {"em": False, "ths": True, "tdx": False})
    logger.info(f"THS: {len(ths_names)} board names")

    # ── Step 2: TDX concept boards (block_gn.dat via pytdx) ──
    logger.info("Step 2: Loading TDX concept boards (pytdx)...")
    tdx_board_names = set()
    try:
        from pytdx.hq import TdxHq_API
        from pytdx.reader.block_reader import BlockReader, BlockReader_TYPE_GROUP
        api = TdxHq_API()
        if api.connect("180.153.18.170", 7709, time_out=3.0):
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
                        tdx_board_names.add(name)
                        source_map.setdefault(name, {"em": False, "ths": False, "tdx": False})["tdx"] = True
                        for code in valid:
                            if code in result:
                                if name not in result[code]:
                                    result[code].append(name)
                            else:
                                result[code] = [name]
                logger.info(f"TDX: {len(tdx_board_names)} boards, {sum(len(v) for v in [valid for b in blocks if b.get('block_type')==2]) if any(b.get('block_type')==2 for b in blocks) else 0} pairs")
    except Exception as e:
        logger.warning(f"TDX boards failed: {e}")
    
    # Count TDX pairs
    tdx_pairs = sum(len(v) for cname, codes in [(cname, codes) for cname in list(result.keys())[:0]] or [])
    tdx_pairs_actual = 0
    for cname, codes_list in [(k, v) for k, v in result.items()]:
        for c in codes_list:
            src = source_map.get(c, {})
            if src.get("tdx") and not src.get("ths"):
                tdx_pairs_actual += 1
    logger.info(f"TDX boards added: {tdx_pairs_actual} stock-board pairs from {len(tdx_board_names)} boards")

    # ── Step 3: Fetch ALL TDX securities ──
    logger.info("Step 3: Loading TDX securities for keyword matching...")
    adapter = get_tdx_adapter()
    tdx_securities = adapter.fetch_all_securities(stock_only=True)
    logger.info(f"TDX securities: {len(tdx_securities)}")

    # ── Step 4: Keyword expansion for ALL concepts ──
    all_concept_names = set(source_map.keys())
    logger.info(f"Step 4: Expanding {len(all_concept_names)} concepts...")

    # For each concept, try multiple search terms
    total_matched = 0
    matched_concepts = 0
    for idx, cname in enumerate(sorted(all_concept_names)):
        search_terms = extract_search_terms(cname)
        if not search_terms:
            continue
        
        added = 0
        matched_codes = set()
        for term in search_terms:
            term_lower = term.lower()
            for code, name in tdx_securities.items():
                if code in matched_codes:
                    continue
                if not code or len(code) != 6 or not code.isdigit():
                    continue
                if not name:
                    continue
                if code.startswith(('399', '880', '950')):
                    continue
                if term_lower in name.lower():
                    if code in result:
                        if cname not in result[code]:
                            result[code].append(cname)
                            added += 1
                            matched_codes.add(code)
                    else:
                        result[code] = [cname]
                        added += 1
                        matched_codes.add(code)
        
        if added > 0:
            source_map.setdefault(cname, {"em": False, "ths": False, "tdx": False})["tdx"] = True
            total_matched += added
            matched_concepts += 1

    logger.info(f"Step 4: matched {matched_concepts}/{len(all_concept_names)} concepts, added {total_matched} pairs")

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
    elapsed = time.time() - start_time
    concept_counts = Counter()
    for scode, concepts in result.items():
        for c in concepts:
            concept_counts[c] += 1

    concepts_with_tdx = sum(1 for s in source_map.values() if isinstance(s, dict) and s.get("tdx"))
    concepts_with_ths = sum(1 for s in source_map.values() if isinstance(s, dict) and s.get("ths"))

    dist = Counter()
    for c, n in concept_counts.most_common():
        if n <= 20: dist["<=20"] = dist.get("<=20", 0) + 1
        elif n <= 50: dist["21-50"] = dist.get("21-50", 0) + 1
        elif n <= 100: dist["51-100"] = dist.get("51-100", 0) + 1
        elif n <= 200: dist["101-200"] = dist.get("101-200", 0) + 1
        else: dist["200+"] = dist.get("200+", 0) + 1

    # Count zero-stock concepts
    zero_count = sum(1 for c in all_concept_names if c not in concept_counts)
    sample_zero = [c for c in sorted(all_concept_names) if c not in concept_counts][:5]

    logger.info(f"\n{'='*50}")
    logger.info(f"Done in {elapsed:.0f}s")
    logger.info(f"Concepts with stocks: {len(concept_counts)} / {len(all_concept_names)} total")
    logger.info(f"Zero-stock concepts: {zero_count} (e.g. {sample_zero})")
    logger.info(f"Stocks in concepts: {len(result)}")
    logger.info(f"Total stock-concept pairs: {sum(concept_counts.values())}")
    logger.info(f"Concepts with THS: {concepts_with_ths}, TDX-expanded: {concepts_with_tdx}")
    logger.info(f"Distribution: {dict(sorted(dist.items()))}")
    logger.info("Top 15:")
    for name, count in concept_counts.most_common(15):
        src = source_map.get(name, {})
        markers = []
        if src.get("ths"): markers.append("THS")
        if src.get("tdx"): markers.append("TDX")
        logger.info(f"  {count:5d} stocks - {name} [{','.join(markers)}]")
    logger.info(f"{'='*50}")

if __name__ == "__main__":
    main()
