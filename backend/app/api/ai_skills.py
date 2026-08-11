"""AI Skill 列表查询 API。"""
from fastapi import APIRouter, Query

from app.ai_skills import registry

router = APIRouter(prefix="/api/ai-skills", tags=["ai-skills"])


@router.get("/list")
def list_ai_skills(category: str | None = Query(None, description="按 category 过滤: market / holdings / settlement")):
    """列出所有可用的 AI Skill。

    返回 META 列表(默认 skill 排最前),前端用于渲染 Skill 选择器。
    """
    skills = registry.list_skills(category)
    return {"skills": skills}
