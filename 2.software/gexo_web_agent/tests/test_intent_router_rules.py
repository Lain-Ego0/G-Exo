"""Rule fast-path routing — every spec example must map correctly."""
from __future__ import annotations

import pytest

from gexo_web_agent.intent_router import route_by_rules
from gexo_web_agent.schemas import (
    AdjustAssistAction,
    DocumentQaAction,
    Mode,
    QueryStatusAction,
    SetModeAction,
)


@pytest.mark.parametrize(
    "text",
    ["现在是什么模式？", "现在是阻尼模式吗？", "还有多少电？", "电机现在多少度？",
     "CAN 正常吗？", "当前助力多少？", "状态", "电量"],
)
def test_status_queries(text: str):
    assert isinstance(route_by_rules(text), QueryStatusAction)


@pytest.mark.parametrize(
    "text",
    ["怎么正确穿戴设备？", "阻尼模式是什么？", "什么是助力模式", "如何充电", "为什么要标定 IMU"],
)
def test_document_questions(text: str):
    a = route_by_rules(text)
    assert isinstance(a, DocumentQaAction)
    assert a.question  # original text preserved


@pytest.mark.parametrize(
    "text", ["切换到阻尼训练模式。", "切到阻尼模式", "进入训练模式", "阻尼模式", "换成阻尼"]
)
def test_switch_to_damping(text: str):
    a = route_by_rules(text)
    assert isinstance(a, SetModeAction) and a.mode is Mode.DAMPING


@pytest.mark.parametrize("text", ["切换到助力模式", "助力模式", "切回助力"])
def test_switch_to_assist(text: str):
    a = route_by_rules(text)
    assert isinstance(a, SetModeAction) and a.mode is Mode.ASSIST


@pytest.mark.parametrize(
    "text", ["助力再大一点。", "增加助力", "加大助力", "助力大一点", "提高一下助力", "大一点"]
)
def test_assist_up(text: str):
    a = route_by_rules(text)
    assert isinstance(a, AdjustAssistAction) and a.delta == pytest.approx(0.1)


@pytest.mark.parametrize(
    "text", ["减小一点助力。", "减少助力", "降低助力", "助力小一点", "小一点"]
)
def test_assist_down(text: str):
    a = route_by_rules(text)
    assert isinstance(a, AdjustAssistAction) and a.delta == pytest.approx(-0.1)


@pytest.mark.parametrize(
    "text", ["你好", "今天天气不错", "帮我叫个外卖", ""]
)
def test_ambiguous_falls_through_to_llm(text: str):
    assert route_by_rules(text) is None


def test_full_width_punctuation_normalized():
    assert isinstance(route_by_rules("切换到阻尼训练模式！！！"), SetModeAction)
