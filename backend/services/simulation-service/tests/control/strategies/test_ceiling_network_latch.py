"""Gridlock round (2026-10-31): warm-up and network latch of the adaptive ceiling.
v3 is the default `AcampConfig()` since the fresh-seed test; `paper_a_config()` is paper A's.
Most tests below set the latch explicitly and read `_load_ewma` (halflife None)."""

from __future__ import annotations

from sim_service.control.strategies import acamp


_OLD = dict(ceiling_relax_net_signal="mean", ceiling_relax_net_halflife_s=None)


def _ctrl(network: dict, load: float, **cfg) -> acamp.AdaptiveCamp:
    c = acamp.AdaptiveCamp(acamp.AcampConfig(**{**_OLD, **cfg}), network=network)
    c._load_ewma = load
    return c


def test_paper_a_config_has_no_latch_and_never_relaxes():
    net: dict = {}
    c = acamp.AdaptiveCamp(acamp.paper_a_config(ceiling_relax_net_block=None), network=net)
    c._load_ewma = 1e9
    assert c._network_state() is False
    assert acamp.paper_a_config().ceiling_relax_factor is None


def test_defaults_are_v3():
    d = acamp.AcampConfig()
    assert (d.ceiling_relax_factor, d.ceiling_relax_below, d.ceiling_relax_hold_s) == (8.0, 0.3, 900.0)
    assert (d.ceiling_relax_net_block, d.ceiling_relax_net_signal, d.ceiling_relax_net_halflife_s,
            d.ceiling_relax_net_release_s, d.ceiling_relax_warmup_s) == (0.7, "max", 60.0, 1800.0, 750.0)


def test_latch_without_shared_network_never_relaxes():
    """Fail safe: a controller built without the shared network dict cannot see the
    network state, so it keeps the fixed ceiling (paper A's behaviour)."""
    from test_maxpressure_and_wait_margin import _cfg, _ctx  # noqa: PLC0415

    c = acamp.AdaptiveCamp(acamp.AcampConfig())
    c.set_sim_time(5000.0)
    c(_cfg(), _ctx(q={"m0": 5.0}, elapsed=25.0))
    assert c.stats.get("ceiling_relaxed", 0) == 0
    with_net = acamp.AdaptiveCamp(acamp.AcampConfig(), network={})
    with_net.set_sim_time(5000.0)
    with_net(_cfg(), _ctx(q={"m0": 5.0}, elapsed=25.0))
    assert with_net.stats.get("ceiling_relaxed", 0) == 1


def test_mean_latch_engages_and_releases_after_calm_period():
    net: dict = {}
    hot = _ctrl(net, load=1e9, ceiling_relax_net_block=0.2, ceiling_relax_net_release_s=100.0)
    cold = _ctrl(net, load=0.0, ceiling_relax_net_block=0.2, ceiling_relax_net_release_s=100.0)
    cold.set_sim_time(0.0)
    cold._network_state()
    hot.set_sim_time(0.0)
    assert hot._network_state() is True  # mean of ~1 and 0 is >= 0.2
    hot._load_ewma = 0.0
    for t in (10.0, 50.0, 109.0):
        hot.set_sim_time(t)
        assert hot._network_state() is True  # calm, but not yet for 100 s
    hot.set_sim_time(111.0)
    assert hot._network_state() is False


def test_max_signal_sees_one_saturated_junction_in_a_large_network():
    net: dict = {}
    kw = dict(ceiling_relax_net_block=0.7, ceiling_relax_net_release_s=1e9)
    quiet = [_ctrl(net, load=0.0, **kw) for _ in range(30)]
    for q in quiet:
        q._network_state()
    hot = _ctrl(net, load=1e9, **kw)
    hot._network_state()  # registers itself
    assert quiet[0]._network_state() is False  # mean is ~1/31 < 0.7
    net.pop("_net")
    kw_max = dict(kw, ceiling_relax_net_signal="max")
    for q in quiet:
        q.cfg = acamp.AcampConfig(**{**_OLD, **kw_max})
    assert quiet[0]._network_state() is True


def test_warmup_and_latch_keep_the_fixed_ceiling():
    """With warm-up or latch engaged the controller must behave exactly like the fixed
    ceiling: `ceiling_relaxed` never counts."""
    from test_maxpressure_and_wait_margin import _cfg, _ctx  # noqa: PLC0415

    net: dict = {}
    c = acamp.AdaptiveCamp(acamp.AcampConfig(
        ceiling_relax_factor=8.0, ceiling_relax_below=0.3, ceiling_relax_warmup_s=600.0,
        ceiling_relax_net_block=0.7, ceiling_relax_net_signal="max",
        ceiling_relax_net_release_s=1e9, ceiling_relax_net_halflife_s=None,
        ceiling_relax_hold_s=0.0), network=net)
    c.set_sim_time(100.0)
    c(_cfg(), _ctx(q={"m0": 5.0}, elapsed=25.0))
    assert c.stats.get("ceiling_relaxed", 0) == 0
    c.set_sim_time(700.0)
    c(_cfg(), _ctx(q={"m0": 5.0}, elapsed=25.0))
    assert c.stats.get("ceiling_relaxed", 0) == 1
    other = acamp.AdaptiveCamp(c.cfg, network=net)
    other._load_ewma = 1e9
    other.set_sim_time(701.0)
    other._network_state()
    c.set_sim_time(702.0)
    c(_cfg(), _ctx(q={"m0": 5.0}, elapsed=25.0))
    assert c.stats.get("ceiling_relaxed", 0) == 1
