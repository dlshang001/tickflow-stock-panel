"""AI Skill 基础类型定义。

每个 AI Skill 必须实现 AiSkillProtocol 协议:
    - build_system_prompt(params, context) -> str
    - build_user_prompt(params, context) -> str
"""
from __future__ import annotations

from typing import Any, Protocol


class AiSkillProtocol(Protocol):
    """所有 AI Skill 必须实现的协议。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        """组装 System Prompt。

        Args:
            params: Skill 专属参数(已通过 validate_params 校验,包含默认值)
            context: 各域注入的数据
                market:     { market_overview, indices, sentiment, news, ... }
                holdings:   { summary, holdings, market_snapshot, concentration, ... }
                settlement: { stats, reconcile, position_summary, ... }

        Returns:
            完整的 System Prompt 字符串
        """
        ...

    def build_user_prompt(self, params: dict, context: dict) -> str:
        """组装 User Prompt。

        Args:
            params: Skill 专属参数
            context: 各域注入的数据

        Returns:
            完整的 User Prompt 字符串
        """
        ...
