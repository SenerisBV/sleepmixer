from pathlib import Path

import pytest

from sleepmix.esoterica.script import (
    CUES, SHOWS, SOURCE_CHARACTERS, Passage, ScriptError, load_all,
    load_script, spoken_text,
)

REAL_SCRIPTS = Path(__file__).resolve().parents[2] / "esoterica" / "scripts"

FRONT = """---
id: {id}
show: {show}
title: A Title
language: en
speaker: >
  A woman at a table.
source_character: tape
{extra}voice:
---
"""

BODY = """<!-- intensity: high -->
and then the door [pause] was already open, [softly] which it never was.

[long pause]

Second paragraph of the first passage. [breath]

[passage]

and the light went [whisper] along the floor.

[passage]
<!-- intensity: low -->
[laughs quietly] and so on, and so on
"""


def write(tmp_path, text, name="a-script", show="testimonies"):
    d = tmp_path / show
    d.mkdir(exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(text)
    return p


def good(tmp_path, extra="", body=BODY, id="a-script", show="testimonies"):
    return write(tmp_path, FRONT.format(id=id, show=show, extra=extra) + body,
                 name=id, show=show)


def test_constants():
    assert CUES == {"[pause]", "[long pause]", "[breath]", "[softly]",
                    "[whisper]", "[laughs quietly]"}
    assert SHOWS == {"testimonies", "sideline", "addresses", "stations",
                     "lessons", "meditations", "shuffles"}
    assert SOURCE_CHARACTERS == {"tape", "room", "oldmic", "hum", "clean"}


def test_parses_three_passages(tmp_path):
    s = load_script(good(tmp_path))
    assert (s.id, s.show, s.title, s.language) == ("a-script", "testimonies", "A Title", "en")
    assert s.source_character == "tape"
    assert s.speaker.strip() == "A woman at a table."
    assert s.voice is None
    assert s.path.name == "a-script.md"
    assert [p.index for p in s.passages] == [0, 1, 2]
    assert [p.intensity for p in s.passages] == ["high", "medium", "low"]
    assert "[pause]" in s.passages[0].text and "<!--" not in s.passages[0].text
    assert "[passage]" not in "".join(p.text for p in s.passages)
    assert isinstance(s.passages, tuple)
    assert isinstance(s.passages[0], Passage)


def test_spoken_text_strips_cues(tmp_path):
    s = load_script(good(tmp_path))
    for p in s.passages:
        t = spoken_text(p)
        assert "[" not in t and "]" not in t and "<!--" not in t
    assert spoken_text(s.passages[0]).startswith(
        "and then the door was already open, which it never was.")
    assert spoken_text(s.passages[2]) == "and so on, and so on"


def test_voice_profile_absent_is_none(tmp_path):
    assert load_script(good(tmp_path)).voice_profile is None


def test_voice_profile_present(tmp_path):
    s = load_script(good(tmp_path, extra="voice_profile: female, older, slow\n"))
    assert s.voice_profile == "female, older, slow"


def test_voice_dict_kept(tmp_path):
    p = good(tmp_path)
    p.write_text(p.read_text().replace("voice:\n", "voice:\n  provider: x\n  id: y\n"))
    assert load_script(p).voice == {"provider": "x", "id": "y"}


def test_voice_key_required(tmp_path):
    p = good(tmp_path)
    p.write_text(p.read_text().replace("voice:\n", ""))
    with pytest.raises(ScriptError, match="voice"):
        load_script(p)


def test_unknown_front_matter_key(tmp_path):
    p = good(tmp_path, extra="voice-voice_profile: female\n")
    with pytest.raises(ScriptError) as e:
        load_script(p)
    assert "voice-voice_profile" in str(e.value) and p.name in str(e.value)


def test_missing_front_matter(tmp_path):
    p = write(tmp_path, "just some words\n\n[passage]\n\nmore\n")
    with pytest.raises(ScriptError, match="a-script.md"):
        load_script(p)


def test_unterminated_front_matter(tmp_path):
    p = write(tmp_path, "---\nid: a-script\n")
    with pytest.raises(ScriptError, match="a-script.md"):
        load_script(p)


def test_unknown_show(tmp_path):
    p = good(tmp_path, show="cartoons")
    with pytest.raises(ScriptError, match="a-script.md") as e:
        load_script(p)
    assert "cartoons" in str(e.value)


def test_unknown_source_character_and_language(tmp_path):
    p = good(tmp_path)
    p.write_text(p.read_text().replace("source_character: tape", "source_character: vinyl"))
    with pytest.raises(ScriptError, match="vinyl"):
        load_script(p)
    p = good(tmp_path)
    p.write_text(p.read_text().replace("language: en", "language: de"))
    with pytest.raises(ScriptError, match="language"):
        load_script(p)


def test_unknown_cue_names_line(tmp_path):
    p = good(tmp_path, body="fine words\n\n[passage]\n\nand then he [shouts] loudly\n")
    # front matter is 10 lines (---..---); body line 5 -> file line 15
    with pytest.raises(ScriptError) as e:
        load_script(p)
    msg = str(e.value)
    assert "a-script.md" in msg and "[shouts]" in msg and "line 15" in msg


def test_other_html_comment_rejected(tmp_path):
    p = good(tmp_path, body="words <!-- note --> here\n")
    with pytest.raises(ScriptError, match="a-script.md"):
        load_script(p)


def test_bad_intensity(tmp_path):
    p = good(tmp_path, body="<!-- intensity: loud -->\nwords\n")
    with pytest.raises(ScriptError, match="loud"):
        load_script(p)


def test_empty_passage(tmp_path):
    p = good(tmp_path, body="words\n\n[passage]\n\n\n[passage]\n\nmore\n")
    with pytest.raises(ScriptError, match="a-script.md") as e:
        load_script(p)
    assert "empty" in str(e.value)


def test_intensity_only_passage_is_empty(tmp_path):
    p = good(tmp_path, body="<!-- intensity: low -->\n\n")
    with pytest.raises(ScriptError, match="empty"):
        load_script(p)


def test_cue_only_passage_is_empty(tmp_path):
    p = good(tmp_path, body="[pause]\n")
    with pytest.raises(ScriptError, match="empty"):
        load_script(p)


def test_id_must_match_filename(tmp_path):
    p = good(tmp_path)
    p.write_text(p.read_text().replace("id: a-script", "id: other-id"))
    with pytest.raises(ScriptError, match="a-script.md") as e:
        load_script(p)
    assert "other-id" in str(e.value)


def test_load_all_real_scripts():
    expected = sorted(p.stem for p in REAL_SCRIPTS.glob("*/*.md"))
    scripts = load_all(REAL_SCRIPTS)
    assert len(expected) == 9
    assert sorted(s.id for s in scripts) == expected
    assert {"backward-lesson-one", "mubba-lesson-one"} <= set(expected)
    assert "aurish-lesson-one" not in expected
    for s in scripts:
        assert s.show in SHOWS
        assert s.voice_profile, s.id
        assert s.passages and all(spoken_text(p) for p in s.passages)
        assert s.path.parent.name == s.show


def test_load_all_empty_dir(tmp_path):
    assert load_all(tmp_path) == []


def test_split_cue_rejected(tmp_path):
    p = good(tmp_path, body="words [long\npause] more\n")
    with pytest.raises(ScriptError) as e:
        load_script(p)
    assert "a-script.md" in str(e.value) and "line 11" in str(e.value)


def test_stray_bracket_rejected(tmp_path):
    p = good(tmp_path, body="fine [pause] and then ] oops\n")
    with pytest.raises(ScriptError, match=r"a-script.md, line 11"):
        load_script(p)


def test_front_matter_error_reports_key_line(tmp_path):
    p = good(tmp_path)
    p.write_text(p.read_text().replace("source_character: tape", "source_character: vinyl"))
    with pytest.raises(ScriptError, match=r"a-script.md, line 8: .*vinyl"):
        load_script(p)
    p = good(tmp_path, show="sideline")
    p.write_text(p.read_text().replace("show: sideline", "show: cartoons"))
    with pytest.raises(ScriptError, match=r"line 3: unknown show"):
        load_script(p)


def test_unknown_key_reports_its_line(tmp_path):
    p = good(tmp_path, extra="voice-voice_profile: female\n")
    with pytest.raises(ScriptError, match=r"line 9: unknown front matter key"):
        load_script(p)


def test_missing_key_has_no_line(tmp_path):
    p = good(tmp_path)
    p.write_text(p.read_text().replace("voice:\n", ""))
    with pytest.raises(ScriptError) as e:
        load_script(p)
    assert "line" not in str(e.value)


def test_empty_passage_reports_separator_line(tmp_path):
    # body starts at file line 11: "words"=11, blank=12, [passage]=13
    p = good(tmp_path, body="words\n\n[passage]\n\n\n[passage]\n\nmore\n")
    with pytest.raises(ScriptError, match=r"line 13: passage 2 is empty"):
        load_script(p)


def test_load_all_rejects_wrong_directory(tmp_path):
    p = good(tmp_path)  # show: testimonies
    wrong = tmp_path / "sideline"
    wrong.mkdir()
    (wrong / "a-script.md").write_text(p.read_text())
    p.unlink()
    with pytest.raises(ScriptError, match="sideline.*testimonies"):
        load_all(tmp_path)


def test_load_all_rejects_duplicate_ids(tmp_path):
    a = good(tmp_path)
    other = tmp_path / "sideline"
    other.mkdir()
    # same id inside the other show's dir would fail the filename rule, so
    # duplicate via a second file name is impossible; duplicate across shows:
    (other / "a-script.md").write_text(a.read_text().replace("show: testimonies", "show: sideline"))
    with pytest.raises(ScriptError) as e:
        load_all(tmp_path)
    msg = str(e.value)
    assert "duplicate id" in msg and "sideline" in msg and "testimonies" in msg


def test_bom_and_crlf(tmp_path):
    p = good(tmp_path)
    p.write_bytes(b"\xef\xbb\xbf" + p.read_text().replace("\n", "\r\n").encode())
    s = load_script(p)
    assert [q.intensity for q in s.passages] == ["high", "medium", "low"]
    assert "\r" not in s.passages[0].text and "\r" not in s.speaker
