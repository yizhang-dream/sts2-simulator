"""is_sovereign_blade None 保护回归测试。

2026-09-06 3M 批首跑实锤:弱池首用(act1_weak chomp)× CONQUEROR power
路径 card_source=None → AttributeError 打崩训练子进程。调用方
remaining_a.py:655 本就 getattr(..., None) 防御,被调方漏判空。
"""

from types import SimpleNamespace

from sts2_env.cards.status import CardId, is_sovereign_blade


def test_none_returns_false():
    assert is_sovereign_blade(None) is False


def test_sovereign_blade_card_returns_true():
    card = SimpleNamespace(card_id=CardId.SOVEREIGN_BLADE)
    assert is_sovereign_blade(card) is True


def test_other_card_returns_false():
    card = SimpleNamespace(card_id=CardId.STOKE)
    assert is_sovereign_blade(card) is False
