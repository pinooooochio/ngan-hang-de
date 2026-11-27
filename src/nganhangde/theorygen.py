"""Claude soạn lý thuyết theo chủ đề: dựng prompt từ khung chương trình, nhận kết quả (gọi API qua worker
sinh câu, hoặc người dùng dán lại), tách khối và thêm vào lý thuyết của chủ đề ở dạng nháp, nguồn "AI #n".

Dùng chung bảng `generation_batches` (cột `kind` = "theory") và worker với phần sinh câu hỏi."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import aigen, theory
from .models import BuildStatus, GenerationBatch

KIND = "theory"
MAX_EXAMPLES = 4
MAX_TOPICS = 40  # số chủ đề tối đa của một đợt soạn qua API

SYSTEM = r"""Bạn là giáo viên Toán giàu kinh nghiệm, soạn phần LÝ THUYẾT cho tài liệu chuyên đề ôn tập
(THPT theo Chương trình giáo dục phổ thông môn Toán 2018; đại học theo đề cương học phần). Viết tiếng Việt,
chính xác, gọn, đúng thuật ngữ và kí hiệu của sách giáo khoa / giáo trình.

ĐỊNH DẠNG BẮT BUỘC (LaTeX, chỉ dùng các môi trường sau, mỗi khối một ý):
\begin{dinhnghia}[Tên khái niệm] ... \end{dinhnghia}
\begin{dinhly}[Tên định lý hoặc tính chất] ... \end{dinhly}
\begin{congthuc}[Tên nhóm công thức, có thể bỏ] ... \end{congthuc}
\begin{phuongphap}[Tên cách giải, có thể bỏ] các bước giải, dùng enumerate hoặc itemize \end{phuongphap}
\begin{vidu}[Tiêu đề ngắn] đề bài ... \begin{loigiai} lời giải đầy đủ \end{loigiai} \end{vidu}
\begin{luuy} sai lầm thường gặp, điều kiện hay bị quên, mẹo kiểm tra \end{luuy}

Dòng `% @dang: <tên dạng>` (chép đúng nguyên văn tên dạng được giao) đứng trước các khối của dạng bài đó.
Các khối đứng trước dòng `% @dang` đầu tiên là kiến thức chung của chủ đề.

QUY TẮC:
- Công thức trong $...$ hoặc \[...\]; dùng lệnh LaTeX chuẩn (\dfrac, \sqrt, \overrightarrow, \widehat, \left( \right) ...).
  Không định nghĩa lệnh mới, không dùng gói lạ.
- Không viết \documentclass, \begin{document}, \section, không bọc kết quả trong ```.
- Chỉ vẽ hình TikZ (tikzpicture) khi thật cần, hình đơn giản, có toạ độ cụ thể.
- Ví dụ có số liệu cụ thể, từ dễ đến khó; lời giải trình bày từng bước như bài giảng, tính đúng, tự kiểm tra
  lại đáp số trước khi viết.
- Mỗi khối chỉ một nội dung; tiêu đề trong ngoặc vuông ngắn gọn.
- Chỉ trả về nội dung LaTeX theo định dạng trên, không lời dẫn, không giải thích thêm."""


def normalize(p: dict) -> dict:
    t = theory.find_topic(p.get("path") or "")
    if t is None:
        raise aigen.GenError(f"không có chủ đề {p.get('path')} trong khung chương trình")
    dang = [d for d in t["dang"] if d in set(p.get("dang") or [])]
    general = bool(p.get("general", True))
    if not general and not dang:
        raise aigen.GenError(f"{t['ten']}: chưa chọn phần nào để soạn (kiến thức chung hoặc một dạng bài)")
    examples = max(0, min(MAX_EXAMPLES, int(p.get("examples", 2))))
    return {"path": t["path"], "general": general, "dang": dang, "examples": examples,
            "note": (p.get("note") or "").strip()}


def missing_parts(session: Session, topic: dict) -> dict:
    """Phần chủ đề chưa có lý thuyết: kiến thức chung, các dạng bài."""
    have = {b.dang for b in theory.topic_blocks(session, topic["path"])}
    return {"general": None not in have, "dang": [d for d in topic["dang"] if d not in have]}


def build_prompt(session: Session, p: dict) -> tuple[str, str]:
    t = theory.find_topic(p["path"])
    assert t is not None
    grade = next(g for g in aigen.load_curriculum() if g["slug"] == p["path"].split("/")[0])
    lines = [f"Soạn lý thuyết cho chủ đề: {' / '.join(t['names'])} (bậc {grade['bac']})."]
    if grade.get("ghi_chu"):
        lines.append(f"Ghi chú về lớp / học phần: {grade['ghi_chu']}")
    if t["ghi_chu"]:
        lines.append(f"Ghi chú về chủ đề: {t['ghi_chu']}")
    if t["noi_dung"]:
        lines += ["", "Kiến thức trọng tâm theo đề cương:", t["noi_dung"]]
    lines += ["", "PHẦN CẦN SOẠN:"]
    n = 0
    if p["general"]:
        n += 1
        lines.append(f"{n}. Kiến thức chung của chủ đề (trước mọi dòng % @dang): các định nghĩa, định lý / tính chất, "
                     "công thức cần nhớ, đủ để học sinh dùng cho mọi dạng bài.")
    if p["dang"]:
        n += 1
        ex = (f"{p['examples']} ví dụ có lời giải (từ dễ đến khó)" if p["examples"]
              else "không cần ví dụ")
        lines.append(f"{n}. Với mỗi dạng bài dưới đây, viết dòng % @dang rồi: một khối phương pháp giải, {ex}, "
                     "và một khối lưu ý nếu dạng có sai lầm hay gặp. Tên dạng (chép đúng):")
        lines += [f"   - {d}" for d in p["dang"]]
    existing = theory.topic_blocks(session, t["path"])
    if existing:
        lines += ["", "Lý thuyết đã có của chủ đề (không viết lại các nội dung này):"]
        for b in existing[:60]:
            label = theory.KINDS.get(b.kind, b.kind)
            what = b.title or (f"câu {b.ref_code}" if b.ref_code else aigen._short(b.content, 80))
            lines.append(f"- [{b.dang or 'kiến thức chung'}] {label}: {what}")
    if p["note"]:
        lines += ["", f"Yêu cầu thêm của người soạn: {p['note']}"]
    return SYSTEM, "\n".join(lines)


def create(session: Session, params: dict, mode: str, output: str | None = None, user_id: int | None = None,
           username: str | None = None, group_id: str | None = None) -> GenerationBatch:
    p = normalize(params)
    system, user = build_prompt(session, p)
    batch = GenerationBatch(kind=KIND, mode=mode, status=BuildStatus.PENDING, params=p, system_prompt=system,
                            user_prompt=user, model=aigen.model_name() if mode == "api" else None, items=[],
                            user_id=user_id, username=username, group_id=group_id)
    session.add(batch)
    session.flush()
    if mode == "manual":
        if not (output or "").strip():
            raise aigen.GenError("chưa dán kết quả")
        import_batch(session, batch, output)
    else:
        if not aigen.api_available():
            raise aigen.GenError("máy chủ chưa có ANTHROPIC_API_KEY, hãy dùng cách chép prompt")
        session.commit()
    return batch


def import_batch(session: Session, batch: GenerationBatch, text: str) -> None:
    """Tách khối từ kết quả và thêm vào lý thuyết của chủ đề (nháp). Lỗi định dạng thì lần soạn thất bại,
    giữ nguyên kết quả để xem lại."""
    t = theory.find_topic(batch.params["path"])
    batch.output = text
    batch.finished_at = datetime.now()
    if t is None:
        batch.status, batch.error = BuildStatus.FAILED, f"không còn chủ đề {batch.params['path']} trong khung chương trình"
        session.commit()
        return
    parsed = theory.parse(aigen.strip_fences(text), t)
    blocks = [b for sec in parsed.sections if sec.topic["path"] == t["path"] for b in sec.blocks]
    if parsed.errors:
        batch.status = BuildStatus.FAILED
        batch.error = "; ".join(f"dòng {ln}: {m}" for ln, m in parsed.errors[:5])
        session.commit()
        return
    if not blocks:
        batch.status, batch.error = BuildStatus.FAILED, "không tìm thấy khối lý thuyết nào trong kết quả"
        session.commit()
        return
    r = theory.save_topic(session, t, blocks, username=batch.username, source=batch.source, append=True,
                          action="ai")
    kinds: dict[str, int] = {}
    for b in blocks:
        kinds[b.kind] = kinds.get(b.kind, 0) + 1
    batch.items = [{"state": "theory", "path": t["path"], "added": r["added"], "kinds": kinds}]
    batch.status = BuildStatus.DONE
    batch.error = None
    session.commit()


def batches(session: Session, path: str | None = None, limit: int = 50) -> list[GenerationBatch]:
    rows = session.scalars(select(GenerationBatch).where(GenerationBatch.kind == KIND)
                           .order_by(GenerationBatch.id.desc()).limit(500))
    return [b for b in rows if path is None or b.params.get("path") == path][:limit]
