"""AI Skill 插件化框架 — 内置 Skill 注册与查询。

使用方式:
    from app.ai_skills import registry

    skills = registry.list_skills(category="settlement")
    skill = registry.get_skill("settlement_wyckoff")
    system_prompt, user_prompt = skill.run(params, context)
"""
from app.ai_skills.registry import (
    list_skills,
    get_skill,
    default_skill,
    validate_params,
)

__all__ = [
    "list_skills",
    "get_skill",
    "default_skill",
    "validate_params",
]
