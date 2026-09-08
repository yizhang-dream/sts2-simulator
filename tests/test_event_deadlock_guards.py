"""事件死锁修复回归:FakeMerchant 买不起的赝品选项必须 disabled(2026-09-05)。

病理(progress guard 探针实证,seed 41300004):FakeMerchant 的
buy_i 选项无条件 enabled=True,金币 < FAKE_RELIC_COST(50) 时 choose(buy_i)
返回 "Could not buy" 但 finished=False、选项原样重挂 → 只看 mask 的确定性
策略永远反复选同一选项,EVENT 层无限空转。同库姊妹事件(TeaMaster/
EmotionalAwareness/ArachnidAcupuncture)全部按 enabled=gold>=成本 惯例。
修复:patch.py 给 _post_buy_options 挂金币守卫 → _actions_event 过滤
disabled 选项,策略从根上选不到买不起的选项。
"""

from types import SimpleNamespace

from sts2_env.datawash.patch import install_v01110_overrides

_BUY_PREFIX = "buy_"


def _mk_player(gold: int) -> SimpleNamespace:
    return SimpleNamespace(gold=gold, held_potions=lambda: [])


def _options_for(gold: int):
    install_v01110_overrides()
    from sts2_env.events.act2 import FakeMerchant

    fm = FakeMerchant()
    rs = SimpleNamespace(player=_mk_player(gold))
    return fm._post_buy_options(rs, ["FakeAnchor", "FakeBloodVial"])


def test_unaffordable_buy_options_disabled():
    opts = _options_for(gold=30)
    buy = [o for o in opts if o.option_id.startswith(_BUY_PREFIX)]
    leave = [o for o in opts if o.option_id == "leave"]
    assert buy and leave, "守卫后仍应有 buy 与 leave 选项(仅 disabled)"
    assert all(not o.enabled for o in buy), "金币不足时 buy_i 必须 disabled"
    assert leave[0].enabled, "leave 不受守卫影响"


def test_affordable_buy_options_stay_enabled():
    opts = _options_for(gold=99)
    buy = [o for o in opts if o.option_id.startswith(_BUY_PREFIX)]
    assert buy and all(o.enabled for o in buy), "买得起路径零变化"


def test_boundary_gold_exactly_cost_enabled():
    opts = _options_for(gold=50)
    buy = [o for o in opts if o.option_id.startswith(_BUY_PREFIX)]
    assert all(o.enabled for o in buy), "金币恰等于成本(>=)必须仍可选"

