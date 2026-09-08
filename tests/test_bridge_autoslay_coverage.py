"""Coverage guards for the AutoSlay bridge wiring."""

from pathlib import Path

RL_AUTO_SLAYER = Path(__file__).resolve().parents[1] / "bridge_mod" / "RlAutoSlayer.cs"


def _rl_auto_slayer_source() -> str:
    return RL_AUTO_SLAYER.read_text(encoding="utf-8")


def test_autoslay_run_rooms_route_through_rl_handlers() -> None:
    source = _rl_auto_slayer_source()

    assert "[RoomType.Monster] = combatHandler" in source
    assert "[RoomType.Elite] = combatHandler" in source
    assert "[RoomType.Boss] = combatHandler" in source
    assert "[RoomType.Event] = new RlEventRoomHandler()" in source
    assert "[RoomType.Shop] = new RlShopRoomHandler()" in source
    assert "[RoomType.Treasure] = new RlTreasureRoomHandler()" in source
    assert "[RoomType.RestSite] = new RlRestSiteRoomHandler()" in source
    assert "_mapHandler = new RlMapHandler()" in source


def test_autoslay_standalone_choice_screens_route_through_rl_handlers() -> None:
    source = _rl_auto_slayer_source()

    assert "[typeof(NRewardsScreen)] = new RlRewardsScreenHandler()" in source
    assert "[typeof(NCardRewardSelectionScreen)] = new RlCardRewardScreenHandler()" in source
    assert "[typeof(NChooseABundleSelectionScreen)] = new RlCardBundleScreenHandler()" in source
    assert "[typeof(NChooseARelicSelection)] = new RlChooseARelicScreenHandler()" in source
    assert "[typeof(NGameOverScreen)] = new RlGameOverScreenHandler()" in source
    assert "[typeof(NCrystalSphereScreen)] = new RlCrystalSphereScreenHandler()" in source


def test_card_select_screens_are_guarded_by_rl_selector() -> None:
    source = _rl_auto_slayer_source()

    assert "CardSelectCmd.UseSelector(new RlCardSelector())" in source
    assert "[typeof(NDeckUpgradeSelectScreen)] = new DeckUpgradeScreenHandler()" in source
    assert "[typeof(NDeckTransformSelectScreen)] = new DeckTransformScreenHandler()" in source
    assert "[typeof(NDeckEnchantSelectScreen)] = new DeckEnchantScreenHandler()" in source
    assert "[typeof(NDeckCardSelectScreen)] = new DeckCardSelectScreenHandler()" in source
    assert "[typeof(NSimpleCardSelectScreen)] = new SimpleCardSelectScreenHandler()" in source
    assert "[typeof(NChooseACardSelectionScreen)] = new ChooseACardScreenHandler()" in source


def test_autoslay_run_flow_uses_named_protocol_and_timing_constants() -> None:
    source = _rl_auto_slayer_source()
    compact_source = "".join(source.split())

    assert "RunCompleteState(NonCombatBridgeProtocol.TerminatedResult)" in compact_source
    assert "RunCompleteState(NonCombatBridgeProtocol.VictoryResult)" in compact_source
    assert "NonCombatBridgeProtocol.GameOverState" in source
    assert "NonCombatBridgeProtocol.GameOverMessage" in source
    assert '"{\\"type\\":\\"run_complete\\"' not in source
    assert '"{\\"type\\":\\"game_over\\"' not in source
    assert "while (runState.TotalFloor < FinalRunFloor)" in source
    assert "TimeSpan.FromMinutes(RunTimeoutMinutes)" in source
    assert "TimeSpan.FromSeconds(RunStateTimeoutSeconds)" in source
    assert "TimeSpan.FromSeconds(RoomAssignmentTimeoutSeconds)" in source
    assert "TimeSpan.FromSeconds(RewardsScreenTimeoutSeconds)" in source


# The CardSelectCmd reference-source interception guards
# (test_decompiled_card_select_cmd_*) parse the pinned reference sources and
# run in the maintainer environment; they are not part of this public build.
