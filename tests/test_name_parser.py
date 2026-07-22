from agyary.messaging.name_parser import parse_name_line, parse_names, parse_pair_line


def test_titles_and_defaults():
    names = parse_names("Ervad Meherzad\nOsti Farzin\nKhud Zahan\nJaidev")
    assert [(n.title, n.name) for n in names] == [
        ("ervad", "Meherzad"),
        ("osti", "Farzin"),
        ("khud", "Zahan"),
        ("behdin", "Jaidev"),  # missing title defaults to behdin
    ]


def test_er_dot_alias():
    assert parse_name_line("Er. Zahan").title == "ervad"
    assert parse_name_line("er zahan").title == "ervad"
    assert parse_name_line("ERVAD ZAHAN").title == "ervad"


def test_departed_marker():
    n = parse_name_line("Ervad Kaikhushru (D)")
    assert n.departed and n.name == "Kaikhushru"
    n = parse_name_line("Behdin Roshan (departed)")
    assert n.departed and n.name == "Roshan"
    assert not parse_name_line("Behdin Roshan").departed


def test_comma_separated_pairs():
    # v2 writes pairs as "Er. Zahan, Er. Meherzad"
    names = parse_names("Er. Kaikhushru (D), Er. Hormazd (D)")
    assert len(names) == 2
    assert all(n.title == "ervad" and n.departed for n in names)


def test_multiword_names_kept_whole():
    n = parse_name_line("Behdin Roshan Dastoor")
    assert n.name == "Roshan Dastoor"


def test_blank_and_junk_lines_skipped():
    assert parse_names("\n   \n,,\n") == []


def test_name_length_capped():
    n = parse_name_line("Behdin " + "x" * 300)
    assert len(n.name) == 200


def test_pair_line_comma():
    pair = parse_pair_line("Er. Zahan, Er. Meherzad")
    assert pair is not None
    n1, n2 = pair
    assert (n1.title, n1.name) == ("ervad", "Zahan")
    assert (n2.title, n2.name) == ("ervad", "Meherzad")


def test_pair_line_double_title_no_comma():
    # The primary bug: "Ervad Zahan Ervad Meherzad" used to be silently
    # mis-parsed as one garbled name because the old regex swallowed the
    # whole line. It must now split cleanly before the 2nd title keyword.
    n1, n2 = parse_pair_line("Ervad Zahan Ervad Meherzad")
    assert (n1.title, n1.name) == ("ervad", "Zahan")
    assert (n2.title, n2.name) == ("ervad", "Meherzad")

    n1, n2 = parse_pair_line("Behdin Roshan Behdin Dinshaw")
    assert (n1.name, n2.name) == ("Roshan", "Dinshaw")


def test_pair_line_departed_marker_preserved():
    n1, n2 = parse_pair_line("Ervad Kaikhushru (D), Ervad Hormazd (D)")
    assert n1.departed and n2.departed


def test_pair_line_rejects_ambiguous_single_title():
    # Only one recognized title keyword: can't tell where the 2nd name
    # starts, so this must be rejected rather than guessed at.
    assert parse_pair_line("Zahan Ervad Meherzad") is None


def test_pair_line_rejects_non_pair():
    assert parse_pair_line("Just one name") is None
    assert parse_pair_line("") is None
    assert parse_pair_line("Er. A, Er. B, Er. C") is None
