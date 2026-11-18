from ecam_sync.transform import clean_title, course_names, transform_texts


def test_act_format():
    title, desc = transform_texts("®-XX3T-T1-G1>", "Act:Signals and systems\nGroupe:G1\nEns:AAA")
    assert title == "Signals and systems"
    assert desc == "Groupe:G1\nEns:AAA"


def test_act_format_with_remark_line():
    _, desc = transform_texts("x", "Act:Séminaire\nGroupe:G3\nRem:Conférence\nEns:")
    assert desc == "Groupe:G3\nRem:Conférence\nEns:"


def test_exam_format_removes_trailing_backslash():
    title, desc = transform_texts("PM1C:Pont Math", "PM1C:Pont Math[ECRIT]\\ \nEns:BBB CCC")
    assert title == "PM1C:Pont Math[ECRIT]"
    assert desc == "Ens:BBB CCC"


def test_double_spaces_collapsed():
    assert clean_title("Act:Chimie Th  ex & labo") == "Chimie Th ex & labo"


def test_act_prefix_is_case_insensitive_and_only_a_prefix():
    assert clean_title("ACT : Coordination") == "Coordination"
    assert clean_title("Reactions Act:2") == "Reactions Act:2"


def test_empty_description_falls_back_to_summary():
    assert transform_texts("Réunion", "") == ("Réunion", "")


def test_everything_empty_gets_placeholder():
    assert transform_texts("", "")[0] == "(sans titre)"


def test_crlf_description():
    title, desc = transform_texts("x", "Act:Cours\r\nGroupe:A\r\nEns:B")
    assert (title, desc) == ("Cours", "Groupe:A\nEns:B")


NAMES = {"TH2C": "Thermo"}


def test_generic_title_is_prefixed_with_course_name():
    assert transform_texts("®-TH2C-T1-G3", "Act:théorie\nGroupe:G3", NAMES) == ("Thermo – théorie", "Groupe:G3")
    assert transform_texts("®-TH2C-X1-G3-A", "Act:Exercices", NAMES)[0] == "Thermo – Exercices"


def test_generic_title_falls_back_to_code():
    assert transform_texts("®-ZZ9C-X1-G3", "Act:exercices", NAMES)[0] == "ZZ9C – exercices"
    assert transform_texts("®-ZZ9C-X1-G3", "Act:exercices")[0] == "ZZ9C – exercices"


def test_specific_titles_are_untouched():
    assert transform_texts("®-TH2C-T1-G3", "Act:Thermodynamique appliquée", NAMES)[0] == "Thermodynamique appliquée"
    assert transform_texts("2BCD-H1-G3", "Act:Coordination", NAMES)[0] == "Coordination"
    assert transform_texts("TH2C:Thermo", "TH2C:Thermo[ECRIT]\\ \nEns:EEE", NAMES)[0] == "TH2C:Thermo[ECRIT]"


def test_generic_title_without_course_code_is_kept():
    assert transform_texts("Réunion", "Act:théorie", NAMES)[0] == "théorie"


def test_course_names_come_from_exam_summaries():
    names = course_names(["TH2C:Thermo", "CH1T:Chimie Th  ex & labo", "®-TH2C-T1-G3", "2BCD-H1-G3", "OM1C:Outils[ECRIT]"])
    assert names == {"TH2C": "Thermo", "CH1T": "Chimie Th ex & labo", "OM1C": "Outils"}
