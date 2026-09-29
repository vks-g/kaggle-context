from __future__ import annotations

from kaggle_context.core.budget import estimate_tokens
from kaggle_context.core.models import Bundle
from kaggle_context.render import sections as r
from kaggle_context.render.facts import (
    external_data_rule,
    key_facts,
    notebook_limits,
    submission_format,
)


def test_key_facts_cover_the_expensive_mistakes(bundle: Bundle) -> None:
    facts = dict(key_facts(bundle))
    assert facts["Metric"] == "AUC"
    assert "team ≤ 5" in facts["Limits"] and "5 submissions/day" in facts["Limits"]
    assert facts["Submission"].startswith("Code competition")
    assert "Internet access disabled" in facts["Notebook limits"]
    assert "CPU Notebook <= 9 hours" in facts["Notebook limits"]
    assert facts["Final deadline"] == "2099-01-01 23:59 UTC"


def test_external_data_rule_is_quoted_not_paraphrased(bundle: Bundle) -> None:
    quote = external_data_rule(bundle)
    assert quote.startswith("C. *External Data*. You may use data other than the Competition Data")


def test_submission_format_comes_from_evaluation_page(bundle: Bundle) -> None:
    fmt = submission_format(bundle)
    assert "id,target" in fmt
    assert "Timeline" not in fmt


def test_notebook_limits_are_deduplicated(bundle: Bundle) -> None:
    limits = notebook_limits(bundle)
    assert len(limits) == len({x.lower() for x in limits})


def test_context_respects_budget(bundle: Bundle) -> None:
    small = r.render_context(bundle, budget=1_500)
    assert estimate_tokens(small) < 2_500
    full = r.render_context(bundle, budget=100_000)
    assert "## Rules" in full and "## Discussions" in full and "## Top public notebooks" in full
    assert "…truncated" not in full


def test_topic_render_nests_replies(bundle: Bundle) -> None:
    text = r.render_topic(bundle.topics[0])
    assert text.startswith("# 1st Place Solution")
    assert "(solution write-up)" in text
    assert "> **Dan**" in text


def test_notebook_render_has_attribution(bundle: Bundle) -> None:
    text = r.render_notebook(bundle.notebooks[0])
    assert "Apache 2.0" in text and "https://www.kaggle.com/code/alice/strong-baseline" in text


def test_data_page_never_ships_data_but_says_how_to_get_it(bundle: Bundle) -> None:
    text = r.render_data(bundle, local_script=True)
    assert "`train.csv` | 2.0 MB" in text
    assert "bash data/download.sh" in text
    assert "/rules" in text


def test_agent_guide_is_short(bundle: Bundle) -> None:
    guide = r.render_agent_guide(bundle)
    assert estimate_tokens(guide) < 2_000
    assert "discussions/solutions/" in guide
