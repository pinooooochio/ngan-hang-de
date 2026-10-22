from collections import Counter
from pathlib import Path

import pytest

from nganhangde import bank, generator, render
from nganhangde.compile import compile_tex, latex_available
from nganhangde.db import make_session
from nganhangde.models import Level
from nganhangde.parser import parse_text

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture
def session():
    s = make_session("sqlite://")
    parsed = parse_text((EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8"))
    report = bank.import_questions(s, parsed)
    assert not report.failed
    return s


def test_import_and_duplicates(session):
    parsed = parse_text((EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8"))
    report = bank.import_questions(session, parsed)
    assert report.added == []
    assert len(report.duplicates) == len(parsed)


def test_find_by_tag_prefix_and_level(session):
    all_12 = bank.find_questions(session, tag="lop-12")
    sub = bank.find_questions(session, tag="Lớp 12/Vectơ trong không gian/Tích vô hướng")
    assert len(sub) > 0 and len(all_12) > len(sub)
    assert all(q.level == Level.VD for q in bank.find_questions(session, level=Level.VD))


def test_balanced_targets():
    import random

    for seed in range(50):
        seq = generator.balanced_targets(10, {3: "D"}, random.Random(seed))
        counts = Counter(seq)
        assert max(counts.values()) - min(counts.values()) <= 1
        assert seq[3] == "D"
        assert generator.longest_run(seq) <= generator.MAX_RUN


def test_variants_keep_correct_answers_and_pins(session):
    spec = generator.load_spec(EXAMPLES / "de-vecto.toml")
    exam = generator.build_exam(session, spec)
    assert len(exam.variants) == 4
    for v in exam.variants:
        mcq = v.data["sections"][0]["questions"]
        assert len(mcq) == 8
        for q, key in zip(mcq, v.answer_key["sections"][0]):
            assert q["choices"]["ABCD".index(key)]["correct"]
            if q["code"] == "12V-007":
                assert key == "D"  # lựa chọn ghim giữ nguyên vị trí D
        counts = Counter(v.answer_key["sections"][0])
        assert max(counts.values()) - min(counts.values()) <= 1
    # Cùng seed thì sinh lại giống hệt
    data, key = generator.make_variant(spec, generator.select_questions(session, spec), "101")
    assert key == exam.variants[0].answer_key


def test_matrix_shortage_is_reported(session):
    spec = {"section": [{"type": "mcq", "pick": [{"tag": "lop-12", "level": "VDC", "count": 1}]}]}
    with pytest.raises(generator.SpecError, match="VDC"):
        generator.select_questions(session, spec)


@pytest.mark.skipif(not latex_available(), reason="chưa cài latexmk/xelatex")
def test_compile_pdf(session, tmp_path):
    spec = generator.load_spec(EXAMPLES / "de-vecto.toml")
    spec["variants"] = 1
    exam = generator.build_exam(session, spec)
    render.copy_style(tmp_path)
    tex = tmp_path / "loigiai.tex"
    tex.write_text(render.render_exam(exam.variants[0].data, solutions=True), encoding="utf-8")
    result = compile_tex(tex)
    assert result.ok, result.error


@pytest.mark.skipif(not latex_available(), reason="chưa cài latexmk/xelatex")
def test_compile_error_points_to_question(tmp_path):
    data = {
        "title": "Lỗi",
        "date": "",
        "duration": None,
        "code": "1",
        "sections": [
            {
                "name": "P",
                "type": "essay",
                "points": None,
                "questions": [
                    {"code": "OK-1", "type": "essay", "stem": "Đúng.", "choices": [], "short_answer": None, "solution": ""},
                    {"code": "HONG-2", "type": "essay", "stem": r"Sai \lenhkhongco.", "choices": [], "short_answer": None, "solution": ""},
                ],
            }
        ],
    }
    render.copy_style(tmp_path)
    tex = tmp_path / "de.tex"
    tex.write_text(render.render_exam(data), encoding="utf-8")
    result = compile_tex(tex)
    assert not result.ok
    assert result.question == "HONG-2"
