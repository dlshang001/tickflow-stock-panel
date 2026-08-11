"""AI Skill 注册表 — 自动发现、加载、查询所有内置 Skill。

使用方式:
    from app.ai_skills import registry

    # 列出所有 skill(可按 category 过滤)
    skills = registry.list_skills(category="settlement")

    # 获取并执行 skill
    skill = registry.get_skill("settlement_wyckoff")
    system_prompt, user_prompt = skill.run(params, context)

    # 获取某 category 的默认 skill
    default = registry.default_skill("settlement")

    # 校验/填充参数
    params = registry.validate_params(meta, raw_params)
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from app.ai_skills.base import AiSkillProtocol

logger = logging.getLogger(__name__)

_builtin_dir = Path(__file__).parent / "builtin"
_skill_cache: dict[str, dict[str, Any]] | None = None


class RegisteredSkill:
    """已注册 Skill 的容器,封装 META 与实例化对象。"""

    def __init__(self, meta: dict, skill_class: type[AiSkillProtocol]):
        self.meta = meta
        self._skill_class = skill_class
        self._instance: AiSkillProtocol | None = None

    @property
    def instance(self) -> AiSkillProtocol:
        """懒加载获取 Skill 实例(每次调用创建新实例,无状态)。"""
        if self._instance is None:
            self._instance = self._skill_class()
        return self._instance

    def run(self, params: dict, context: dict) -> tuple[str, str]:
        """执行 Skill,返回 (system_prompt, user_prompt)。

        Args:
            params: Skill 专属参数(建议先通过 validate_params 校验)
            context: 各域注入的数据

        Returns:
            (system_prompt, user_prompt) 元组
        """
        inst = self._skill_class()
        system_prompt = inst.build_system_prompt(params, context)
        user_prompt = inst.build_user_prompt(params, context)
        return system_prompt, user_prompt


def _discover_skills() -> dict[str, dict[str, Any]]:
    """扫描 builtin 目录,自动发现所有 Skill 并缓存。

    约定:
      - 每个 .py 文件(除 __init__ 外)被视为一个 Skill 模块
      - 模块必须导出 META dict 和一个以 Skill 结尾的类
      - META["id"] 作为唯一标识
    """
    global _skill_cache
    if _skill_cache is not None:
        return _skill_cache

    skills: dict[str, dict[str, Any]] = {}
    if not _builtin_dir.is_dir():
        _skill_cache = skills
        return skills

    for py_file in sorted(_builtin_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = py_file.stem
        try:
            mod = importlib.import_module(f"app.ai_skills.builtin.{module_name}")
            meta = getattr(mod, "META", None)
            if not meta or not isinstance(meta, dict):
                logger.warning("Skill %s: missing META dict, skipping", module_name)
                continue

            skill_class = None
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and attr_name.endswith("Skill"):
                    skill_class = attr
                    break
            if skill_class is None:
                logger.warning("Skill %s: no *Skill class found, skipping", module_name)
                continue

            skill_id = meta["id"]
            skills[skill_id] = {
                "meta": meta,
                "skill_class": skill_class,
                "module": mod,
            }
            logger.debug("Loaded skill: %s (%s, category=%s)", skill_id, meta.get("name"), meta.get("category"))

        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load skill from %s: %s", module_name, e)

    _skill_cache = skills
    return skills


def list_skills(category: str | None = None) -> list[dict[str, Any]]:
    """列出所有 Skill 的 META(可按 category 过滤)。

    Args:
        category: 可选过滤("market" / "holdings" / "settlement")

    Returns:
        META dict 列表,默认 skill 排在最前。
        每个 META 包含: id, name, category, description, tags, emoji, params, default_for_category
    """
    skills = _discover_skills()
    result = [info["meta"] for info in skills.values()]
    if category:
        result = [m for m in result if m.get("category") == category]
    # 默认 skill 排最前,其余按 id 排序
    return sorted(result, key=lambda m: (not m.get("default_for_category", False), m.get("id", "")))


def get_skill(skill_id: str) -> RegisteredSkill:
    """按 ID 获取 Skill 包装对象。

    Args:
        skill_id: Skill ID(如 "settlement_wyckoff")

    Returns:
        RegisteredSkill 对象,可调用 .run(params, context)

    Raises:
        ValueError: 当 skill_id 不存在时
    """
    skills = _discover_skills()
    info = skills.get(skill_id)
    if info is None:
        available = ", ".join(sorted(skills.keys()))
        raise ValueError(f"未知 Skill: {skill_id}. 可用: {available}")
    return RegisteredSkill(info["meta"], info["skill_class"])


def default_skill(category: str) -> dict[str, Any]:
    """获取某 category 的默认 Skill META。

    Args:
        category: "market" / "holdings" / "settlement"

    Returns:
        默认 Skill 的 META dict

    Raises:
        ValueError: 该 category 无默认 skill
    """
    for meta in list_skills(category):
        if meta.get("default_for_category"):
            return meta
    # 兜底:取第一个
    all_in_cat = list_skills(category)
    if all_in_cat:
        return all_in_cat[0]
    raise ValueError(f"category '{category}' 下没有任何 skill")


def validate_params(meta: dict, raw_params: dict | None) -> dict:
    """用 META.params 校验并填充用户传入的参数。

    - 缺失的参数补默认值
    - 类型自动转换(bool/int/float/select)
    - select 类型值不在 options 中时回退到 default

    Args:
        meta: Skill META dict(含 params 定义)
        raw_params: 用户传入的原始参数(可为 None)

    Returns:
        校验并填充后的参数字典
    """
    result: dict[str, Any] = {}
    defined = meta.get("params", [])
    # 兼容 params 使用 "id" 或 "key" 作为参数标识
    param_map: dict[str, dict] = {}
    for p in defined:
        pid = p.get("id") or p.get("key")
        if pid:
            param_map[pid] = p
    raw = raw_params or {}

    for pid, spec in param_map.items():
        value = raw.get(pid, spec.get("default"))
        ptype = spec.get("type", "string")

        if ptype == "bool":
            value = bool(value) if not isinstance(value, bool) else value
        elif ptype == "int":
            value = int(value)
        elif ptype == "float":
            value = float(value)
        elif ptype == "select":
            options = spec.get("options", [])
            if options and value not in options:
                value = spec.get("default", options[0] if options else None)
        elif ptype == "number":
            value = float(value) if "." in str(value) else int(value)

        result[pid] = value

    # 保留 META 未定义但用户传入的额外参数
    for key, val in raw.items():
        if key not in param_map:
            result[key] = val

    return result


def reload() -> None:
    """清空缓存,强制重新扫描 builtin 目录(开发时热加载用)。"""
    global _skill_cache
    _skill_cache = None
    logger.info("Skill registry cache cleared, will reload on next access")
