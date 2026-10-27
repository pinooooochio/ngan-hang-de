"""Luyện đề: tạo lượt làm bài, chấm điểm tự động và thống kê kết quả.

Cách chấm theo đề tốt nghiệp THPT môn Toán từ 2025:
- Trắc nghiệm nhiều phương án: đúng được trọn điểm câu (mặc định 0,25).
- Đúng/sai 4 ý: đúng 1 ý được 10% điểm câu, 2 ý 25%, 3 ý 50%, 4 ý 100% (mặc định 1 điểm).
- Trả lời ngắn: khớp đáp án được trọn điểm (mặc định 0,5); số được so theo giá trị,
  chấp nhận dấu phẩy hay dấu chấm thập phân.
- Tự luận: không chấm tự động, chỉ hiện lời giải.

Câu trả lời gửi lên là một dict, khoá "phần.câu" (đếm từ 0):
- mcq: chỉ số lựa chọn 0..3
- tf: danh sách 4 giá trị true / false / null
- short, essay: chuỗi
"""

from __future__ import annotations

import copy
import random
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import bank, generator
from .models import Attempt, AttemptItem, Exam, Question, TaxonomyNode

DEFAULT_POINTS = {"mcq": 0.25, "tf": 1.0, "short": 0.5, "essay": 0.0}
SECTION_NAMES = {"mcq": "Trắc nghiệm", "tf": "Đúng/sai", "short": "Trả lời ngắn", "essay": "Tự luận"}
TF_SCALE = [0, 0.1, 0.25, 0.5, 1.0]  # tỉ lệ điểm theo số ý đúng
GRACE = timedelta(seconds=30)  # nộp quá giờ trong khoảng này vẫn tính là đúng giờ


class PracticeError(Exception):
    pass


# ---------- Chấm điểm ----------


def section_points(section: dict) -> float:
    pts = section.get("points")
    return float(pts) if pts is not None else DEFAULT_POINTS[section["type"]]


def parse_number(text: str) -> float | None:
    t = text.strip().replace(" ", "").replace("$", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def short_matches(answer: str | None, expected: str | None) -> bool:
    if answer is None or expected is None or not str(answer).strip():
        return False
    a, e = parse_number(str(answer)), parse_number(expected)
    if a is not None and e is not None:
        return abs(a - e) <= 1e-9 * max(1.0, abs(e))
    norm = lambda s: "".join(str(s).split()).casefold()  # noqa: E731
    return norm(answer) == norm(expected)


def grade_question(q: dict, answer, points: float) -> tuple[float, bool | None]:
    """Trả về (điểm đạt được, đúng hoàn toàn hay không). Tự luận trả về (0, None)."""
    if q["type"] == "mcq":
        right = next((i for i, c in enumerate(q["choices"]) if c["correct"]), None)
        ok = isinstance(answer, int) and not isinstance(answer, bool) and answer == right
        return (points if ok else 0.0), ok
    if q["type"] == "tf":
        given = answer if isinstance(answer, list) else []
        n_right = sum(
            1 for i, c in enumerate(q["choices"]) if i < len(given) and given[i] is not None and given[i] == c["correct"]
        )
        n_right = min(n_right, len(TF_SCALE) - 1)
        return round(points * TF_SCALE[n_right], 4), n_right == len(q["choices"])
    if q["type"] == "short":
        ok = short_matches(answer, q.get("short_answer"))
        return (points if ok else 0.0), ok
    return 0.0, None


def public_data(data: dict) -> dict:
    """Bản đề gửi cho người đang làm bài: bỏ đáp án và lời giải."""
    out = copy.deepcopy(data)
    for sec in out["sections"]:
        for q in sec["questions"]:
            q["choices"] = [{"content": c["content"]} for c in q["choices"]]
            q["short_answer"] = None
            q["solution"] = ""
    return out


# ---------- Tạo lượt làm bài ----------


def start_from_exam(session: Session, exam: Exam, variant_code: str | None = None, timed: bool = True) -> Attempt:
    if not exam.variants:
        raise PracticeError("đề chưa có mã đề nào")
    if variant_code:
        variant = next((v for v in exam.variants if v.code == variant_code), None)
        if variant is None:
            raise PracticeError(f"đề không có mã {variant_code}")
    else:
        variant = random.choice(exam.variants)
    attempt = Attempt(
        exam_id=exam.id,
        kind="exam",
        title=exam.title,
        variant_code=variant.code,
        data=copy.deepcopy(variant.data),
        answers={},
        duration=exam.duration if timed else None,
    )
    session.add(attempt)
    session.commit()
    return attempt


def start_quick(session: Session, spec: dict, duration: int | None = None) -> Attempt:
    """Luyện nhanh: chọn câu ngẫu nhiên theo cấu hình giống cấu hình đề, sinh một mã đề duy nhất."""
    spec = {**spec, "seed": spec.get("seed") or random.randint(1, 10**6)}
    try:
        sections = generator.select_questions(session, spec)
    except generator.SpecError as e:
        raise PracticeError(str(e)) from e
    if not any(sections):
        raise PracticeError("chưa chọn câu nào")
    data, _ = generator.make_variant(spec, sections, "LT")
    data["sections"] = [s for s in data["sections"] if s["questions"]]
    attempt = Attempt(
        kind="quick",
        title=spec.get("title") or "Luyện nhanh",
        data=data,
        answers={},
        duration=duration,
    )
    session.add(attempt)
    session.commit()
    return attempt


def quick_spec(title: str | None, tag: str | None, level: str | None, counts: dict[str, int]) -> dict:
    cell = {k: v for k, v in {"tag": tag, "level": level}.items() if v}
    sections = [
        {"name": SECTION_NAMES[t], "type": t, "pick": [{**cell, "count": n}]} for t, n in counts.items() if n > 0
    ]
    return {"title": title or "Luyện nhanh", "section": sections}


def retry_spec(attempt: Attempt) -> dict:
    """Cấu hình luyện lại các câu chưa đúng hoàn toàn của một lượt đã nộp."""
    by_type: dict[str, list[str]] = defaultdict(list)
    for it in attempt.items:
        if it.correct is False and it.question_code not in by_type[it.type]:
            by_type[it.type].append(it.question_code)
    if not by_type:
        raise PracticeError("lượt này không có câu sai để luyện lại")
    order = ["mcq", "tf", "short"]
    return {
        "title": f"Luyện lại câu sai: {attempt.title}",
        "section": [{"name": SECTION_NAMES[t], "type": t, "ids": by_type[t]} for t in order if by_type.get(t)],
    }


# ---------- Làm bài và nộp bài ----------


def deadline(attempt: Attempt) -> datetime | None:
    return attempt.started_at + timedelta(minutes=attempt.duration) if attempt.duration else None


def save_answers(session: Session, attempt: Attempt, answers: dict) -> None:
    if attempt.submitted_at is not None:
        raise PracticeError("bài đã nộp, không sửa được câu trả lời")
    attempt.answers = dict(answers)
    session.commit()


def submit(session: Session, attempt: Attempt, answers: dict | None = None) -> Attempt:
    if attempt.submitted_at is not None:
        raise PracticeError("bài đã nộp")
    if answers is not None:
        attempt.answers = dict(answers)
    codes = {q["code"] for sec in attempt.data["sections"] for q in sec["questions"]}
    tags_of = {
        q.code: [t.path for t in q.tags]
        for q in session.scalars(select(Question).where(Question.code.in_(codes)))
    }
    total = possible = 0.0
    attempt.items.clear()
    for si, sec in enumerate(attempt.data["sections"]):
        pts = section_points(sec)
        for qi, q in enumerate(sec["questions"]):
            earned, ok = grade_question(q, attempt.answers.get(f"{si}.{qi}"), pts)
            max_pts = pts if q["type"] != "essay" else 0.0
            total += earned
            possible += max_pts
            attempt.items.append(
                AttemptItem(
                    section=si,
                    position=qi,
                    question_code=q["code"],
                    type=q["type"],
                    level=q.get("level"),
                    tags=tags_of.get(q["code"], []),
                    points=earned,
                    max_points=max_pts,
                    correct=ok,
                )
            )
    attempt.score = round(total, 4)
    attempt.max_score = round(possible, 4)
    attempt.submitted_at = datetime.now()
    session.commit()
    return attempt


def is_late(attempt: Attempt) -> bool:
    end = deadline(attempt)
    return bool(end and attempt.submitted_at and attempt.submitted_at > end + GRACE)


# ---------- Thống kê ----------


def stats(session: Session, depth: int = 2, user_id: int | None = None) -> dict:
    """Tỉ lệ điểm theo mức độ và theo thẻ (đến độ sâu `depth`: lớp, chủ đề) trên các lượt đã nộp
    (của một người nếu có `user_id`)."""
    stmt = select(AttemptItem).join(Attempt).where(Attempt.submitted_at.is_not(None), AttemptItem.max_points > 0)
    if user_id is not None:
        stmt = stmt.where(Attempt.user_id == user_id)
    items = session.scalars(stmt).all()

    def bucket():
        return {"n": 0, "right": 0, "points": 0.0, "max_points": 0.0}

    by_level: dict[str, dict] = defaultdict(bucket)
    by_tag: dict[str, dict] = defaultdict(bucket)
    for it in items:
        groups = [("level", it.level or "")]
        prefixes = {"/".join(p.split("/")[:d]) for p in it.tags for d in range(1, depth + 1) if len(p.split("/")) >= d}
        groups += [("tag", p) for p in prefixes]
        for kind, key in groups:
            b = (by_level if kind == "level" else by_tag)[key]
            b["n"] += 1
            b["right"] += 1 if it.correct else 0
            b["points"] += it.points
            b["max_points"] += it.max_points

    nodes = {n.path: n for n in session.scalars(select(TaxonomyNode).where(TaxonomyNode.path.in_(list(by_tag))))}

    def finish(b: dict) -> dict:
        return {**b, "points": round(b["points"], 4), "max_points": round(b["max_points"], 4),
                "ratio": round(b["points"] / b["max_points"], 4) if b["max_points"] else None}

    tags = [
        {"path": p, "names": bank.tag_names(nodes[p]) if p in nodes else [p], "depth": p.count("/"), **finish(b)}
        for p, b in sorted(by_tag.items())
    ]
    return {
        "attempts": session.scalar(select(func.count(Attempt.id)).where(Attempt.submitted_at.is_not(None))),
        "by_level": {k: finish(b) for k, b in by_level.items()},
        "by_tag": tags,
    }
