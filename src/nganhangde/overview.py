"""Ngân hàng theo chủ đề: mỗi lớp / học phần trong khung chương trình, mỗi chủ đề và dạng bài kèm số câu đã
duyệt theo mức độ, số câu nháp, số khối lý thuyết, số chuyên đề đã tạo. Tính một lần cho cả ngân hàng."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .aigen import load_curriculum
from .models import Question, QuestionTag, Status, TaxonomyNode, TheoryBlock, TopicDoc
from .parser import slugify

LEVELS = ["NB", "TH", "VD", "VDC"]


def _empty() -> dict:
    return {"approved": set(), "draft": set(), "levels": {lv: set() for lv in LEVELS}}


def _add(bucket: dict, qid: int, status: Status, level) -> None:
    if status == Status.APPROVED:
        bucket["approved"].add(qid)
        if level is not None:
            bucket["levels"][level.value].add(qid)
    else:
        bucket["draft"].add(qid)


def _out(bucket: dict) -> dict:
    return {"approved": len(bucket["approved"]), "draft": len(bucket["draft"]),
            "levels": {lv: len(s) for lv, s in bucket["levels"].items()}}


def overview(session: Session) -> dict:
    grades = load_curriculum()
    # chủ đề theo đường dẫn; dạng bài theo slug
    topics: dict[str, dict] = {}
    for g in grades:
        for t in g["chu_de"]:
            if t.get("label"):
                continue
            topics[t["path"]] = {"t": t, "grade": g["slug"], "all": _empty(),
                                 "dang": {slugify(d): _empty() for d in t["dang"]}}
    grade_q = {g["slug"]: _empty() for g in grades}

    rows = session.execute(
        select(Question.id, Question.status, Question.level, TaxonomyNode.path)
        .join(QuestionTag, QuestionTag.question_id == Question.id)
        .join(TaxonomyNode, TaxonomyNode.id == QuestionTag.node_id))
    for qid, status, level, path in rows:
        parts = path.split("/")
        if parts[0] in grade_q:
            _add(grade_q[parts[0]], qid, status, level)
        for i in range(len(parts), 0, -1):
            info = topics.get("/".join(parts[:i]))
            if info is None:
                continue
            _add(info["all"], qid, status, level)
            if i < len(parts) and parts[i] in info["dang"]:
                _add(info["dang"][parts[i]], qid, status, level)
            break

    theory: dict[tuple[str, str | None], dict] = {}
    for path, dang, status in session.execute(select(TheoryBlock.topic_path, TheoryBlock.dang, TheoryBlock.status)):
        c = theory.setdefault((path, dang), {"approved": 0, "draft": 0})
        c[status.value] += 1

    # số chuyên đề theo chủ đề và theo lớp (mỗi chuyên đề tính một lần cho mỗi lớp dù gồm nhiều chủ đề)
    docs: dict[str, int] = {}
    per_grade: dict[str, int] = {}
    for (cfg,) in session.execute(select(TopicDoc.config)):
        paths = {p.get("path") for p in (cfg or {}).get("parts") or [] if p.get("path")}
        for p in paths:
            docs[p] = docs.get(p, 0) + 1
        for s in {p.split("/")[0] for p in paths}:
            per_grade[s] = per_grade.get(s, 0) + 1

    out = []
    for g in grades:
        items = []
        for t in g["chu_de"]:
            info = topics.get(t["path"])
            if info is None:
                continue
            th = {"approved": 0, "draft": 0}
            for (path, _dang), c in theory.items():
                if path == t["path"]:
                    th["approved"] += c["approved"]
                    th["draft"] += c["draft"]
            items.append({
                "path": t["path"], "ten": t["ten"], "chuong": t["chuong"],
                **_out(info["all"]),
                "theory": th, "docs": docs.get(t["path"], 0),
                "dang": [{"name": d, **_out(info["dang"][slugify(d)]),
                          "theory": theory.get((t["path"], d), {"approved": 0, "draft": 0})} for d in t["dang"]],
            })
        if not items:
            continue
        out.append({"ten": g["ten"], "slug": g["slug"], "bac": g["bac"], "ghi_chu": g.get("ghi_chu", ""),
                    **_out(grade_q[g["slug"]]), "docs": per_grade.get(g["slug"], 0), "topics": items})
    inside = set().union(*(b["approved"] | b["draft"] for b in grade_q.values())) if grade_q else set()
    total = {st.value: 0 for st in Status}
    other = 0
    for qid, status in session.execute(select(Question.id, Question.status)):
        total[status.value] += 1
        other += qid not in inside
    return {"grades": out, "levels": LEVELS, "total": total, "other": other}
