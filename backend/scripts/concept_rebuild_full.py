"""Concept cache rebuild — EM (via proxy) + THS (names) + TDX (boards + keyword expansion).
Uses AKShare proxy patch to access EM push2 API.
Completes in ~5 minutes for 494 EM concepts.
"""
import json, os, sys, time, logging, re as _re, random
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("concept_rebuild")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_CACHE_DIR = Path.home() / ".lianghua" / "data_cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
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
    "3D": ["3D"], "5G": ["5G"], "6G": ["6G"], "ST": ["ST"],
    "中字头": ["中"], "含H股": ["H股"], "含可转债": ["转债"],
    "破净": ["破净"], "举牌": ["举牌"], "股权转让": ["股权"],
    "一带一路": ["一带"], "雄安": ["雄安"], "大湾区": ["湾区"],
    "央企": ["央企"], "国企": ["国企"],
    "跨境电商": ["跨境"], "数字经济": ["数字"],
    "元宇宙": ["元宇"], "氢能": ["氢"], "中药": ["中药"],
    "创新药": ["创新药"], "医美": ["医美"], "预制菜": ["预制"],
    "养鸡": ["养鸡"], "猪肉": ["猪肉"], "白酒": ["白酒"],
    "华为": ["华为"], "小米": ["小米"], "苹果": ["苹果"],
    "腾讯": ["腾讯"], "百度": ["百度"], "阿里": ["阿里", "蚂蚁"],
    "拼多多": ["拼多多"], "抖音": ["抖音", "字节"],
    "快手": ["快手"], "小红书": ["小红书"],
    "脑机": ["脑机"], "减速器": ["减速"], "超导": ["超导"],
    "核聚变": ["聚变"], "光刻": ["光刻"], "免税": ["免税"],
    "区块链": ["区块链"], "云计算": ["云计算", "云"],
    "机器人": ["机器人"], "机床": ["机床"],
    "OLED": ["OLED"], "PCB": ["PCB"], "WiFi": ["WiFi"],
    "MiniLED": ["MiniLED"], "NFT": ["NFT"], "CPO": ["CPO"],
    "充电桩": ["充电桩"], "换电": ["换电"],
    "低空": ["低空"], "飞行汽车": ["飞行"],
    "医美": ["医美"], "辅助生殖": ["辅助生殖"],
    "草甘膦": ["草甘膦"], "钛白": ["钛白"],
    "煤炭": ["煤炭"], "化肥": ["化肥"],
    "页岩气": ["页岩"], "可燃冰": ["可燃冰"],
    "固废": ["固废"], "污水": ["污水"],
    "网约车": ["网约"], "共享单车": ["共享"],
    "养鸡": ["养鸡"], "禽流感": ["禽流感"],
    "流感": ["流感"], "消毒": ["消毒"],
    "粮食": ["粮食"], "大豆": ["大豆"], "玉米": ["玉米"],
    "足球": ["足球"], "赛马": ["赛马"],
    "烟草": ["烟草"], "染料": ["染料"],
    "环氧": ["环氧"], "丙烯": ["丙烯"],
}

def _extract_keywords(concept_name: str) -> list[str]:
    keywords = []
    for root, kws in _CONCEPT_KEYWORD_MAP.items():
        if root in concept_name:
            keywords.extend(kws)
    # Remove "概念" suffix for matching
    raw = concept_name.replace("概念", "").replace("板块", "").strip()
    if raw and len(raw) >= 2:
        keywords.append(raw)
    # Split compound words
    parts = _re.split(r'[/、·\s,，()（）]+', concept_name)
    for part in parts:
        part = part.strip()
        if len(part) >= 2 and part not in keywords:
            keywords.append(part)
    seen = set()
    return [k for k in keywords if not (k in seen or seen.add(k))][:8]


def main():
    result: dict[str, list[str]] = {}  # stock_code -> [concept_names]
    source_map: dict[str, dict[str, bool]] = {}  # concept_name -> {em, ths, tdx}
    start_time = time.time()

    # ── Step 1: EM concept boards (via proxy) ──
    import akshare as ak
    try:
        import akshare_proxy_patch
        from app.config import settings
        if settings.AKSHARE_PROXY_ENABLED:
            akshare_proxy_patch.install_patch(
                settings.AKSHARE_PROXY_GATEWAY,
                auth_token=settings.AKSHARE_PROXY_TOKEN,
                retry=settings.AKSHARE_PROXY_RETRY,
                hook_domains=[
                    "push2.eastmoney.com", "push2his.eastmoney.com",
                    "emweb.securities.eastmoney.com", "datacenter.eastmoney.com",
                    "82.push2.eastmoney.com", "17.push2.eastmoney.com",
                ],
            )
            logger.info("Proxy patch installed")
    except Exception as e:
        logger.warning(f"Proxy patch failed: {e}")

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
        logger.warning(f"EM board list failed: {e}")

    # Fetch EM concept constituents
    em_ok = 0
    em_fail = 0
    for idx, (bcode, bname) in enumerate(em_boards):
        cons = []
        try:
            df_cons = ak.stock_board_concept_cons_em(symbol=bcode)
            if df_cons is not None and not df_cons.empty:
                for _, c in df_cons.iterrows():
                    scode = str(c.get("代码", "")).strip().zfill(6)
                    if scode:
                        cons.append(scode)
        except Exception:
            em_fail += 1

        if cons:
            for scode in cons:
                result.setdefault(scode, []).append(bname)
            source_map.setdefault(bname, {"em": False, "ths": False, "tdx": False})["em"] = True
            em_ok += 1
        else:
            source_map.setdefault(bname, {"em": False, "ths": False, "tdx": False})

        if (idx + 1) % 50 == 0:
            logger.info(f"EM progress: {idx+1}/{len(em_boards)}, ok={em_ok}, fail={em_fail}, stocks={len(result)}")
        time.sleep(0.2 + random.random() * 0.3)

    logger.info(f"EM done: {em_ok}/{len(em_boards)} boards, {em_fail} failed, {len(result)} stocks")

    # ── Step 2: THS concept board names ──
    import requests as _req
    ths_names = []
    try:
        r = _req.get("http://q.10jqka.com.cn/gn/", headers=_HEADERS, timeout=15)
        if r.status_code == 200:
            for match in _re.finditer(
                r'href="http://q\.10jqka\.com\.cn/gn/detail/code/(\d+)/"[^>]* target="_blank">([^<]+)</a>', r.text):
                name = match.group(2).strip()
                if name:
                    ths_names.append(name)
                    source_map.setdefault(name, {"em": False, "ths": False, "tdx": False})["ths"] = True
        logger.info(f"THS board names: {len(ths_names)}")
    except Exception as e:
        logger.warning(f"THS board list failed: {e}")

    # ── Step 3: TDX concept boards (block_gn.dat) ──
    tdx_board_count = 0
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
                        source_map.setdefault(name, {"em": False, "ths": False, "tdx": False})["tdx"] = True
                        for code in valid:
                            if code in result:
                                if name not in result[code]:
                                    result[code].append(name)
                            else:
                                result[code] = [name]
                        tdx_board_count += 1
            else:
                api.disconnect()
    except Exception as e:
        logger.warning(f"TDX boards failed: {e}")
    logger.info(f"TDX boards: {tdx_board_count}")

    # ── Step 4: TDX keyword expansion for zero-stock concepts ──
    from app.adapters.tdx_adapter import get_tdx_adapter
    adapter = get_tdx_adapter()
    tdx_securities = adapter.fetch_all_securities(stock_only=True)
    logger.info(f"TDX securities: {len(tdx_securities)}")

    # Find concepts with 0 stocks
    concept_counts_before = Counter()
    for scode, concepts in result.items():
        for c in concepts:
            concept_counts_before[c] += 1
    zero_stock_concepts = [c for c in source_map if c not in concept_counts_before]
    logger.info(f"Expanding {len(zero_stock_concepts)} zero-stock concepts via TDX keywords...")

    keyword_added = 0
    keyword_filled = 0
    for cname in sorted(zero_stock_concepts):
        keywords = _extract_keywords(cname)
        if not keywords:
            continue
        added = 0
        for kw in keywords:
            kw_lower = kw.lower()
            for code, name in tdx_securities.items():
                if not code or len(code) != 6 or not code.isdigit():
                    continue
                if not name or code.startswith(('399', '880', '950')):
                    continue
                if kw_lower in name.lower():
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
        logger.info(f"TDX keywords: filled {keyword_filled} concepts, added {keyword_added} pairs")

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

    em_count = sum(1 for s in source_map.values() if s.get("em"))
    ths_count = sum(1 for s in source_map.values() if s.get("ths"))
    tdx_count = sum(1 for s in source_map.values() if s.get("tdx"))
    zeros = sum(1 for c in source_map if c not in concept_counts)

    dist = Counter()
    for n in concept_counts.values():
        if n <= 20: dist["<=20"] += 1
        elif n <= 50: dist["21-50"] += 1
        elif n <= 100: dist["51-100"] += 1
        elif n <= 200: dist["101-200"] += 1
        else: dist["200+"] += 1

    logger.info(f"\n{'='*50}")
    logger.info(f"Done in {elapsed:.0f}s")
    logger.info(f"Concepts: {len(concept_counts)}/{len(source_map)} ({zeros} zero-stock)")
    logger.info(f"Stocks: {len(result)}, pairs: {sum(concept_counts.values())}")
    logger.info(f"Sources: EM={em_count}, THS={ths_count}, TDX={tdx_count}")
    logger.info(f"Distribution: {dict(sorted(dist.items()))}")
    logger.info(f"Exactly-50 problem: {sum(1 for n in concept_counts.values() if n==50)} concepts")
    logger.info("Top 10:")
    for name, count in concept_counts.most_common(10):
        src = source_map.get(name, {})
        tags = []
        if src.get("em"): tags.append("EM")
        if src.get("ths"): tags.append("THS")
        if src.get("tdx"): tags.append("TDX")
        logger.info(f"  {count:5d} - {name} [{','.join(tags)}]")
    logger.info(f"{'='*50}")

if __name__ == "__main__":
    main()
