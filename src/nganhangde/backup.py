"""Sao lưu toàn bộ dữ liệu ra một file .zip và khôi phục lại.

File gồm `manifest.json`, mỗi bảng một file `data/<bảng>.jsonl` (mỗi dòng một bản ghi) và, nếu chọn, các PDF
trong thư mục file (`files/...`). Danh sách bảng và cột lấy thẳng từ mô hình dữ liệu nên bảng mới thêm sau này
tự có trong bản sao lưu. Khôi phục thay toàn bộ dữ liệu hiện có bằng dữ liệu trong file, trong một giao dịch:
lỗi giữa chừng thì dữ liệu cũ còn nguyên. Chạy được cả trên PostgreSQL lẫn SQLite, chuyển qua lại được.
"""

from __future__ import annotations

import enum
import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import IO

from sqlalchemy import Date, DateTime, Engine, Enum, func, select, text, update

from . import __version__, builds
from .models import Base, Build, BuildStatus, GenerationBatch

FORMAT = "nhd-backup"
FORMAT_VERSION = 1
PREFIX = "nhd-saoluu-"
SAFETY_PREFIX = "truoc-khoi-phuc-"

# Tên tiếng Việt của các bảng hiện trên trang sao lưu
TABLE_NAMES = {
    "questions": "Câu hỏi",
    "choices": "Lựa chọn",
    "taxonomy_nodes": "Thẻ",
    "question_tags": "Gắn thẻ",
    "exam_templates": "Khung đề",
    "exams": "Đề",
    "exam_items": "Câu trong đề",
    "exam_variants": "Mã đề",
    "builds": "File biên dịch",
    "attempts": "Lượt luyện",
    "attempt_items": "Câu trong lượt luyện",
    "generation_batches": "Lần sinh AI",
}


class BackupError(Exception):
    pass


def backups_dir() -> Path:
    return Path(os.environ.get("NHD_BACKUPS", "backups"))


def backup_name(now: datetime | None = None, prefix: str = PREFIX) -> str:
    return f"{prefix}{(now or datetime.now()):%Y%m%d-%H%M%S}.zip"


# ---------- Chuyển giá trị sang JSON và ngược lại ----------


def _dump_value(v):
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _load_value(column, v):
    if v is None:
        return None
    t = column.type
    if isinstance(t, Enum) and t.enum_class is not None:
        try:
            return t.enum_class(v)
        except ValueError:
            return t.enum_class[v]
    if isinstance(t, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(t, Date):
        return date.fromisoformat(v)
    return v


# ---------- Sao lưu ----------


def table_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t.name: conn.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables}


def _iter_files(root: Path):
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                yield p


def files_size(root: Path | None = None) -> tuple[int, int]:
    """(số file, tổng dung lượng) trong thư mục file."""
    files = list(_iter_files(root or builds.files_dir()))
    return len(files), sum(p.stat().st_size for p in files)


def write_backup(engine: Engine, out: IO[bytes] | Path, include_files: bool = True) -> dict:
    """Ghi bản sao lưu ra `out` (file hoặc luồng nhị phân). Trả về manifest."""
    root = builds.files_dir()
    manifest = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "app_version": __version__,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "database": engine.dialect.name,
        "files_dir": str(root),
        "include_files": include_files,
        "tables": {},
        "files": 0,
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        # Đọc mọi bảng trong cùng một giao dịch để bản sao lưu nhất quán
        with engine.connect() as conn:
            for table in Base.metadata.sorted_tables:
                order = list(table.primary_key.columns)
                buf = io.StringIO()
                n = 0
                for row in conn.execute(select(table).order_by(*order)).mappings():
                    buf.write(json.dumps({k: _dump_value(v) for k, v in row.items()}, ensure_ascii=False))
                    buf.write("\n")
                    n += 1
                z.writestr(f"data/{table.name}.jsonl", buf.getvalue())
                manifest["tables"][table.name] = n
        if include_files:
            for p in _iter_files(root):
                # PDF đã nén sẵn, không cần nén lại
                z.write(p, "files/" + p.relative_to(root).as_posix(), compress_type=zipfile.ZIP_STORED)
                manifest["files"] += 1
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def save_backup(engine: Engine, include_files: bool = True, prefix: str = PREFIX, keep: int | None = None) -> Path:
    """Lưu bản sao lưu vào thư mục sao lưu (biến NHD_BACKUPS, mặc định ./backups).
    `keep`: chỉ giữ lại ngần ấy bản gần nhất cùng tiền tố."""
    folder = backups_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / backup_name(prefix=prefix)
    tmp = target.with_suffix(".tmp")
    try:
        with open(tmp, "wb") as f:
            write_backup(engine, f, include_files)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    if keep is not None and keep > 0:
        for old in sorted(folder.glob(f"{prefix}*.zip"))[:-keep]:
            old.unlink()
    return target


def list_backups() -> list[dict]:
    folder = backups_dir()
    if not folder.is_dir():
        return []
    rows = []
    for p in sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = p.stat()
        rows.append(
            {
                "name": p.name,
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "safety": p.name.startswith(SAFETY_PREFIX),
            }
        )
    return rows


def stored_backup(name: str) -> Path:
    """Đường dẫn một bản trong thư mục sao lưu, chặn tên có thư mục."""
    if "/" in name or "\\" in name or not name.endswith(".zip") or name.startswith("."):
        raise BackupError("tên bản sao lưu không hợp lệ")
    p = backups_dir() / name
    if not p.is_file():
        raise BackupError(f"không có bản sao lưu {name}")
    return p


# ---------- Đọc và khôi phục ----------


@dataclass
class Archive:
    manifest: dict
    rows: dict[str, list[dict]]
    files: list[str]  # đường dẫn trong zip, dạng files/...
    warnings: list[str] = field(default_factory=list)


def read_archive(z: zipfile.ZipFile) -> Archive:
    names = set(z.namelist())
    if "manifest.json" not in names:
        raise BackupError("không phải file sao lưu của ngân hàng đề (thiếu manifest.json)")
    try:
        manifest = json.loads(z.read("manifest.json"))
    except ValueError:
        raise BackupError("manifest.json bị hỏng")
    if manifest.get("format") != FORMAT:
        raise BackupError("không phải file sao lưu của ngân hàng đề")
    if int(manifest.get("version", 0)) > FORMAT_VERSION:
        raise BackupError("file sao lưu do bản mới hơn tạo ra, hãy cập nhật ứng dụng trước khi khôi phục")

    known = {t.name: t for t in Base.metadata.sorted_tables}
    archive = Archive(manifest, {}, [])
    for name in sorted(names):
        if name.startswith("data/") and name.endswith(".jsonl"):
            table = name[len("data/") : -len(".jsonl")]
            if table not in known:
                archive.warnings.append(f"bỏ qua bảng {table}: ứng dụng hiện tại không có")
                continue
            cols = known[table].columns
            rows = []
            dropped: set[str] = set()
            for i, line in enumerate(z.read(name).decode("utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    dropped.update(k for k in raw if k not in cols)
                    rows.append({k: _load_value(cols[k], v) for k, v in raw.items() if k in cols})
                except (ValueError, KeyError) as e:
                    raise BackupError(f"{name} dòng {i} bị hỏng: {e}")
            if dropped:
                archive.warnings.append(f"bảng {table}: bỏ qua cột {', '.join(sorted(dropped))}")
            archive.rows[table] = rows
        elif name.startswith("files/") and not name.endswith("/"):
            parts = PurePosixPath(name).parts
            if ".." in parts or name.startswith("/"):
                raise BackupError(f"đường dẫn file không hợp lệ: {name}")
            archive.files.append(name)
    for table, n in manifest.get("tables", {}).items():
        if table in known and len(archive.rows.get(table, [])) != n:
            raise BackupError(f"file sao lưu thiếu dữ liệu bảng {table} (có {len(archive.rows.get(table, []))}/{n} dòng)")
    return archive


def open_archive(src: bytes | Path) -> tuple[zipfile.ZipFile, Archive]:
    try:
        z = zipfile.ZipFile(io.BytesIO(src) if isinstance(src, bytes) else src)
    except zipfile.BadZipFile:
        raise BackupError("file không phải .zip hoặc đã bị hỏng")
    return z, read_archive(z)


def summary(archive: Archive) -> dict:
    m = archive.manifest
    return {
        "created_at": m.get("created_at"),
        "app_version": m.get("app_version"),
        "database": m.get("database"),
        "tables": {t: len(r) for t, r in archive.rows.items()},
        "files": len(archive.files),
        "warnings": archive.warnings,
    }


def _reset_sequences(conn) -> None:
    """PostgreSQL: đưa bộ đếm id về sau id lớn nhất vừa chèn, để bản ghi mới không trùng id."""
    if conn.dialect.name != "postgresql":
        return
    for table in Base.metadata.sorted_tables:
        pk = list(table.primary_key.columns)
        if len(pk) != 1 or not pk[0].autoincrement or pk[0].type.python_type is not int:
            continue
        col = pk[0].name
        conn.execute(
            text(
                f'SELECT setval(pg_get_serial_sequence(:t, :c), COALESCE(MAX("{col}"), 1), MAX("{col}") IS NOT NULL) '
                f'FROM "{table.name}"'
            ),
            {"t": table.name, "c": col},
        )


def restore(engine: Engine, src: bytes | Path, safety_backup: bool = True) -> dict:
    """Thay toàn bộ dữ liệu bằng nội dung file sao lưu. Trước khi ghi đè, lưu một bản dữ liệu hiện tại
    (tiền tố `truoc-khoi-phuc-`) vào thư mục sao lưu. Trả về tóm tắt kèm tên bản an toàn."""
    z, archive = open_archive(src)
    with z:
        safety = None
        if safety_backup and any(table_counts(engine).values()):
            safety = save_backup(engine, include_files=True, prefix=SAFETY_PREFIX).name

        # Đường dẫn PDF lưu trong bảng builds là đường dẫn tuyệt đối lúc sao lưu: đổi sang thư mục file hiện tại
        root = builds.files_dir()
        old_root = archive.manifest.get("files_dir")
        if old_root:
            for row in archive.rows.get("builds", []):
                p = row.get("pdf_path")
                if p and p.startswith(old_root.rstrip("/") + "/"):
                    row["pdf_path"] = str(root / p[len(old_root.rstrip("/")) + 1 :])

        tables = Base.metadata.sorted_tables
        with engine.begin() as conn:
            for table in reversed(tables):
                conn.execute(table.delete())
            for table in tables:
                rows = archive.rows.get(table.name)
                if not rows:
                    continue
                # Gom theo bộ cột để mỗi lệnh chèn có cùng danh sách cột
                groups: dict[tuple, list[dict]] = {}
                for r in rows:
                    groups.setdefault(tuple(sorted(r)), []).append(r)
                for group in groups.values():
                    for i in range(0, len(group), 500):
                        conn.execute(table.insert(), group[i : i + 500])
            # Việc đang chạy dở lúc sao lưu thì xếp hàng lại
            conn.execute(update(Build).where(Build.status == BuildStatus.RUNNING).values(status=BuildStatus.PENDING))
            conn.execute(
                update(GenerationBatch)
                .where(GenerationBatch.status == BuildStatus.RUNNING)
                .values(status=BuildStatus.PENDING)
            )
            _reset_sequences(conn)

        if archive.files:
            for name in archive.files:
                target = root / name[len("files/") :]
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as f_in, open(target, "wb") as f_out:
                    while chunk := f_in.read(1 << 20):
                        f_out.write(chunk)

    return {**summary(archive), "safety_backup": safety}
