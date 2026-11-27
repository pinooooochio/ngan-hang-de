"""Chuyên đề: ghép lý thuyết đã duyệt với bài tập tự luyện chọn từ ngân hàng, theo chủ đề và dạng bài,
đáp án và lời giải ở cuối quyển; xuất một file PDF (biên dịch nền).

Cấu hình (`config`):
    title, date
    parts: [{path, general: bool, dang: [tên dạng]}]   chủ đề, có phần kiến thức chung không, các dạng bài
    levels: {NB, TH, VD, VDC}       số bài tập mỗi mức độ cho mỗi dạng bài
    mixed: {NB, TH, VD, VDC}        số bài tập tổng hợp cuối mỗi chủ đề (câu của chủ đề chưa dùng ở các dạng)
    types: [mcq, tf, short, essay]  loại câu được chọn làm bài tập
    seed
"""

from __future__ import annotations

import logging
import random
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import builds, generator, render, theory
from .bank import find_questions
from .compile import CompileResult, compile_tex
from .models import BuildStatus, Level, Question, QuestionType, Status, TopicDoc
from .parser import slugify

log = logging.getLogger(__name__)

LEVELS = ["NB", "TH", "VD", "VDC"]
TYPES = ["mcq", "tf", "short", "essay"]
MAX_PER_LEVEL = 20


class DocError(Exception):
    pass


def normalize(cfg: dict) -> dict:
    parts = []
    seen = set()
    for p in cfg.get("parts") or []:
        t = theory.find_topic(p.get("path") or "")
        if t is None:
            raise DocError(f"không có chủ đề {p.get('path')} trong khung chương trình")
        if t["path"] in seen:
            continue
        seen.add(t["path"])
        want = set(p.get("dang") or [])
        parts.append({"path": t["path"], "general": bool(p.get("general", True)),
                      "dang": [d for d in t["dang"] if d in want]})
    if not parts:
        raise DocError("chưa chọn chủ đề nào")

    def counts(d: dict | None) -> dict:
        return {lv: max(0, min(MAX_PER_LEVEL, int((d or {}).get(lv, 0) or 0))) for lv in LEVELS}

    types = [t for t in TYPES if t in (cfg.get("types") or TYPES)] or TYPES
    title = (cfg.get("title") or "").strip() or "Chuyên đề " + ", ".join(
        theory.find_topic(p["path"])["ten"] for p in parts[:3])
    return {"title": title[:300], "date": cfg.get("date") or date.today().isoformat(), "parts": parts,
            "levels": counts(cfg.get("levels", {"NB": 2, "TH": 2, "VD": 1})), "mixed": counts(cfg.get("mixed")),
            "types": types, "seed": int(cfg.get("seed") or random.randrange(1, 10**6))}


def _pool(session: Session, tag: str, level: str, types: list[str], used: set[int]) -> list[Question]:
    out = []
    for t in types:
        out += [q for q in find_questions(session, tag=tag, level=Level(level), type=QuestionType(t), approved_only=True)
                if q.id not in used]
    return out


def availability(session: Session, cfg: dict) -> list[dict]:
    """Số câu đã duyệt có sẵn theo chủ đề / dạng / mức độ, số khối lý thuyết đã duyệt, để người soạn chọn."""
    cfg = normalize(cfg)
    out = []
    for p in cfg["parts"]:
        t = theory.find_topic(p["path"])
        blocks = theory.topic_blocks(session, t["path"], approved_only=True)
        n_theory = {d: sum(1 for b in blocks if b.dang == d) for d in [None, *t["dang"]]}
        rows = []
        for d in t["dang"]:
            tag = f"{t['path']}/{slugify(d)}"
            rows.append({"dang": d, "theory": n_theory.get(d, 0),
                         "questions": {lv: len(_pool(session, tag, lv, cfg["types"], set())) for lv in LEVELS}})
        out.append({"path": t["path"], "ten": t["ten"], "names": t["names"], "dang_all": t["dang"],
                     "general_theory": n_theory.get(None, 0), "dang": rows,
                     "topic_questions": {lv: len(_pool(session, t["path"], lv, cfg["types"], set())) for lv in LEVELS}})
    return out


def _question(q: Question, rng: random.Random) -> dict:
    item = generator.snapshot(q, None, rng)
    item["key"] = generator.key_for(item) if item["type"] != "essay" else ""
    item["correct_index"] = next((i + 1 for i, c in enumerate(item["choices"]) if c["correct"]), 0)
    return item


def build_data(session: Session, cfg: dict) -> dict:
    """Chọn bài tập và chụp nội dung lý thuyết / câu hỏi lúc tạo. Mỗi dạng bài lấy đủ số câu theo mức độ nếu
    ngân hàng có (ưu tiên câu ít dùng, mỗi nhóm biến thể một câu); thiếu thì lấy hết và ghi chú lại."""
    rng = random.Random(cfg["seed"])
    usage = generator.usage_counts(session)
    rank = lambda q: usage.get(q.code, 0)  # noqa: E731
    used: set[int] = set()
    groups: set[str] = set()
    notes: list[str] = []
    number = 0
    topics = []

    def pick(tag: str, want: dict, where: str) -> list[dict]:
        nonlocal number
        out = []
        short: list[str] = []
        for lv in LEVELS:
            n = want[lv]
            if not n:
                continue
            pool = _pool(session, tag, lv, cfg["types"], used)
            chosen = generator.pick(pool, min(n, len(pool)), rng, rank, groups)
            if len(chosen) < n:
                short.append(f"{lv} {len(chosen)}/{n}")
            for q in chosen:
                used.add(q.id)
                number += 1
                out.append({**_question(q, rng), "number": number})
        if short:
            notes.append(f"{where}: ngân hàng không đủ câu đã duyệt (lấy được {', '.join(short)})")
        return out

    def theory_items(blocks) -> list[dict]:
        items = []
        refs = {b.ref_code for b in blocks if b.ref_code}
        qs = {q.code: q for q in session.scalars(select(Question).where(Question.code.in_(refs)))} if refs else {}
        for b in blocks:
            item = {"kind": b.kind, "title": b.title, "content": b.content, "ref": b.ref_code, "question": None}
            if b.ref_code:
                q = qs.get(b.ref_code)
                if q is None:
                    continue
                item["question"] = _question(q, rng)
            items.append(item)
        return items

    # câu đã dùng làm ví dụ trong lý thuyết thì không lấy lại làm bài tập
    for p in cfg["parts"]:
        refs = [b.ref_code for b in theory.topic_blocks(session, p["path"], approved_only=True) if b.ref_code]
        for q in session.scalars(select(Question).where(Question.code.in_(refs))) if refs else []:
            used.add(q.id)
            if q.variant_group:
                groups.add(q.variant_group)

    for p in cfg["parts"]:
        t = theory.find_topic(p["path"])
        blocks = theory.topic_blocks(session, t["path"], approved_only=True)
        topic = {"path": t["path"], "ten": t["ten"], "names": t["names"], "general": [], "dang": [], "mixed": []}
        if p["general"]:
            topic["general"] = theory_items([b for b in blocks if b.dang is None])
            if not topic["general"]:
                notes.append(f"{t['ten']}: chưa có lý thuyết chung đã duyệt")
        for d in p["dang"]:
            items = theory_items([b for b in blocks if b.dang == d])
            exercises = pick(f"{t['path']}/{slugify(d)}", cfg["levels"], f"{t['ten']} / {d}")
            if not items:
                notes.append(f"{t['ten']} / {d}: chưa có lý thuyết đã duyệt")
            if items or exercises:  # dạng không có gì thì không in tiêu đề trống
                topic["dang"].append({"name": d, "theory": items, "exercises": exercises})
        topic["mixed"] = pick(t["path"], cfg["mixed"], f"{t['ten']} / tổng hợp")
        topics.append(topic)
    return {"title": cfg["title"], "date": cfg["date"], "topics": topics, "notes": notes, "count": number}


def render_doc(data: dict) -> str:
    exercises = [q for t in data["topics"] for d in t["dang"] for q in d["exercises"]] + \
                [q for t in data["topics"] for q in t["mixed"]]
    exercises.sort(key=lambda q: q["number"])
    return render.make_env().get_template("chuyende.tex.j2").render(
        d=data, date_text=render.date_text(data.get("date")), exercises=exercises,
        has_key=any(q["type"] != "essay" for q in exercises))


def create(session: Session, cfg: dict, username: str | None = None) -> TopicDoc:
    cfg = normalize(cfg)
    data = build_data(session, cfg)
    doc = TopicDoc(title=cfg["title"], config=cfg, data=data, username=username, status=BuildStatus.PENDING,
                   tex=render_doc(data))
    session.add(doc)
    session.commit()
    return doc


def refresh(session: Session, doc: TopicDoc, reselect: bool = False) -> TopicDoc:
    """Cập nhật nội dung theo ngân hàng hiện tại: giữ cấu hình (và bộ số chọn câu, nên cùng câu nếu ngân hàng
    không đổi), hoặc chọn lại câu khác (`reselect`)."""
    cfg = dict(doc.config)
    if reselect:
        cfg["seed"] = random.randrange(1, 10**6)
    doc.config = cfg
    doc.data = build_data(session, cfg)
    doc.tex = render_doc(doc.data)
    doc.status, doc.error, doc.error_question, doc.finished_at = BuildStatus.PENDING, None, None, None
    session.commit()
    return doc


# ---------- Biên dịch nền ----------


def doc_dir(doc_id: int) -> Path:
    return builds.files_dir() / "chuyen-de" / str(doc_id)


def claim_next(session: Session) -> TopicDoc | None:
    stmt = select(TopicDoc).where(TopicDoc.status == BuildStatus.PENDING).order_by(TopicDoc.id).limit(1)
    if session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    doc = session.scalar(stmt)
    if doc is None:
        session.commit()
        return None
    doc.status = BuildStatus.RUNNING
    session.commit()
    return doc


def run(session: Session, doc: TopicDoc) -> TopicDoc:
    target = doc_dir(doc.id) / "chuyen-de.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        render.copy_style(folder)
        tex = folder / "chuyen-de.tex"
        tex.write_text(doc.tex, encoding="utf-8")
        try:
            result = compile_tex(tex)
        except Exception as e:  # noqa: BLE001 - ví dụ thiếu latexmk
            result = CompileResult(False, None, str(e))
        if result.ok and result.pdf:
            shutil.move(str(result.pdf), target)
            doc.status, doc.pdf_path, doc.error, doc.error_question = BuildStatus.DONE, str(target), None, None
        else:
            doc.status, doc.error, doc.error_question = BuildStatus.FAILED, result.error, result.question
    doc.finished_at = datetime.now()
    session.commit()
    return doc


def run_pending(session: Session) -> int:
    n = 0
    while (doc := claim_next(session)) is not None:
        run(session, doc)
        n += 1
    return n


def reset_stale(session: Session) -> None:
    session.execute(update(TopicDoc).where(TopicDoc.status == BuildStatus.RUNNING).values(status=BuildStatus.PENDING))
    session.commit()
