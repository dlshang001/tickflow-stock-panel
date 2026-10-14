from __future__ import annotations

import json
from types import SimpleNamespace

import polars as pl
import pytest

from app.api import settings as settings_api
from app.api import stock_analysis as stock_analysis_api
from app.services import ai_provider, stock_analyzer


@pytest.mark.asyncio
async def test_stock_analyzer_uses_requested_model_in_meta_and_stream(monkeypatch, tmp_path):
    captured = {}
    frame = pl.DataFrame({"close": [123.0], "raw_close": [123.0]})
    repo = SimpleNamespace(resolve_asset_type=lambda _symbol: "stock")

    monkeypatch.setattr(stock_analyzer, "_load_kline", lambda *_args: frame)
    monkeypatch.setattr(stock_analyzer, "compute_levels", lambda _df: {})
    monkeypatch.setattr(stock_analyzer, "summarize_levels", lambda *_args: "level summary")
    monkeypatch.setattr(stock_analyzer, "_load_financials", lambda *_args: {})
    monkeypatch.setattr(stock_analyzer, "_clean_rows", lambda *_args: [])
    monkeypatch.setattr(stock_analyzer, "_build_user_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr(ai_provider, "current_ai_model", lambda: "configured-default")
    monkeypatch.setattr(ai_provider, "is_codex_cli_provider", lambda: False)

    async def fake_stream(_messages, **kwargs):
        captured.update(kwargs)
        yield "report text"

    monkeypatch.setattr(ai_provider, "stream_ai_text", fake_stream)
    events = [
        json.loads(item)
        async for item in stock_analyzer.analyze_stock_stream(
            repo, tmp_path, "600000.SH", model="requested-model",
        )
    ]

    assert events[0]["type"] == "meta"
    assert events[0]["model"] == "requested-model"
    assert captured["model"] == "requested-model"
    assert events[1] == {"type": "delta", "content": "report text"}
    assert events[2]["type"] == "done"


@pytest.mark.asyncio
async def test_analyze_route_forwards_model_to_service(monkeypatch, tmp_path):
    captured = {}
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=repo)))

    async def fake_analyzer(_repo, _data_dir, symbol, focus, *, model):
        captured.update(symbol=symbol, focus=focus, model=model)
        yield json.dumps({"type": "meta", "model": model})

    monkeypatch.setattr(stock_analysis_api, "analyze_stock_stream", fake_analyzer)
    monkeypatch.setattr(stock_analysis_api, "with_heartbeat", lambda stream: stream)
    response = await stock_analysis_api.analyze_stock(
        request,
        stock_analysis_api.AnalyzeRequest(symbol="600000.SH", focus="cash flow", model="requested-model"),
    )
    body = [chunk async for chunk in response.body_iterator]

    assert captured == {"symbol": "600000.SH", "focus": "cash flow", "model": "requested-model"}
    assert b"requested-model" in body[0] if isinstance(body[0], bytes) else "requested-model" in body[0]


def test_analyze_request_caps_model_identifier_length():
    with pytest.raises(ValueError):
        stock_analysis_api.AnalyzeRequest(symbol="600000.SH", model="x" * 201)


@pytest.mark.asyncio
async def test_codex_model_list_keeps_saved_model_first(monkeypatch):
    monkeypatch.setattr(ai_provider, "current_ai_provider", lambda: ai_provider.CODEX_CLI_PROVIDER)
    monkeypatch.setattr(ai_provider, "current_ai_model", lambda: "")
    monkeypatch.setattr(ai_provider, "current_codex_effective_model", lambda: "saved-local-model")

    async def fake_catalog():
        return {
            "models": [
                {"model": "new-model", "is_default": False},
                {"model": "cli-default", "is_default": True},
            ],
        }

    monkeypatch.setattr(ai_provider, "codex_model_catalog", fake_catalog)
    assert await settings_api.get_ai_models() == {
        "models": ["saved-local-model", "new-model", "cli-default"],
    }

    monkeypatch.setattr(ai_provider, "current_codex_effective_model", lambda: "")
    assert await settings_api.get_ai_models() == {
        "models": ["cli-default", "new-model"],
    }
