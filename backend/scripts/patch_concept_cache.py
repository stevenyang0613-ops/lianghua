"""Patch existing concept cache:
1. Fix EM source flags (set em=True for EM-originated concepts)
2. Merge EM data into THS concept names (e.g., "白酒" -> "白酒概念")
3. Fix "exactly 50" problem by supplementing with EM data
"""
import json, os, sys, time, logging, re as _re
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("patch_concepts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_CACHE_DIR = Path.home() / ".lianghua" / "data_cache"

def _normalize_concept_name(name: str) -> str:
    """Strip '概念'/'板块' suffix for matching"""
    return name.replace("概念", "").replace("板块", "").strip()

def main():
    concept_path = _CACHE_DIR / "stock_concept.json"
    source_path = _CACHE_DIR / "stock_concept_source.json"

    d = json.load(open(concept_path))
    d.pop("_ts", None)
    src = json.load(open(source_path))
    src.pop("_ts", None)

    # ── Step 1: Re-fetch EM board names via proxy ──
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
                ],
            )
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
        logger.error(f"EM board list failed: {e}")
        return

    # Build EM name -> THS name mapping
    em_to_ths: dict[str, str] = {}  # EM name -> best matching THS name
    ths_names = {n for n in src if src[n].get("ths")}
    em_names = {bname for _, bname in em_boards}

    for em_name in em_names:
        if em_name in ths_names:
            continue  # Exact match, no mapping needed
        em_norm = _normalize_concept_name(em_name)
        for ths_name in ths_names:
            ths_norm = _normalize_concept_name(ths_name)
            if em_norm == ths_norm:
                em_to_ths[em_name] = ths_name
                break

    logger.info(f"EM->THS name mappings: {len(em_to_ths)}")
    for em_name, ths_name in list(em_to_ths.items())[:10]:
        logger.info(f"  '{em_name}' -> '{ths_name}'")

    # ── Step 2: Fetch EM constituents and merge ──
    result = {k: list(v) if isinstance(v, list) else v for k, v in d.items()}
    source_map = dict(src)

    concept_counts = Counter()
    for scode, concepts in result.items():
        for c in concepts:
            concept_counts[c] += 1

    em_ok = 0
    em_added_total = 0
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
            pass

        if not cons:
            continue

        # Determine target concept name
        target_name = em_to_ths.get(bname, bname)

        # Mark EM source
        source_map.setdefault(target_name, {"em": False, "ths": False, "tdx": False})["em"] = True

        # Merge stocks into target concept
        added = 0
        for scode in cons:
            if scode in result:
                if target_name not in result[scode]:
                    result[scode].append(target_name)
                    added += 1
            else:
                result[scode] = [target_name]
                added += 1

        if added > 0:
            em_added_total += added
        em_ok += 1

        if (idx + 1) % 100 == 0:
            logger.info(f"EM progress: {idx+1}/{len(em_boards)}, ok={em_ok}, added={em_added_total}")
        time.sleep(0.15)

    logger.info(f"EM done: {em_ok}/{len(em_boards)}, added {em_added_total} stock-concept pairs")

    # ── Step 3: TDX keyword expansion for remaining zero/low-stock concepts ──
    concept_counts = Counter()
    for scode, concepts in result.items():
        for c in concepts:
            concept_counts[c] += 1

    low_stock = [c for c in source_map if concept_counts.get(c, 0) < 5]
    logger.info(f"Concepts with <5 stocks: {len(low_stock)}")

    if low_stock:
        from app.adapters.tdx_adapter import get_tdx_adapter
        adapter = get_tdx_adapter()
        tdx_securities = adapter.fetch_all_securities(stock_only=True)
        logger.info(f"TDX: {len(tdx_securities)} securities")

        from app.engine.data_enrich_runner import _extract_concept_keywords
        tdx_added = 0
        tdx_filled = 0
        for cname in sorted(low_stock):
            keywords = _extract_concept_keywords(cname)
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
                tdx_added += added
                tdx_filled += 1

        if tdx_added:
            logger.info(f"TDX keywords: filled {tdx_filled} concepts, added {tdx_added} pairs")

    # ── Save ──
    save_result = dict(result)
    save_result["_ts"] = time.time()
    with open(concept_path, "w") as f:
        json.dump(save_result, f, ensure_ascii=False)

    save_source = dict(source_map)
    save_source["_ts"] = time.time()
    with open(source_path, "w") as f:
        json.dump(save_source, f, ensure_ascii=False)

    # ── Final Stats ──
    concept_counts = Counter()
    for scode, concepts in result.items():
        for c in concepts:
            concept_counts[c] += 1

    em_count = sum(1 for s in source_map.values() if isinstance(s, dict) and s.get("em"))
    ths_count = sum(1 for s in source_map.values() if isinstance(s, dict) and s.get("ths"))
    tdx_count = sum(1 for s in source_map.values() if isinstance(s, dict) and s.get("tdx"))
    exact_50 = sum(1 for n in concept_counts.values() if n == 50)
    zeros = sum(1 for c in source_map if c not in concept_counts)

    dist = Counter()
    for n in concept_counts.values():
        if n <= 20: dist["<=20"] += 1
        elif n <= 50: dist["21-50"] += 1
        elif n <= 100: dist["51-100"] += 1
        elif n <= 200: dist["101-200"] += 1
        else: dist["200+"] += 1

    logger.info(f"\n{'='*50}")
    logger.info(f"Concepts: {len(concept_counts)} ({zeros} zero-stock)")
    logger.info(f"Stocks: {len(result)}, pairs: {sum(concept_counts.values())}")
    logger.info(f"Sources: EM={em_count}, THS={ths_count}, TDX={tdx_count}")
    logger.info(f"Exactly-50 problem: {exact_50} concepts")
    logger.info(f"Distribution: {dict(sorted(dist.items()))}")
    logger.info("Top 10:")
    for name, count in concept_counts.most_common(10):
        s = source_map.get(name, {})
        tags = []
        if s.get("em"): tags.append("EM")
        if s.get("ths"): tags.append("THS")
        if s.get("tdx"): tags.append("TDX")
        logger.info(f"  {count:5d} - {name} [{','.join(tags)}]")
    logger.info(f"{'='*50}")

if __name__ == "__main__":
    main()
