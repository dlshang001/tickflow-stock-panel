"""大喵票池批量录入 —— 从群主预案文本解析出股票列表。

纯正则 + instruments 维表匹配,不依赖 LLM(更快、零成本、结果确定):
  1. 抽取六位代码(如 600085 / 600085.SH / $同仁堂(SH600085)$)
  2. 对代码无法覆盖的行,用 instruments 名称做子串匹配(如"同仁堂")
  3. 按关键词推断分类(新观察/新开仓/持仓处理/老等票/做T/止盈/止损)
  4. 保留每行的描述作为 note/strategy

返回候选列表,由前端预览确认后再写入(避免误匹配直接落库)。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 名称索引缓存(instruments 不常变,避免每次解析都重建)
_name_index_cache: dict = {}

# 六位代码,兼容 SH/SZ/BJ 前后缀、OCR 把 . 识别成空格等
_CODE_RE = re.compile(r"(?<!\d)(?:sh|sz|bj)?[\s.]?(\d{6})(?:\.(?:sh|sz|bj))?(?!\d)", re.IGNORECASE)
# 形如 (SH600085) / （SZ000001） 的带交易所前缀写法
_CODE_PREFIX_RE = re.compile(r"[（(]\s*(sh|sz|bj)\s*(\d{6})\s*[）)]", re.IGNORECASE)

# 分类关键词 → category(命中即归类,按顺序优先)
_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("take_profit", ("止盈", "高抛", "卖出", "落袋", "获利了结")),
    ("stop_loss", ("止损", "割肉", "破位走", "离场")),
    ("new_open", ("新开仓", "开仓", "买入", "建仓", "低吸", "打板")),
    ("t_add", ("做t", "做T", "加仓", "t加", "T加", "补仓")),
    ("holding_todo", ("持仓", "持有", "待处理", "处理", "持仓待")),
    ("old_deng", ("老等", "老登", "老仓", "继续等")),
    ("new_watch", ("新观察", "观察", "加入观察", "关注", "可看", "留意", "备选", "试仓")),
]

# 名称匹配时排除的高频非股票词(避免误命中)
_NAME_BLOCKLIST = {
    "今日", "明天", "今天", "大盘", "板块", "指数", "涨停", "跌停", "收盘", "开盘",
    "持仓", "观察", "关注", "做t", "加仓", "止损", "止盈", "开仓", "建仓", "买入",
    "卖出", "逻辑", "策略", "提示", "群主", "预案", "新观察", "新开仓", "可看",
    "中国", "股份", "集团", "科技", "新材", "电子", "能源", "医药", "银行", "证券",
    "继续", "试仓",
}


def _build_name_index(instruments_df) -> dict[str, list[tuple[str, str]]]:
    """构建 名称字串 → [(symbol, name)] 的索引。带缓存,instruments 行数变化时刷新。

    返回 dict:名称(如"同仁堂") → [(symbol, full_name)],list 用于兼容同名(极少)。
    """
    cache_key = instruments_df.height
    if _name_index_cache.get("key") == cache_key and _name_index_cache.get("idx"):
        return _name_index_cache["idx"]

    index: dict[str, list[tuple[str, str]]] = {}
    for rec in instruments_df.select(["symbol", "name"]).to_dicts():
        sym = rec.get("symbol")
        name = (rec.get("name") or "").strip()
        if not sym or not name:
            continue
        # 去掉名称里的 *ST/ST 前缀做一个别名,同时保留原名
        clean = re.sub(r"^\*?ST", "", name).strip()
        for n in {name, clean}:
            if len(n) < 2:
                continue
            index.setdefault(n, []).append((str(sym), name))

    _name_index_cache["key"] = cache_key
    _name_index_cache["idx"] = index
    return index


def _match_by_name(line: str, name_index: dict[str, list[tuple[str, str]]]) -> tuple[str, str] | None:
    """在一行文本里找股票名称(最长优先,避免"东方"误命中"东方财富"的子串)。"""
    candidates: list[tuple[int, str, list[tuple[str, str]]]] = []
    for name, pairs in name_index.items():
        if name in _NAME_BLOCKLIST or len(name) < 2:
            continue
        idx = line.find(name)
        if idx >= 0:
            candidates.append((len(name), name, pairs))
    if not candidates:
        return None
    # 名称越长越精确,优先
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, name, pairs = candidates[0]
    sym, full_name = pairs[0]
    return sym, full_name


def _detect_category(text: str) -> tuple[str, str]:
    """根据整行关键词推断分类。返回 (category, 命中的关键词)。"""
    for category, keywords in _CATEGORY_RULES:
        for kw in keywords:
            if kw in text:
                return category, kw
    return "new_watch", ""


def parse_text(text: str, instruments_df) -> list[dict]:
    """解析预案文本为候选股票列表。

    每行最多产出一条;按行去重(同 symbol 不同行只保留首个,但 note 合并)。
    返回:[{"symbol","name","category","note","raw","matched_by"}]
    """
    name_index = _build_name_index(instruments_df)
    results: list[dict] = []
    seen: dict[str, int] = {}  # symbol -> results 下标

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 2:
            continue

        symbol = None
        name = ""
        matched_by = ""

        # 1. 优先抽六位代码
        code_match = _CODE_PREFIX_RE.search(line)
        if code_match:
            code = code_match.group(2)
            symbol = _code_to_symbol(code, name_index)
            matched_by = "code"
        else:
            m = _CODE_RE.search(line)
            if m:
                code = m.group(1)
                symbol = _code_to_symbol(code, name_index)
                matched_by = "code"

        # 2. 代码没命中,用名称匹配
        if not symbol:
            hit = _match_by_name(line, name_index)
            if hit:
                symbol, name = hit
                matched_by = "name"

        if not symbol:
            continue

        # 3. 名称回填(代码命中时查 name)
        if not name:
            for pairs in name_index.values():
                for sym, nm in pairs:
                    if sym == symbol:
                        name = nm
                        break
                if name:
                    break

        category, kw = _detect_category(line)
        # note 去掉代码/名称本身,保留描述
        note = line
        if symbol:
            note = re.sub(r"(?<!\d)\d{6}(?!\d)", "", note)
        note = re.sub(r"[\s（）()\[\]【】.SHZBJE]+$", "", note).strip(" ，,、")
        # 去掉命中的股票名本身,避免 note 里重复
        if name and name in note:
            note = note.replace(name, "", 1).strip(" ，,、:：-")
        note = note[:200]

        if symbol in seen:
            # 同票重复行:合并 note,不重复添加
            existing = results[seen[symbol]]
            if note and note not in (existing.get("note") or ""):
                existing["note"] = ((existing.get("note") or "") + " / " + note).strip(" /")
            continue

        seen[symbol] = len(results)
        results.append({
            "symbol": symbol,
            "name": name,
            "category": category,
            "category_hint": kw,
            "note": note,
            "raw": line,
            "matched_by": matched_by,
        })

    return results


def _code_to_symbol(code: str, name_index: dict[str, list[tuple[str, str]]]) -> str | None:
    """六位代码 → 标准 symbol(如 600085 → 600085.SH)。通过 name_index 反查精确后缀。"""
    # 在索引里找以该代码开头的 symbol
    for pairs in name_index.values():
        for sym, _nm in pairs:
            if sym.split(".")[0] == code:
                return sym
    return None
