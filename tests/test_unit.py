from app.pipeline.planner import HeuristicPlanner
from app.pipeline.segment import Word, build_srt, phrases_from_text, scenes_from_words, split_sentences

P = HeuristicPlanner()


def plan(text, avoid=None, hint=None):
    return P.plan(text, hint, text, "bright", avoid or [])


def test_sentences_keep_abbreviations_and_decimals():
    s = split_sentences("Dr. Rao spoke. Sales rose 3.5 percent! Why?")
    assert s == ["Dr. Rao spoke.", "Sales rose 3.5 percent!", "Why?"]


def test_scenes_cover_all_time_and_break_on_sentences():
    words = [Word(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate(
        "Trust is earned slowly. It takes years, and it can vanish in a day. Be patient and keep your word.".split())]
    total = words[-1].end + 0.3
    sc = scenes_from_words(words, total, 2.0, 8.0)
    assert sc[0].start == 0.0 and abs(sc[-1].end - total) < 1e-9
    for a, b in zip(sc, sc[1:]):
        assert abs(a.end - b.start) < 1e-9          # no gaps, no overlaps
        assert a.text.rstrip().endswith((".", "?", "!"))  # boundaries on sentence ends
    assert all(s.duration >= 1.9 for s in sc)       # no flashing micro-scenes


def test_long_sentence_is_split_at_a_phrase_boundary():
    words = [Word(w, i * 0.5, i * 0.5 + 0.4) for i, w in enumerate(
        ("when you save a little every month, even a small amount, it compounds quietly over many years, "
         "and one day you notice it has become something real").split())]
    sc = scenes_from_words(words, words[-1].end, 2.0, 8.0)
    assert len(sc) >= 2 and all(s.duration <= 8.5 for s in sc)


def test_srt_is_well_formed_and_ordered():
    words = [Word(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate("one two three four five six seven eight nine ten".split())]
    srt = build_srt(scenes_from_words(words, 4.5, 1.0, 8.0))
    blocks = [b for b in srt.strip().split("\n\n") if b]
    assert blocks[0].startswith("1\n00:00:00,")
    assert " --> " in blocks[0]


def test_ambiguous_words_use_context():
    assert "bank" in plan("She opened a bank account and made a deposit.").queries[0]
    assert "river" in plan("We sat on the river bank and watched the water.").queries[0]
    assert "server" in plan("Moving to the cloud means your data runs on remote servers.").queries[0]
    assert "sky" in plan("Dark clouds covered the sky before the storm.").queries[0]
    assert "mouse on desk" in plan("Click the mouse to scroll on your computer.").queries[0]
    assert "animal" in plan("The tiny mouse squeaked and ate the cheese.").queries[0]
    assert "code" in plan("Python is a programming language for developers.").queries[0]
    assert "snake" in plan("The python slithered through the jungle.").queries[0]
    q = plan("The value of our brand and company culture matters to customers.").queries[0]
    assert "cash" not in q and "money" not in q


def test_abstract_line_becomes_a_visual_metaphor():
    p = plan("Trust is earned slowly.")
    assert p.abstract and "trust" not in p.queries[0]


def test_numbers_become_chart_footage_not_a_literal_search():
    p = plan("Sales grew 40% in 2025.")
    assert any("chart" in q for q in p.queries) and not any("2025" in q or "40" in q for q in p.queries)


def test_named_person_and_brand_get_generic_footage():
    p = plan("Elon Musk said Tesla would double production.")
    assert "NAMED_ENTITY_GENERIC_FOOTAGE" in [f["code"] for f in p.flags]
    joined = " ".join(p.queries).lower()
    assert "elon" not in joined and "musk" not in joined and "tesla" not in joined


def test_sensitive_news_gets_respectful_visuals_without_people():
    p = plan("A factory fire killed three workers and families are grieving.")
    assert p.sensitive and "SENSITIVE_TOPIC_RESPECTFUL_FOOTAGE" in [f["code"] for f in p.flags]
    assert not any("people" in q or "worker" in q for q in p.queries)


def test_avoid_list_is_expanded():
    p = plan("Celebrate the launch.", avoid=["people's faces", "alcohol"])
    assert {"beer", "wine", "face", "people"} <= p.avoid


def test_visual_hint_is_used_first():
    assert plan("Our product launches today.", hint="rocket launching").queries[0] == "rocket launching"


def test_concrete_instruction_with_one_abstract_word_gets_no_metaphor():
    p = plan("Save your changes and you are done.")
    assert not any("seasons" in q for q in p.queries)


def test_sensitive_queries_rotate_per_scene_in_the_pipeline_rule():
    p = plan("Their families are grieving after the tragedy.")
    assert p.sensitive and len(set(p.queries)) >= 3
