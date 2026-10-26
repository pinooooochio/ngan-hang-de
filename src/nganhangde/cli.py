"""Dòng lệnh `nhd`."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from sqlalchemy import select

from . import aigen, bank, builds, compile as tex, generator, render
from .db import make_session
from .models import LEVEL_NAMES, Level, Question, QuestionType, Status
from .parser import parse_text, slugify

app = typer.Typer(help="Ngân hàng câu hỏi và sinh đề thi LaTeX.", no_args_is_help=True, add_completion=False)

TYPE_NAMES = {
    QuestionType.MCQ: "trắc nghiệm",
    QuestionType.TRUE_FALSE: "đúng/sai",
    QuestionType.SHORT: "trả lời ngắn",
    QuestionType.ESSAY: "tự luận",
}


@app.command("import")
def import_cmd(
    file: Path = typer.Argument(..., exists=True, help="File .tex chứa các khối \\begin{ex}"),
    dry_run: bool = typer.Option(False, "--thu", help="Chỉ kiểm tra, không lưu"),
    draft: bool = typer.Option(False, "--nhap", help="Lưu ở trạng thái nháp (chưa dùng để sinh đề)"),
):
    """Import câu hỏi từ file .tex."""
    parsed = parse_text(file.read_text(encoding="utf-8"))
    if not parsed:
        typer.echo("Không tìm thấy khối \\begin{ex} nào.")
        raise typer.Exit(1)
    session = make_session()
    report = bank.import_questions(
        session, parsed, source=file.name, status=Status.DRAFT if draft else Status.APPROVED, dry_run=dry_run
    )
    for pq in report.failed:
        typer.secho(f"  LỖI dòng {pq.line}: " + "; ".join(pq.errors), fg="red")
    for pq in report.warned:
        typer.secho(f"  Cảnh báo dòng {pq.line}: " + "; ".join(pq.warnings), fg="yellow")
    for line, code in report.duplicates:
        typer.echo(f"  Bỏ qua dòng {line}: trùng câu {code}")
    verb = "Sẽ thêm" if dry_run else "Đã thêm"
    typer.secho(
        f"{verb} {len(report.added)} câu, {len(report.duplicates)} câu trùng, {len(report.failed)} câu lỗi.",
        bold=True,
    )
    if report.failed:
        raise typer.Exit(1)


@app.command("list")
def list_cmd(
    tag: Optional[str] = typer.Option(None, "--the", help="Đường dẫn thẻ, ví dụ lop-12/vecto"),
    level: Optional[Level] = typer.Option(None, "--muc", help="NB, TH, VD, VDC"),
    qtype: Optional[QuestionType] = typer.Option(None, "--loai", help="mcq, tf, short, essay"),
):
    """Liệt kê câu hỏi theo bộ lọc."""
    session = make_session()
    qs = bank.find_questions(session, tag=tag, level=level, type=qtype)
    for q in qs:
        stem = " ".join(q.stem_latex.split())
        stem = stem if len(stem) <= 70 else stem[:67] + "..."
        lv = q.level.value if q.level else "-"
        draft = " [nháp]" if q.status == Status.DRAFT else ""
        typer.echo(f"{q.code:<12} {lv:<4} {TYPE_NAMES[q.type]:<13} {stem}{draft}")
    typer.echo(f"Tổng: {len(qs)} câu")


@app.command("tags")
def tags_cmd():
    """In cây thẻ và số câu mỗi nhánh."""
    session = make_session()
    tree = bank.tag_tree(session)
    if not tree:
        typer.echo("Chưa có thẻ nào.")
    for node, depth, count in tree:
        typer.echo(f"{'  ' * depth}{node.name}  ({count})   [{node.path}]")


@app.command("show")
def show_cmd(code: str):
    """Xem chi tiết một câu hỏi."""
    session = make_session()
    q = session.scalar(select(Question).where(Question.code == code))
    if q is None:
        typer.echo(f"Không có câu {code}")
        raise typer.Exit(1)
    typer.secho(f"{q.code} · {TYPE_NAMES[q.type]} · {LEVEL_NAMES.get(q.level, 'chưa có mức độ')}", bold=True)
    typer.echo("Thẻ: " + (", ".join(t.path for t in q.tags) or "(chưa có)"))
    typer.echo(q.stem_latex)
    for i, c in enumerate(q.choices):
        mark = "*" if c.is_correct else " "
        pin = " (ghim)" if c.pinned else ""
        typer.echo(f" {mark} {'ABCD'[i] if q.type == QuestionType.MCQ else 'abcd'[i]}. {c.content_latex}{pin}")
    if q.short_answer:
        typer.echo(f"Đáp án: {q.short_answer}")
    if q.solution_latex:
        typer.echo("Lời giải: " + q.solution_latex)


@app.command("build")
def build_cmd(
    spec_file: Path = typer.Argument(..., exists=True, help="File cấu hình đề .toml"),
    out: Path = typer.Option(Path("out"), "--ra", help="Thư mục xuất"),
    no_pdf: bool = typer.Option(False, "--chi-tex", help="Chỉ sinh .tex, không biên dịch PDF"),
):
    """Sinh đề và các mã đề từ file cấu hình, xuất .tex và PDF."""
    spec = generator.load_spec(spec_file)
    session = make_session()
    try:
        exam = generator.build_exam(session, spec)
    except generator.SpecError as e:
        typer.secho("Không lập được đề:\n" + str(e), fg="red")
        raise typer.Exit(1)

    folder = out / f"{slugify(exam.title)}-{exam.exam_date or exam.id}"
    folder.mkdir(parents=True, exist_ok=True)
    render.copy_style(folder)
    files: list[Path] = []
    for name, _kind, _code, content in builds.exam_documents(exam):
        p = folder / f"{name}.tex"
        p.write_text(content, encoding="utf-8")
        files.append(p)
    typer.echo(f"Đề #{exam.id}: {len(exam.variants)} mã đề, {len(exam.items)} câu → {folder}")

    if no_pdf:
        return
    if not tex.latex_available():
        typer.secho("Không tìm thấy latexmk/xelatex; đã sinh .tex, chưa biên dịch PDF.", fg="yellow")
        raise typer.Exit(1)
    failed = False
    for p in files:
        r = tex.compile_tex(p)
        if r.ok:
            typer.echo(f"  ✓ {r.pdf.name}")
        else:
            failed = True
            where = f" (câu {r.question})" if r.question else ""
            typer.secho(f"  ✗ {p.name}: {r.error}{where}", fg="red")
    if failed:
        raise typer.Exit(1)


def gen_params(grade: str, topic: str, level: str, qtype: str, count: int, dang: Optional[str], notes: Optional[str]) -> dict:
    return {"grade": grade, "topic": topic, "level": level, "type": qtype, "count": count, "dang": dang, "notes": notes}


@app.command("prompt")
def prompt_cmd(
    grade: str = typer.Option(..., "--lop", help='Ví dụ "Lớp 12"'),
    topic: str = typer.Option(..., "--chu-de", help='Ví dụ "Nguyên hàm và tích phân"'),
    level: str = typer.Option(..., "--muc", help="NB | TH | VD | VDC"),
    qtype: str = typer.Option("mcq", "--loai", help="mcq | tf | short | essay"),
    count: int = typer.Option(10, "--so", help="Số câu"),
    dang: Optional[str] = typer.Option(None, "--dang", help="Dạng bài (tuỳ chọn)"),
    notes: Optional[str] = typer.Option(None, "--ghi-chu", help="Yêu cầu thêm"),
):
    """In prompt sinh câu hỏi để dán vào Claude. Kết quả dán lại bằng `nhd import --nhap`."""
    session = make_session()
    try:
        system, user = aigen.build_prompt(session, gen_params(grade, topic, level, qtype, count, dang, notes))
    except aigen.GenError as e:
        typer.echo(f"Lỗi: {e}")
        raise typer.Exit(1)
    typer.echo(aigen.combined_prompt(system, user))


@app.command("sinh")
def generate_cmd(
    grade: str = typer.Option(..., "--lop"),
    topic: str = typer.Option(..., "--chu-de"),
    level: str = typer.Option(..., "--muc"),
    qtype: str = typer.Option("mcq", "--loai"),
    count: int = typer.Option(10, "--so"),
    dang: Optional[str] = typer.Option(None, "--dang"),
    notes: Optional[str] = typer.Option(None, "--ghi-chu"),
):
    """Gọi Claude API sinh câu hỏi (cần ANTHROPIC_API_KEY), lưu vào ngân hàng ở trạng thái nháp."""
    session = make_session()
    try:
        batch = aigen.create_batch(session, gen_params(grade, topic, level, qtype, count, dang, notes), "api")
    except aigen.GenError as e:
        typer.echo(f"Lỗi: {e}")
        raise typer.Exit(1)
    typer.echo(f"Đang sinh {count} câu bằng {batch.model}…")
    aigen.run_batch(session, batch)
    if batch.status.value == "failed":
        typer.echo(f"Lỗi: {batch.error}")
        raise typer.Exit(1)
    for it in batch.items:
        mark = {"new": "+", "duplicate": "=", "error": "!"}[it["state"]]
        detail = it["code"] or it.get("duplicate_of") or "; ".join(it["errors"])
        typer.echo(f" {mark} {detail}: {it['stem'][:70]}")
        for w in it["warnings"]:
            typer.echo(f"     cảnh báo: {w}")
    added = sum(1 for it in batch.items if it["code"])
    typer.echo(f"Đã thêm {added} câu nháp, nguồn \"{batch.source}\". Đọc lại và duyệt trên web trước khi ra đề.")
    if batch.error:
        typer.echo(batch.error)


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    no_worker: bool = typer.Option(False, "--khong-worker", help="Không chạy luồng biên dịch PDF nền"),
):
    """Chạy giao diện web tại http://HOST:PORT (kèm worker biên dịch PDF)."""
    import uvicorn

    from .api import create_app

    typer.echo(f"Mở http://{host}:{port} trên trình duyệt")
    uvicorn.run(create_app(worker=not no_worker), host=host, port=port)


if __name__ == "__main__":
    app()
