import json

from build import finite, is_candidate, render_html


def test_render_html_embeds_and_escapes():
    html = render_html('<script id="data" type="application/json">/*__DATA__*/null</script>', {"x": "</script><b>"})
    assert "/*__DATA__*/null" not in html and "<\\/script>" in html
    assert json.loads(html.split(">", 1)[1].rsplit("</script>", 1)[0].replace("<\\/", "</")) == {"x": "</script><b>"}


def test_finite_replaces_nan_and_inf():
    out = finite({"a": float("nan"), "b": [float("inf"), 1.5], "c": {"d": float("-inf")}, "e": "x", "f": 3})
    assert out == {"a": None, "b": [None, 1.5], "c": {"d": None}, "e": "x", "f": 3}


def test_is_candidate():
    tier = {"buffett": "A", "gates": "B", "soros": "B"}

    def s(acts):
        return {"actions": [{"inv": i, "t": t} for i, t in acts]}

    assert is_candidate(s([("gates", "new"), ("soros", "add")]), tier)
    assert is_candidate(s([("buffett", "new"), ("gates", "hold")]), tier)
    assert not is_candidate(s([("gates", "new"), ("soros", "hold")]), tier)
