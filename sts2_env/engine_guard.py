"""Engine step wall-clock guard: aborts a single env.step if the engine
loops indefinitely (prevents process-level OOM from run-away self-loops).
"""

from __future__ import annotations

import time

# 进程内步级 deadline(None=未 arm,透传)。单线程 worker 协议,用 list
# 单元以便 wrapper 就地读写(与 snapshot._embed_fastpath 同口径)。
_deadline: list[float | None] = [None]
_armed_plays: list[int] = [0]
_budget: list[float] = [0.0]
_max_plays: list[int | None] = [None]

_installed = False


class EngineStepBudgetExceeded(RuntimeError):
    """单个 env.step 内引擎卡路循环超墙钟预算时熔断(engine step guard)。"""


def install_engine_step_guard() -> None:
    """给 CombatState._finish_card_play 安装 deadline 检查(幂等)。"""
    global _installed
    if _installed:
        return
    from sts2_env.core.combat import CombatState

    original = CombatState._finish_card_play

    def _finish_card_play_guarded(self, card, owner):
        if _deadline[0] is not None:
            _armed_plays[0] += 1
            over_plays = (_max_plays[0] is not None
                          and _armed_plays[0] > _max_plays[0])
            # 时间判定用 >:Windows time.monotonic 粒度粗(≈ms 级),极小
            # 预算在同一个 tick 内读作 0 → 由 max_plays 维度兜底确定性熔断。
            over_time = time.monotonic() > _deadline[0]
            if over_time or over_plays:
                _deadline[0] = None  # 熔断后立即失效,防连环抛
                raise EngineStepBudgetExceeded(
                    f"engine step exceeded budget "
                    f"(wall {_budget[0]:.3f}s, plays {_armed_plays[0]}"
                    f"{f'/{_max_plays[0]}' if _max_plays[0] is not None else ''}"
                    ") (engine step guard: unbounded card-play loop within "
                    "a single turn, step never returns)")
        return original(self, card, owner)

    CombatState._finish_card_play = _finish_card_play_guarded
    _installed = True


def is_installed() -> bool:
    return _installed


def arm_step_deadline(budget_s: float,
                      max_plays: int | None = None) -> None:
    """env.step 进入引擎前调用:记预算并起算 deadline。

    budget_s:墙钟预算(秒);max_plays:可选的步内完成 play 数上限
    (确定性维度,测试/已知病态签名用;None=不限)。
    """
    _budget[0] = float(budget_s)
    _max_plays[0] = max_plays
    _armed_plays[0] = 0
    _deadline[0] = time.monotonic() + float(budget_s)


def disarm_step_deadline() -> None:
    """env.step 返回后调用:恢复透传。异常路径也须执行(finally)。"""
    _deadline[0] = None
    _max_plays[0] = None
