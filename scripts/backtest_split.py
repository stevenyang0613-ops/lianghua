#!/usr/bin/env python3
"""
样本外验证：train/validation/test 三段切分

功能：
1. 自动检测是否有 backtest CSV 缓存
2. 如果有 → 直接分析（快速）
3. 如果没有 → 复制 _archive 脚本到 /tmp/，运行完整 backtest，然后分析

三段切分：
- Train:      2022-06-24 ~ 2023-06-30  (12 个月，熊市)
- Validation: 2023-07-01 ~ 2024-06-30  (12 个月，震荡)
- Test:       2024-07-01 ~ 2026-06-23  (24 个月，真正样本外，含 9月反弹)
"""
import os
import sys
import shutil
import subprocess
from datetime import date, timedelta
import pandas as pd

CSV_PATH = '/Users/mac/lianghua/timing_backtest_ultimate.csv'
ARCHIVE_SCRIPT = '/Users/mac/lianghua/_archive/scripts/timing_backtest_ultimate.py'
TMP_DIR = '/tmp/lianghua_backtest'


def ensure_csv() -> str:
    """确保有 backtest CSV，没有则触发运行"""
    if os.path.exists(CSV_PATH):
        age_hours = (pd.Timestamp.now() - pd.Timestamp(os.path.getmtime(CSV_PATH), unit='s')).total_seconds() / 3600
        if age_hours < 24:
            print(f"✅ 使用现有 CSV（{age_hours:.1f}h 前生成）")
            return CSV_PATH
        else:
            print(f"⚠️  CSV 已 {age_hours:.1f}h 前生成，将重新运行")
    print(f"📊 无可用 CSV，触发完整 backtest...")
    # 复制脚本到 /tmp/（避开 .gitignore）
    os.makedirs(TMP_DIR, exist_ok=True)
    tmp_script = os.path.join(TMP_DIR, 'timing_backtest_ultimate.py')
    shutil.copy(ARCHIVE_SCRIPT, tmp_script)
    # 复制 timing_cache.db
    cache_src = '/Users/mac/lianghua/backend/data/timing_cache.db'
    cache_dst = os.path.join(TMP_DIR, 'data')
    os.makedirs(cache_dst, exist_ok=True)
    if os.path.exists(cache_src):
        shutil.copy(cache_src, os.path.join(cache_dst, 'timing_cache.db'))
    # 在 /tmp/ 运行
    cwd_old = os.getcwd()
    try:
        os.chdir(TMP_DIR)
        # 创建软链接：backend → 原 backend（让脚本能 import app.strategies...）
        if not os.path.exists('backend'):
            os.symlink('/Users/mac/lianghua/backend', 'backend')
        env = os.environ.copy()
        env['PYTHONPATH'] = TMP_DIR + ':' + env.get('PYTHONPATH', '')
        result = subprocess.run(
            [sys.executable, tmp_script],
            capture_output=True, text=True, env=env, timeout=600
        )
        if result.returncode != 0:
            print(f"❌ backtest 失败: {result.stderr[-500:]}")
            sys.exit(1)
        # 复制 CSV 回工作目录
        generated = os.path.join(TMP_DIR, 'timing_backtest_ultimate.csv')
        if os.path.exists(generated):
            shutil.copy(generated, CSV_PATH)
            print(f"✅ Backtest 完成，CSV 已保存到 {CSV_PATH}")
    finally:
        os.chdir(cwd_old)
    return CSV_PATH


def analyze_split():
    """执行三段切分分析"""
    csv_path = ensure_csv()
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])

    print("\n" + "=" * 70)
    print("样本外验证：train/validation/test 三段切分")
    print("=" * 70)

    periods = [
        ('Train', date(2022, 6, 24), date(2023, 6, 30)),
        ('Validation', date(2023, 7, 1), date(2024, 6, 30)),
        ('Test', date(2024, 7, 1), date(2026, 6, 23)),
        ('Full', date(2022, 6, 24), date(2026, 6, 23)),
    ]

    print(f"\n{'Period':<14s} {'Days':>6s} {'策略(净)':>10s} {'BH':>10s} {'超额':>9s} {'仓位':>7s} {'月胜率':>7s}")
    print("-" * 75)

    results = {}
    for pname, pstart, pend in periods:
        mask = (df['date'] >= pd.Timestamp(pstart)) & (df['date'] <= pd.Timestamp(pend))
        sub = df[mask].copy()
        if len(sub) == 0:
            continue
        cum_strat = (1 + sub['strategy_return_net'].fillna(0)).prod() - 1
        cum_bh = (1 + sub['buyhold_return'].fillna(0)).prod() - 1
        avg_pos = sub['position_ratio'].mean()
        sub['month'] = sub['date'].dt.to_period('M')
        monthly_strat = sub.groupby('month').apply(
            lambda g: (1 + g['strategy_return_net'].fillna(0)).prod() - 1)
        monthly_bh = sub.groupby('month').apply(
            lambda g: (1 + g['buyhold_return'].fillna(0)).prod() - 1)
        monthly_win = (monthly_strat > monthly_bh).mean()
        print(f"  {pname:<12s} {len(sub):>6d} {cum_strat*100:>+9.2f}% {cum_bh*100:>+9.2f}% "
              f"{(cum_strat - cum_bh)*100:>+8.2f}% {avg_pos*100:>6.0f}% {monthly_win*100:>6.1f}%")
        results[pname] = {
            'cum_strat': cum_strat, 'cum_bh': cum_bh, 'avg_pos': avg_pos,
            'monthly_win_vs_bh': monthly_win, 'n_months': len(monthly_strat),
        }

    # 样本外稳健性分析
    print("\n" + "=" * 70)
    print("样本外稳健性分析")
    print("=" * 70)
    if all(k in results for k in ['Train', 'Validation', 'Test']):
        t, v, te = results['Train'], results['Validation'], results['Test']
        print(f"\n  收益序列: Train={t['cum_strat']*100:+.2f}% → Val={v['cum_strat']*100:+.2f}% → Test={te['cum_strat']*100:+.2f}%")
        print(f"  仓位序列: Train={t['avg_pos']*100:.0f}% → Val={v['avg_pos']*100:.0f}% → Test={te['avg_pos']*100:.0f}%")
        print(f"  跑赢BH:   Train={t['monthly_win_vs_bh']*100:.1f}% → Val={v['monthly_win_vs_bh']*100:.1f}% → Test={te['monthly_win_vs_bh']*100:.1f}%")
        print()
        if te['cum_strat'] > 0:
            print(f"  ✅ Test 期间正收益 ({te['cum_strat']*100:+.2f}%)，策略具备样本外 alpha")
        else:
            print(f"  ❌ Test 期间负收益 ({te['cum_strat']*100:+.2f}%)，样本外未通过验证")
        if te['cum_strat'] > v['cum_strat'] * 0.5:
            print(f"  ✅ Test 收益 ({te['cum_strat']*100:+.2f}%) ≥ Validation ({v['cum_strat']*100:+.2f}%) 的一半，无明显衰减")
        else:
            print(f"  ⚠️  Test 收益 ({te['cum_strat']*100:+.2f}%) < Validation ({v['cum_strat']*100:+.2f}%) 的一半，可能存在过拟合")
        if v['cum_strat'] > 0 and te['cum_strat'] < 0:
            print(f"  ⚠️  ⚠️  WARNING: Validation 期间跑赢 ({v['cum_strat']*100:+.2f}%) 但 Test 期间亏损 ({te['cum_strat']*100:+.2f}%)")
        if te['monthly_win_vs_bh'] >= 0.5:
            print(f"  ✅ Test 期间 {te['monthly_win_vs_bh']*100:.1f}% 月份跑赢 BH，稳健性良好")
        else:
            print(f"  ⚠️  Test 期间仅 {te['monthly_win_vs_bh']*100:.1f}% 月份跑赢 BH，需改进")


if __name__ == '__main__':
    analyze_split()
