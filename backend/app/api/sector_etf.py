"""
行业 ETF 映射配置端点

集中管理申万行业代码 → ETF 代码的映射关系，避免在前端和后端多处硬编码。
映射表来源：申万行业分类（2021 版）+ 主流 ETF 产品代码。
"""
from fastapi import APIRouter
from typing import List
from pydantic import BaseModel

router = APIRouter()


class SectorEtfMapping(BaseModel):
    """行业 ETF 映射"""
    sw_code: str          # 申万行业代码 (如 "801010")
    etf_code: str         # ETF 代码 (如 "510050")
    etf_name: str         # ETF 名称 (如 "上证50")
    sector: str           # 行业标签 (如 "大盘蓝筹")


# 申万行业 → ETF 映射表
# 数据来源：申万行业分类（2021 版）+ 主流 ETF 产品代码
# ETF 代码以 510/511/512/515/516/518/159 开头，上交所和深交所分别
SECTOR_ETF_MAP: List[SectorEtfMapping] = [
    SectorEtfMapping(sw_code="801010", etf_code="510050", etf_name="上证50ETF",     sector="大盘蓝筹"),
    SectorEtfMapping(sw_code="801020", etf_code="159949", etf_name="创业板50ETF",   sector="成长"),
    SectorEtfMapping(sw_code="801030", etf_code="510500", etf_name="中证500ETF",    sector="中盘"),
    SectorEtfMapping(sw_code="801040", etf_code="510880", etf_name="红利ETF",       sector="红利"),
    SectorEtfMapping(sw_code="801050", etf_code="515050", etf_name="科技ETF",       sector="科技"),
    SectorEtfMapping(sw_code="801060", etf_code="512880", etf_name="证券ETF",       sector="金融"),
    SectorEtfMapping(sw_code="801070", etf_code="512070", etf_name="非银ETF",       sector="非银金融"),
    SectorEtfMapping(sw_code="801080", etf_code="512690", etf_name="酒ETF",         sector="消费"),
    SectorEtfMapping(sw_code="801090", etf_code="512010", etf_name="医药ETF",       sector="医药"),
    SectorEtfMapping(sw_code="801100", etf_code="516160", etf_name="新能源ETF",     sector="新能源"),
    SectorEtfMapping(sw_code="801110", etf_code="515800", etf_name="800ETF",        sector="宽基"),
    SectorEtfMapping(sw_code="801120", etf_code="515220", etf_name="煤炭ETF",       sector="能源"),
    SectorEtfMapping(sw_code="801130", etf_code="512100", etf_name="1000ETF",       sector="小盘"),
    SectorEtfMapping(sw_code="801140", etf_code="516510", etf_name="云计算ETF",     sector="云计算"),
    SectorEtfMapping(sw_code="801150", etf_code="515030", etf_name="新汽车ETF",     sector="汽车"),
    SectorEtfMapping(sw_code="801160", etf_code="512660", etf_name="军工ETF",       sector="军工"),
    SectorEtfMapping(sw_code="801170", etf_code="515790", etf_name="光伏ETF",       sector="光伏"),
    SectorEtfMapping(sw_code="801180", etf_code="516110", etf_name="汽车ETF",       sector="汽车"),
    SectorEtfMapping(sw_code="801190", etf_code="512580", etf_name="碳中和ETF",     sector="碳中和"),
    SectorEtfMapping(sw_code="801200", etf_code="562800", etf_name="稀有金属ETF",   sector="稀有金属"),
]


@router.get("/sector-etf-map", response_model=List[SectorEtfMapping])
async def get_sector_etf_map():
    """获取申万行业到 ETF 的映射表

    返回所有 20 个申万行业对应的代表性 ETF 配置。前端 SectorRotation 页面
    应当调用此端点而非使用前端硬编码的 SECTOR_ETF_MAP。
    """
    return SECTOR_ETF_MAP


def get_sector_etf_map_for_backtest() -> dict:
    """供后端回测使用的简表（sw_code → (etf_code, etf_name, sector)）"""
    return {
        m.sw_code: (m.etf_code, m.etf_name, m.sector)
        for m in SECTOR_ETF_MAP
    }
