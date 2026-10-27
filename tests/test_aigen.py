from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from nganhangde import aigen
from nganhangde.api import create_app

EXAMPLES = Path(__file__).parent.parent / "examples"

PARAMS = {"grade": "Lớp 12", "topic": "Vectơ trong không gian", "level": "TH", "type": "mcq", "count": 3}

# Kết quả giả lập: 2 câu tốt (một câu bọc trong ```), 1 câu trùng ngân hàng, 1 câu sai số \True, 1 câu sai loại
OUTPUT = r"""```latex
% @tags: Lớp 12 / Vectơ trong không gian / Tích có hướng ; @level: TH ; @source: AI ; @id: X1
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec a=(1;0;0)$, $\vec b=(0;1;0)$. Tích có hướng $[\vec a,\vec b]$ bằng
  \choice{$(0;0;-1)$}{\True $(0;0;1)$}{$(1;1;0)$}{$(0;1;1)$}
  \loigiai{$[\vec a,\vec b]=(0\cdot0-0\cdot1;\,0\cdot0-1\cdot0;\,1\cdot1-0\cdot0)=(0;0;1)$.}
\end{ex}
```

% @tags: Lớp 11 / Sai chủ đề ; @level: NB
\begin{ex}
  Trong không gian $Oxyz$, cho $A(1;2;3)$. Khoảng cách từ $A$ đến mặt phẳng $(Oxy)$ bằng
  \choice{$1$}{$2$}{\True $3$}{$\sqrt{14}$}
  \loigiai{Khoảng cách bằng $|z_A|=3$.}
\end{ex}

% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: NB
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=(1;2;-1)$ và $\vec v=(2;0;1)$. Tích vô hướng $\vec u\cdot\vec v$ bằng
  \choice
    {$0$}
    {\True $1$}
    {$2$}
    {$3$}
  \loigiai{$\vec u\cdot\vec v = 1\cdot 2 + 2\cdot 0 + (-1)\cdot 1 = 1$.}
\end{ex}

\begin{ex}
  Câu lỗi hai đáp án đúng. \choice{\True $1$}{\True $2$}{$3$}{$4$}
\end{ex}

\begin{ex}
  Câu trả lời ngắn lẫn vào. \shortans{5}
\end{ex}
"""


@pytest.fixture
def app(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("NHD_FILES", str(tmp_path / "files"))
    app = create_app(db_url)
    with TestClient(app) as c:
        source = (EXAMPLES / "vecto-khong-gian.tex").read_text(encoding="utf-8")
        assert c.post("/api/import/commit", json={"source": source}).status_code == 200
        app.state.client = c
        yield app
    app.state.engine.dispose()


def test_curriculum_and_coverage(app):
    c = app.state.client
    cur = c.get("/api/gen/curriculum").json()
    assert [g["ten"] for g in cur["grades"]] == ["Lớp 10", "Lớp 11", "Lớp 12", "Giải tích 1", "Giải tích 2",
                                                    "Giải tích 3", "Đại số", "Xác suất thống kê"]
    assert cur["model"] == "claude-opus-5-5"
    lop12 = next(g for g in cur["grades"] if g["slug"] == "lop-12")
    assert any(t["path"] == "lop-12/nguyen-ham-va-tich-phan" for t in lop12["chu_de"])

    cov = c.get("/api/gen/coverage", params={"grade": "Lớp 12"}).json()
    vec = next(t for t in cov["topics"] if t["path"] == "lop-12/vecto-trong-khong-gian")
    assert vec["in_curriculum"]
    assert {lv: cell["approved"] for lv, cell in vec["counts"].items()} == {"NB": 3, "TH": 7, "VD": 4, "VDC": 0}  # câu 2H3N1-1 chỉ có thẻ Lớp 12
    nguyen_ham = next(t for t in cov["topics"] if t["path"] == "lop-12/nguyen-ham-va-tich-phan")
    assert nguyen_ham["counts"]["NB"] == {"approved": 0, "draft": 0}


UNI_OUTPUT = r"""% @tags: Giải tích 1 / Chương 1. Hàm số một biến số / Dãy số và giới hạn dãy số / Tiêu chuẩn tồn tại giới hạn ; @level: TH
\begin{ex}
  Dãy $u_n=\dfrac{n}{n+1}$ có giới hạn bằng
  \choice{$0$}{\True $1$}{$2$}{$+\infty$}
  \loigiai{$u_n=1-\dfrac1{n+1}\to1$.}
\end{ex}
"""

UNI = {"grade": "Giải tích 1", "topic": "Dãy số và giới hạn dãy số", "level": "TH", "type": "mcq", "count": 1}


def test_university_curriculum_has_chapters(app):
    c = app.state.client
    gt1 = next(g for g in c.get("/api/gen/curriculum").json()["grades"] if g["slug"] == "giai-tich-1")
    assert gt1["bac"] == "Đại học" and len(gt1["chuong"]) == 3 and len(gt1["chu_de"]) == 14
    day = next(t for t in gt1["chu_de"] if t["ten"] == "Dãy số và giới hạn dãy số")
    assert day["names"] == ["Giải tích 1", "Chương 1. Hàm số một biến số", "Dãy số và giới hạn dãy số"]
    assert day["path"] == "giai-tich-1/chuong-1-ham-so-mot-bien-so/day-so-va-gioi-han-day-so"

    user = c.post("/api/gen/prompt", json=UNI).json()["user"]
    assert "- Chương: Chương 1. Hàm số một biến số" in user
    assert "% @tags: Giải tích 1 / Chương 1. Hàm số một biến số / Dãy số và giới hạn dãy số / <Dạng bài>" in user
    assert "nguyên lý kẹp" in user  # kiến thức trọng tâm
    assert "Định hướng câu hỏi trắc nghiệm" in user and "Maclaurin" in user
    essay = c.post("/api/gen/prompt", json={**UNI, "type": "essay"}).json()["user"]
    assert "Định hướng câu hỏi tự luận" in essay and "Rolle" in essay

    items = c.post("/api/gen/check", json={"params": UNI, "output": UNI_OUTPUT}).json()
    assert items[0]["state"] == "new"
    assert items[0]["tags"] == [["Giải tích 1", "Chương 1. Hàm số một biến số", "Dãy số và giới hạn dãy số",
                                 "Tiêu chuẩn tồn tại giới hạn"]]
    b = c.post("/api/gen/batches", json={"params": UNI, "mode": "manual", "output": UNI_OUTPUT}).json()
    code = b["items"][0]["code"]

    # Câu chỉ gắn tới tầng chương có dòng riêng trong bảng độ phủ
    c.post("/api/questions/bulk", json={"codes": ["12V-001"], "set_tag": "Giải tích 1 / Chương 1. Hàm số một biến số"})
    cov = c.get("/api/gen/coverage", params={"grade": "Giải tích 1"}).json()["topics"]
    assert [t["name"] for t in cov[:2]] == ["Tập số, trị tuyệt đối và các thuộc tính của hàm số",
                                            "Dãy số và giới hạn dãy số"]
    assert cov[1]["chuong"] == "Chương 1. Hàm số một biến số" and cov[1]["counts"]["TH"]["draft"] == 1
    extra = [t for t in cov if not t["in_curriculum"]]
    assert [(t["name"], t["chuong"], t["label"]) for t in extra] == [
        ("Chương 1. Hàm số một biến số", "Chương 1. Hàm số một biến số", "Câu chưa gắn chủ đề")]

    # Cây thẻ theo thứ tự khung chương trình
    tags = [t["path"] for t in c.get("/api/tags").json()]
    assert tags.index("giai-tich-1/chuong-1-ham-so-mot-bien-so/day-so-va-gioi-han-day-so") < len(tags)
    assert c.get(f"/api/questions/{code}").json()["status"] == "draft"


def test_prompt_contents(app):
    c = app.state.client
    r = c.post("/api/gen/prompt", json={**PARAMS, "notes": "Dùng số nguyên nhỏ"}).json()
    assert "\\choice" in r["system"] and "Vận dụng cao" in r["system"]
    user = r["user"]
    assert "Hãy soạn 3 câu" in user and "Thông hiểu (TH)" in user and "Dùng số nguyên nhỏ" in user
    assert "% @tags: Lớp 12 / Vectơ trong không gian / <Dạng bài> ; @level: TH" in user
    assert "Tích có hướng" in user  # các dạng bài trong khung chương trình
    assert "Câu mẫu đã duyệt" in user and "câu mới phải khác hẳn" in user
    assert r["combined"].startswith(r["system"])
    # Prompt hệ thống không đổi giữa các yêu cầu để dùng được cache
    other = c.post("/api/gen/prompt", json={**PARAMS, "grade": "Lớp 10", "topic": "Vectơ"}).json()
    assert other["system"] == r["system"] and "Câu mẫu" not in other["user"]

    assert c.post("/api/gen/prompt", json={**PARAMS, "count": 0}).status_code == 422
    assert c.post("/api/gen/prompt", json={**PARAMS, "topic": " "}).status_code == 422


def test_manual_batch_checks_and_imports(app):
    c = app.state.client
    items = c.post("/api/gen/check", json={"params": PARAMS, "output": OUTPUT}).json()
    assert [it["state"] for it in items] == ["new", "new", "duplicate", "error", "error"]
    assert items[0]["tags"] == [["Lớp 12", "Vectơ trong không gian", "Tích có hướng"]]
    assert items[1]["tags"] == [["Lớp 12", "Vectơ trong không gian"]]  # thẻ sai chủ đề bị thay
    assert items[2]["duplicate_of"] == "12V-001"
    assert "loại câu là short" in items[4]["errors"][0]

    r = c.post("/api/gen/batches", json={"params": PARAMS, "mode": "manual", "output": OUTPUT})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "done" and b["n_added"] == 2 and b["n_duplicate"] == 1 and b["n_error"] == 2
    codes = [it["code"] for it in b["items"] if it["code"]]
    q = c.get(f"/api/questions/{codes[0]}").json()
    assert q["status"] == "draft" and q["level"] == "TH" and q["source"] == f"AI #{b['id']}"
    listed = c.get("/api/questions", params={"source": b["source"]}).json()
    assert listed["total"] == 2

    assert c.post("/api/gen/batches", json={"params": PARAMS, "mode": "manual", "output": " "}).status_code == 422
    assert c.post("/api/gen/batches", json={"params": PARAMS, "mode": "api"}).status_code == 422  # chưa có khoá
    assert len(c.get("/api/gen/batches").json()) == 1


def test_api_batch_runs_in_worker(app, monkeypatch):
    calls = []

    def fake(system, user, model):
        calls.append((system, user, model))
        return OUTPUT, {"input_tokens": 100, "output_tokens": 50, "stop_reason": "end_turn"}

    monkeypatch.setattr(aigen, "CALLER", fake)
    c = app.state.client
    assert c.get("/api/gen/curriculum").json()["api"] is True
    b = c.post("/api/gen/batches", json={"params": PARAMS, "mode": "api"}).json()
    assert b["status"] == "pending" and b["model"] == "claude-opus-5-5"
    with Session(app.state.engine) as s:
        assert aigen.run_pending(s) == 1
    done = c.get(f"/api/gen/batches/{b['id']}").json()
    assert done["status"] == "done" and done["n_added"] == 2 and done["usage"]["output_tokens"] == 50
    assert calls[0][2] == "claude-opus-5-5" and "Hãy soạn 3 câu" in calls[0][1]

    def broken(system, user, model):
        raise aigen.GenError("Claude API đang giới hạn tần suất, thử lại sau ít phút")

    monkeypatch.setattr(aigen, "CALLER", broken)
    b2 = c.post("/api/gen/batches", json={"params": PARAMS, "mode": "api"}).json()
    with Session(app.state.engine) as s:
        aigen.run_pending(s)
    failed = c.get(f"/api/gen/batches/{b2['id']}").json()
    assert failed["status"] == "failed" and "giới hạn" in failed["error"]
    assert c.post(f"/api/gen/batches/{b2['id']}/retry").json()["status"] == "pending"
    assert c.post(f"/api/gen/batches/{b['id']}/retry").status_code == 409


def test_short_answer_rule():
    assert aigen.short_answer_ok("2,5") and aigen.short_answer_ok("-12") and aigen.short_answer_ok("0,75")
    assert not aigen.short_answer_ok("12,25") and not aigen.short_answer_ok("x=2")
