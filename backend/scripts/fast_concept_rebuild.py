"""Fast concept cache rebuild — uses AKShare for constituents with minimal delay,
plus TDX keyword expansion. Skips slow HTTP fallback pagination."""
import json, os, sys, time, logging, random
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fast_concept_rebuild")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import akshare as ak
from app.adapters.tdx_adapter import get_tdx_adapter

_CACHE_DIR = Path.home() / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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
    result: dict[str, list[str]] = {}
    source_map: dict[str, dict[str, bool]] = {}

    # ── Source 1: EM via AKShare ──
    em_boards = []
    try:
        df = ak.stock_board_concept_name_em()
        for _, board in df.iterrows():
            bcode = str(board.get("板块代码", "")).strip()
            bname = str(board.get("板块名称", "")).strip()
            if bcode and bname:
                em_boards.append((bcode, bname))
        logger.info(f"EM boards: {len(em_boards)}")
    except Exception as e:
        logger.warning(f"EM boards failed: {e}")

    em_ok = 0
    for bcode, bname in em_boards:
        try:
            cons_df = ak.stock_board_concept_cons_em(symbol=bcode)
            for _, c in cons_df.iterrows():
                scode = str(c.get("代码", "")).strip().zfill(6)
                if scode:
                    result.setdefault(scode, []).append(bname)
            source_map.setdefault(bname, {"em": False, "ths": False, "tdx": False})["em"] = True
            em_ok += 1
        except Exception:
            pass
    logger.info(f"EM done: {em_ok}/{len(em_boards)} boards, {len(result)} stocks")

    # ── Source 2: THS via AKShare ──
    ths_boards = []
    try:
        df = ak.stock_board_concept_name_ths()
        for _, board in df.iterrows():
            bcode = str(board.get("代码", "")).strip()
            bname = str(board.get("名称", "")).strip()
            if bcode and bname:
                ths_boards.append((bcode, bname))
        logger.info(f"THS boards from AKShare: {len(ths_boards)}")
    except Exception as e:
        logger.warning(f"THS AKShare failed: {e}")
        # HTTP fallback for board list
        import requests as _req, re as _re
        try:
            r = _req.get("http://q.10jqka.com.cn/gn/",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code == 200:
                for match in _re.finditer(
                    r'href="http://q\.10jqka\.com\.cn/gn/detail/code/(\d+)/"[^>]* target="_blank">([^<]+)</a>', r.text):
                    code = match.group(1).strip()
                    name = match.group(2).strip()
                    if code and name:
                        ths_boards.append((code, name))
                logger.info(f"THS boards from HTTP: {len(ths_boards)}")
        except Exception as e2:
            logger.error(f"THS HTTP fallback failed: {e2}")

    ths_ok = 0
    for idx, (bcode, bname) in enumerate(ths_boards):
        try:
            cons_df = ak.stock_board_concept_cons_ths(symbol=bcode)
            if cons_df is not None and not cons_df.empty:
                for _, c in cons_df.iterrows():
                    scode = str(c.get("代码", "") or c.get("code", "")).strip().zfill(6)
                    if scode:
                        result.setdefault(scode, []).append(bname)
                source_map.setdefault(bname, {"em": False, "ths": False, "tdx": False})["ths"] = True
                ths_ok += 1
        except Exception:
            pass

        if (idx + 1) % 50 == 0:
            _save_progress(result, source_map)
            logger.info(f"THS progress: {idx+1}/{len(ths_boards)}, {ths_ok} ok, {len(result)} stocks")
        time.sleep(0.3 + random.random() * 0.5)  # Gentle delay

    logger.info(f"THS done: {ths_ok}/{len(ths_boards)} boards")

    # ── Source 3: TDX keyword expansion ──
    logger.info("Starting TDX keyword expansion...")
    adapter = get_tdx_adapter()
    tdx_securities = adapter.fetch_all_securities(stock_only=True)
    if tdx_securities:
        all_concept_names = set(source_map.keys())
        logger.info(f"TDX: expanding {len(all_concept_names)} concepts")
        tdx_total_added = 0
        tdx_concepts_filled = 0
        for cname in sorted(all_concept_names):
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
                tdx_total_added += added
                tdx_concepts_filled += 1
        if tdx_total_added:
            logger.info(f"TDX: expanded {tdx_concepts_filled} concepts, added {tdx_total_added} pairs")
    else:
        logger.warning("TDX: no securities fetched")

    # ── Save ──
    _save_final(result, source_map)

def _save_progress(result, source_map):
    data = dict(result)
    data["_ts"] = time.time()
    with open(_CACHE_DIR / "stock_concept.json", "w") as f:
        json.dump(data, f, ensure_ascii=False)

def _save_final(result, source_map):
    data = dict(result)
    data["_ts"] = time.time()
    with open(_CACHE_DIR / "stock_concept.json", "w") as f:
        json.dump(data, f, ensure_ascii=False)

    src = dict(source_map)
    src["_ts"] = time.time()
    with open(_CACHE_DIR / "stock_concept_source.json", "w") as f:
        json.dump(src, f, ensure_ascii=False)

    concept_counts = Counter()
    for scode, concepts in result.items():
        for c in concepts:
            concept_counts[c] += 1

    concepts_with_tdx = sum(1 for s in source_map.values() if s.get("tdx"))
    logger.info(f"Final: {len(concept_counts)} concepts, {len(result)} stocks")
    logger.info(f"Concepts with TDX: {concepts_with_tdx}")
    # Distribution
    dist = Counter()
    for c, n in concept_counts.most_common():
        if n <= 20: dist["<=20"] = dist.get("<=20", 0) + 1
        elif n <= 50: dist["21-50"] = dist.get("21-50", 0) + 1
        elif n <= 100: dist["51-100"] = dist.get("51-100", 0) + 1
        else: dist["100+"] = dist.get("100+", 0) + 1
    logger.info(f"Distribution: {dict(sorted(dist.items()))}")
    # Sample
    logger.info(f"Top 5: {concept_counts.most_common(5)}")

if __name__ == "__main__":
    main()
