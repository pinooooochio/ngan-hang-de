"""Lập đề từ file cấu hình và sinh các mã đề có đảo câu, đảo đáp án.

Cấu hình đề (TOML):

    title = "Kiểm tra Vectơ trong không gian"
    date = "2026-10-22"
    duration = 45          # phút
    variants = 4           # số mã đề
    first_code = 101
    seed = 2026

    [[section]]
    name = "PHẦN I. Câu trắc nghiệm nhiều phương án lựa chọn"
    type = "mcq"           # mcq | tf | short | essay
    points = 0.25          # điểm mỗi câu (tuỳ chọn)
    pick = [ { tag = "lop-12/vecto-trong-khong-gian", level = "NB", count = 2 } ]
    # hoặc chọn tay: ids = ["2H3-001", "2H3-002"]
"""

from __future__ import annotations

import random
import tomllib
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .bank import find_questions
from .models import Exam, ExamItem, ExamVariant, Level, Question, QuestionType

LETTERS = "ABCD"
MAX_RUN = 3  # không quá 3 câu liên tiếp cùng chữ cái đáp án


class SpecError(Exception):
    pass


def load_spec(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def select_questions(session: Session, spec: dict) -> list[list[Question]]:
    """Chọn câu cho từng phần. Kết quả giống nhau cho mọi mã đề."""
    rng = random.Random(f"{spec.get('seed', 0)}-chon-cau")
    used: set[int] = set()
    sections: list[list[Question]] = []
    problems: list[str] = []
    for si, sec in enumerate(spec.get("section", []), 1):
        try:
            qtype = QuestionType(sec.get("type", "mcq"))
        except ValueError:
            raise SpecError(f"Phần {si}: loại câu không hợp lệ {sec.get('type')!r}")
        chosen: list[Question] = []
        for code in sec.get("ids", []):
            q = session.scalar(select(Question).where(Question.code == code))
            if q is None:
                problems.append(f"Phần {si}: không có câu {code}")
            elif q.type != qtype:
                problems.append(f"Phần {si}: câu {code} là loại {q.type.value}, phần này cần {qtype.value}")
            else:
                chosen.append(q)
                used.add(q.id)
        for cell in sec.get("pick", []):
            level = Level(cell["level"]) if cell.get("level") else None
            count = int(cell.get("count", 1))
            pool = [
                q
                for q in find_questions(session, tag=cell.get("tag"), level=level, type=qtype, approved_only=True)
                if q.id not in used
            ]
            if len(pool) < count:
                label = f"thẻ {cell.get('tag') or '(mọi)'}, mức {cell.get('level') or '(mọi)'}"
                problems.append(f"Phần {si}: {label} cần {count} câu, ngân hàng chỉ còn {len(pool)}")
                continue
            picked = rng.sample(pool, count)
            chosen.extend(picked)
            used.update(q.id for q in picked)
        sections.append(chosen)
    if problems:
        raise SpecError("\n".join(problems))
    return sections


def balanced_targets(n: int, fixed: dict[int, str], rng: random.Random) -> list[str | None]:
    """Chọn chữ cái đáp án đích cho n câu sao cho số lần A/B/C/D chênh nhau tối đa 1
    (tính cả các câu có đáp án cố định trong `fixed`) và không có chuỗi dài hơn MAX_RUN."""
    counts = Counter({L: 0 for L in LETTERS})
    counts.update(fixed.values())
    free = [i for i in range(n) if i not in fixed]
    pool: list[str] = []
    for _ in free:
        low = min(counts.values())
        letter = rng.choice([L for L in LETTERS if counts[L] == low])
        counts[letter] += 1
        pool.append(letter)
    best: list[str | None] = []
    for _ in range(500):
        rng.shuffle(pool)
        seq: list[str | None] = [fixed.get(i) for i in range(n)]
        for i, letter in zip(free, pool):
            seq[i] = letter
        best = seq
        if longest_run(seq) <= MAX_RUN:
            break
    return best


def longest_run(seq: list) -> int:
    best = run = 0
    prev = object()
    for x in seq:
        run = run + 1 if x == prev else 1
        prev = x
        best = max(best, run)
    return best


def permute_choices(q: Question, rng: random.Random, target: int | None = None) -> list[int]:
    """Trả về hoán vị: perm[vị trí mới] = vị trí gốc. Lựa chọn `pinned` giữ nguyên chỗ.
    Nếu có `target`, đặt đáp án đúng vào vị trí đó (khi vị trí đó không bị ghim)."""
    n = len(q.choices)
    perm: list[int | None] = [None] * n
    free_slots = []
    movable = []
    for c in q.choices:
        if c.pinned:
            perm[c.position] = c.position
        else:
            free_slots.append(c.position)
            movable.append(c.position)
    correct = next((c.position for c in q.choices if c.is_correct and not c.pinned), None)
    if target is not None and correct is not None and target in free_slots:
        perm[target] = correct
        free_slots.remove(target)
        movable.remove(correct)
    rng.shuffle(movable)
    for slot, orig in zip(free_slots, movable):
        perm[slot] = orig
    return [p for p in perm if p is not None]


def snapshot(q: Question, perm: list[int] | None) -> dict:
    choices = list(q.choices)
    if perm is not None:
        choices = [choices[i] for i in perm]
    return {
        "code": q.code,
        "type": q.type.value,
        "level": q.level.value if q.level else None,
        "stem": q.stem_latex,
        "choices": [{"content": c.content_latex, "correct": c.is_correct} for c in choices],
        "short_answer": q.short_answer,
        "solution": q.solution_latex,
    }


def key_for(item: dict) -> str:
    if item["type"] == "mcq":
        return LETTERS[next(i for i, c in enumerate(item["choices"]) if c["correct"])]
    if item["type"] == "tf":
        return "".join("Đ" if c["correct"] else "S" for c in item["choices"])
    if item["type"] == "short":
        return item["short_answer"] or ""
    return ""


def make_variant(spec: dict, sections: list[list[Question]], code: str) -> tuple[dict, dict]:
    seed = f"{spec.get('seed', 0)}-{code}"
    rng = random.Random(seed)
    out_sections = []
    keys = []
    for sec, questions in zip(spec.get("section", []), sections):
        qs = list(questions)
        if sec.get("shuffle", True):
            rng.shuffle(qs)
        qtype = QuestionType(sec.get("type", "mcq"))
        items = []
        if qtype == QuestionType.MCQ:
            fixed = {
                i: LETTERS[c.position]
                for i, q in enumerate(qs)
                for c in q.choices
                if c.is_correct and c.pinned
            }
            targets = balanced_targets(len(qs), fixed, rng)
            for q, t in zip(qs, targets):
                perm = permute_choices(q, rng, LETTERS.index(t) if t else None)
                items.append(snapshot(q, perm))
        elif qtype == QuestionType.TRUE_FALSE:
            items = [snapshot(q, permute_choices(q, rng)) for q in qs]
        else:
            items = [snapshot(q, None) for q in qs]
        out_sections.append({"name": sec.get("name", ""), "type": qtype.value, "points": sec.get("points"), "questions": items})
        keys.append([key_for(it) for it in items])
    data = {
        "title": spec.get("title", "Đề kiểm tra"),
        "date": str(spec.get("date", "")),
        "duration": spec.get("duration"),
        "code": code,
        "sections": out_sections,
    }
    return data, {"sections": keys}


def build_exam(session: Session, spec: dict) -> Exam:
    sections = select_questions(session, spec)
    exam = Exam(
        title=spec.get("title", "Đề kiểm tra"),
        exam_date=str(spec.get("date", "")) or None,
        duration=spec.get("duration"),
        config=spec,
    )
    for si, (sec, qs) in enumerate(zip(spec.get("section", []), sections)):
        for pi, q in enumerate(qs):
            exam.items.append(ExamItem(question=q, section=si, position=pi, points=sec.get("points")))
    first = int(spec.get("first_code", 101))
    for k in range(int(spec.get("variants", 1))):
        code = str(first + k)
        data, key = make_variant(spec, sections, code)
        exam.variants.append(ExamVariant(code=code, seed=f"{spec.get('seed', 0)}-{code}", data=data, answer_key=key))
    session.add(exam)
    session.commit()
    return exam
