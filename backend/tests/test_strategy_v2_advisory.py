from app.services.strategy_v2_advisory import robust_validation_objective, selection_stability


def trade(pnl, side="SHORT"):
    return {"net_pnl": pnl, "r_multiple": pnl / 10, "side": side}


def test_objective_uses_net_expectancy_and_robustness_penalty():
    stable = {
        "SHORT/A/F1": [trade(2), trade(2)],
        "SHORT/B/F1": [trade(2), trade(2)],
        "SHORT/C/F1": [trade(2), trade(2)],
    }
    unstable = {
        "SHORT/A/F1": [trade(8), trade(8)],
        "SHORT/B/F1": [trade(-2), trade(-2)],
        "SHORT/C/F1": [trade(0), trade(0)],
    }
    stable_score, eligible, detail = robust_validation_objective(stable, minimum_trades=6)
    unstable_score, _, _ = robust_validation_objective(unstable, minimum_trades=6)
    assert eligible and detail["net_expectancy"] == 2
    assert stable_score > unstable_score


def test_minimum_trades_and_selection_stability():
    score, eligible, _ = robust_validation_objective({"a": [trade(1)]}, minimum_trades=2)
    assert not eligible and score == float("-inf")
    assert selection_stability(["a", "a", "b"])["modal_share"] == 2 / 3
