"""The sample-test scorer: if it miscounts, we would promise the mobeds the wrong thing.

Pure functions only - no database, no model.
"""

from tools.namebook_eval.score import (
    ReadLine,
    ReadName,
    disputed_names,
    key_en,
    key_gu,
    parse_truth,
    score_page,
)


def rl(*names, struck="no"):
    """A read line: each name is 'English' or ('English', legibility)."""
    out = []
    for n in names:
        text, leg = (n, "clear") if isinstance(n, str) else n
        out.append(ReadName(text, "", leg))
    return ReadLine(out, struck)


def test_spelling_does_not_count():
    assert key_en("Firoz") == key_en("Phiroz")
    assert key_en("Sorabji") == key_en("Sorab")
    assert key_en("Dhunbai") == key_en("Dun")
    assert key_gu("ઝરીન") == key_gu("ઝરિન")


def test_parse_truth_titles_strikes_and_unknowns():
    lines = parse_truth(
        "# a comment\n"
        "behdin Rustom | behdin Jamshed\n"
        "osti Dhun\n"
        "~ behdin Sorab | behdin Framroz\n"
        "behdin ? | ervad Hormuzd\n"
    )
    assert [line.names for line in lines] == [
        ["Rustom", "Jamshed"], ["Dhun"], ["Sorab", "Framroz"], [None, "Hormuzd"],
    ]
    assert [line.struck for line in lines] == [False, False, True, False]


def test_a_clean_reading_is_all_correct():
    truth = parse_truth("behdin Rustom | behdin Jamshed\nosti Dhun\n")
    c = score_page(truth, [rl("Rustam", "Jamsheed"), rl("Dhunbai")])
    assert c["names on page"] == 3
    assert c["correct"] == 3
    assert c["invented"] == c["missed"] == c["wrong (sure)"] == 0


def test_sure_but_wrong_is_told_apart_from_flagged():
    truth = parse_truth("behdin Rustom | behdin Jamshed\n")
    c = score_page(truth, [rl("Rustom", "Hormuzd")])
    assert c["wrong (sure)"] == 1
    c = score_page(truth, [rl("Rustom", ("Hormuzd", "unsure"))])
    assert c["wrong (sure)"] == 0 and c["wrong (flagged)"] == 1


def test_an_added_line_is_invented_and_a_skipped_line_is_missed():
    truth = parse_truth("behdin Rustom | behdin Jamshed\nosti Dhun\n")
    c = score_page(truth, [rl("Rustom", "Jamshed"), rl("Kersi"), rl("Dhun")])
    assert c["invented"] == 1 and c["missed"] == 0
    c = score_page(truth, [rl("Rustom", "Jamshed")])
    assert c["missed"] == 1


def test_a_half_read_pair_is_a_wrong_section_and_a_miss():
    truth = parse_truth("behdin Rustom | behdin Jamshed\n")
    c = score_page(truth, [rl("Rustom")])
    assert c["wrong section"] == 1 and c["missed"] == 1


def test_an_unreadable_half_keeps_the_pair():
    truth = parse_truth("behdin Rustom | behdin Jamshed\n")
    c = score_page(truth, [rl("Rustom", ("", "unreadable"))])
    assert c["wrong section"] == 0
    assert c["correct"] == 1 and c["wrong (flagged)"] == 1


def test_strikeouts_both_ways():
    truth = parse_truth("~ behdin Sorab | behdin Framroz\nosti Dhun\n")
    c = score_page(truth, [rl("Sorab", "Framroz"), rl("Dhun")])
    assert c["struck name read as live"] == 1
    assert c["names on page"] == 1  # a struck name is not to be imported
    c = score_page(truth, [rl("Sorab", "Framroz", struck="yes"), rl("Dhun", struck="yes")])
    assert c["dropped as struck"] == 1 and c["missed"] == 1


def test_a_title_written_into_the_name_is_not_a_mistake():
    truth = parse_truth("behdin Rustom | behdin Jamshed\n")
    c = score_page(truth, [rl("Behdin Rustom", "Behdin Jamshed")])
    assert c["correct"] == 2 and c["wrong (sure)"] == 0


def test_invented_names_are_told_apart_by_how_sure_the_reader_was():
    truth = parse_truth("osti Dhun\n")
    c = score_page(truth, [rl("Dhun"), rl(("Kersi", "unsure"))])
    assert c["invented"] == 0 and c["invented (flagged)"] == 1


def test_an_unreadable_slot_on_a_single_line_is_a_blank_not_an_invention():
    """Gemma 3 did this on the smoke test: a farmayeshne line turned into a pair with an
    unreadable half. Harmless at review, but it also changes the section."""
    truth = parse_truth("behdin Kersi\n")
    c = score_page(truth, [rl("Kersi", ("", "unreadable"))])
    assert c["correct"] == 1 and c["invented"] == 0
    assert c["blank slot added"] == 1 and c["wrong section"] == 1


def test_a_second_run_catches_a_sure_mistake_it_disagrees_with():
    truth = parse_truth("behdin Rustom | behdin Jamshed\n")
    run1 = [rl("Rustom", "Hormuzd")]
    run2 = [rl("Rustom", "Jamshed")]
    c = score_page(truth, run1, disputed_names(run1, run2))
    assert c["wrong (sure)"] == 1
    assert c["wrong (sure), caught by run 2"] == 1
