from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from helpers import login_admin
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
        login_admin(c)
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


def test_batch_list_has_creator_and_pending(app):
    c = app.state.client
    b = c.post("/api/gen/batches", json={"params": PARAMS, "mode": "manual", "output": OUTPUT}).json()
    assert b["username"] == "admin"
    listed = c.get("/api/gen/batches").json()
    assert listed[0]["id"] == b["id"] and listed[0]["n_pending"] == 2 and listed[0]["user_id"] == b["user_id"]
    # duyệt một câu thì số câu chờ duyệt giảm
    code = next(it["code"] for it in b["items"] if it["code"])
    assert c.post("/api/questions/bulk", json={"codes": [code], "status": "approved"}).status_code == 200
    assert c.get("/api/gen/batches").json()[0]["n_pending"] == 1


ROWS = [
    {"grade": "Lớp 12", "topic": "Vectơ trong không gian", "level": "NB", "type": "mcq", "count": 1},
    {"grade": "Lớp 12", "topic": "Vectơ trong không gian", "level": "TH", "type": "short", "count": 1},
    {"grade": "Lớp 11", "topic": "Khoảng cách trong không gian", "level": "VD", "type": "mcq", "count": 2},
]

MULTI_OUTPUT = r"""% @tags: Lớp 11 / Khoảng cách trong không gian / Khoảng cách từ điểm đến mặt phẳng ; @level: VD
\begin{ex}
  Cho hình lập phương cạnh $a=2$. Khoảng cách từ một đỉnh tới mặt phẳng chứa mặt đối diện bằng
  \choice{\True $2$}{$1$}{$\sqrt2$}{$4$}
  \loigiai{Bằng độ dài cạnh.}
\end{ex}

% @tags: Lớp 12 / Vectơ trong không gian / Tọa độ điểm ; @level: NB
\begin{ex}
  Trong không gian $Oxyz$, hình chiếu của $M(3;4;5)$ lên trục $Ox$ là
  \choice{\True $(3;0;0)$}{$(0;4;0)$}{$(0;0;5)$}{$(3;4;0)$}
  \loigiai{Giữ hoành độ.}
\end{ex}

% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: TH
\begin{ex}
  Cho $\vec a=(1;2;3)$, $\vec b=(2;1;1)$. Tính $\vec a\cdot\vec b$.
  \shortans{7}
  \loigiai{$2+2+3=7$.}
\end{ex}

% @tags: Lớp 10 / Hệ thức lượng ; @level: NB
\begin{ex}
  Câu lạc đề. \choice{\True $1$}{$2$}{$3$}{$4$}
\end{ex}
"""


def test_multi_rows_prompt_check_and_save(app):
    c = app.state.client
    p = c.post("/api/gen/prompt/multi", json={"rows": ROWS}).json()
    assert "## Ô 3" in p["user"] and "tổng cộng 4 câu" in p["user"] and "(1 + 1 + 2 theo thứ tự các ô)" in p["user"]
    assert "% @tags: Lớp 11 / Khoảng cách trong không gian / <Dạng bài> ; @level: VD" in p["user"]

    r = c.post("/api/gen/check/multi", json={"rows": ROWS, "output": MULTI_OUTPUT}).json()
    assert [len(x) for x in r["rows"]] == [1, 1, 1]
    assert r["rows"][2][0]["tags"] == [["Lớp 11", "Khoảng cách trong không gian", "Khoảng cách từ điểm đến mặt phẳng"]]
    assert len(r["unmatched"]) == 1 and "lạc đề" in r["unmatched"][0]["stem"]

    res = c.post("/api/gen/batches/multi", json={"rows": ROWS, "mode": "manual", "output": MULTI_OUTPUT})
    assert res.status_code == 201, res.text
    g = res.json()
    assert len(g["batches"]) == 3 and all(b["group_id"] == g["group_id"] for b in g["batches"])
    assert [b["n_added"] for b in g["batches"]] == [1, 1, 1]
    # cả đợt mở ở ngân hàng bằng bộ lọc nhiều nguồn
    sources = "|".join(b["source"] for b in g["batches"])
    assert c.get("/api/questions", params={"source": sources}).json()["total"] == 3

    too_many = [{**ROWS[0], "count": 30}, {**ROWS[1], "count": 30}, {**ROWS[2], "count": 1}]
    assert c.post("/api/gen/prompt/multi", json={"rows": too_many}).status_code == 422
    assert c.post("/api/gen/batches/multi", json={"rows": ROWS, "mode": "api"}).status_code == 422  # chưa có khoá


def test_multi_rows_api_mode_queues_one_batch_per_row(app, monkeypatch):
    c = app.state.client
    monkeypatch.setattr(aigen, "CALLER", lambda s, u, m: ("", {"input_tokens": 1, "output_tokens": 1}))
    g = c.post("/api/gen/batches/multi", json={"rows": ROWS, "mode": "api"}).json()
    assert [b["status"] for b in g["batches"]] == ["pending"] * 3
    assert len({b["group_id"] for b in g["batches"]}) == 1
    # sinh bằng API được tới 300 câu một đợt; dán tay mỗi phần tối đa 60 câu
    big = [{**ROWS[i % 3], "count": 30} for i in range(10)]
    assert c.post("/api/gen/batches/multi", json={"rows": big, "mode": "api"}).status_code == 201
    assert c.post("/api/gen/batches/multi", json={"rows": big + [ROWS[0]], "mode": "api"}).status_code == 422
    assert c.post("/api/gen/prompt/multi", json={"rows": big[:2]}).status_code == 200
    assert c.post("/api/gen/prompt/multi", json={"rows": big[:3]}).status_code == 422


def test_manual_parts_join_one_group(app):
    c = app.state.client
    first = c.post("/api/gen/batches/multi", json={"rows": ROWS[:2], "mode": "manual", "output": MULTI_OUTPUT}).json()
    second = c.post("/api/gen/batches/multi", json={"rows": ROWS[2:], "mode": "manual", "output": MULTI_OUTPUT,
                                                    "group_id": first["group_id"]}).json()
    assert second["group_id"] == first["group_id"]


VARIANTS = r"""% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: NB
% @kiemtra: 2*1 + 1*0 + (-1)*3 = -1
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=(2;1;-1)$ và $\vec v=(1;0;3)$. Tích vô hướng $\vec u\cdot\vec v$ bằng
  \choice{$1$}{\True $-1$}{$5$}{$-5$}
  \loigiai{$2-3=-1$.}
\end{ex}

% @kiemtra: 3*1 + 1*2 + 0*1 = 5
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=(3;1;0)$ và $\vec v=(1;2;1)$. Tích vô hướng $\vec u\cdot\vec v$ bằng
  \choice{$4$}{\True $6$}{$5$}{$7$}
  \loigiai{Ghi sai đáp án.}
\end{ex}
"""


def test_variants_grouped_and_answer_checked(app):
    c = app.state.client
    p = c.get("/api/questions/12V-001/variant-params", params={"count": 2}).json()
    assert p["variant_of"] == "12V-001" and p["grade"] == "Lớp 12" and p["topic"] == "Vectơ trong không gian"
    assert p["dang"] == "Tích vô hướng" and p["count"] == 2
    prompt = c.post("/api/gen/prompt", json=p).json()
    assert "biến thể của câu gốc" in prompt["user"] and "12V-001" in prompt["user"]
    assert "@kiemtra" in prompt["system"]

    b = c.post("/api/gen/batches", json={"params": p, "mode": "manual", "output": VARIANTS}).json()
    assert b["n_added"] == 2
    good, bad = b["items"]
    assert good["answer_errors"] == [] and good["answer_checked"]
    assert any("khác đáp số" in e for e in bad["answer_errors"])
    # câu gốc và hai biến thể cùng một nhóm; cảnh báo lưu lên câu để người duyệt thấy ở ngân hàng
    q = c.get(f"/api/questions/{bad['code']}").json()
    grp = q["variant_group"]
    assert grp.startswith("N-") and q["variant_origin"] == "12V-001" and q["n_variants"] == 3
    assert "khác đáp số" in q["check_note"]
    assert q["tags"][0]["names"] == ["Lớp 12", "Vectơ trong không gian", "Tích vô hướng"]
    listed = c.get("/api/questions", params={"group": grp}).json()
    assert listed["total"] == 3 and all(it["n_variants"] == 3 for it in listed["items"])
    # sửa câu thì cảnh báo được xoá
    src = q["ex_source"].replace("Ghi sai đáp án.", "$3+2+0=5$.").replace("{\\True $6$}", "{$6$}").replace("{$5$}", "{\\True $5$}")
    # duyệt cả nhóm bỏ qua câu còn cảnh báo
    assert c.post(f"/api/questions/group/{grp}/approve").json() == {"approved": 1, "skipped": [bad["code"]]}
    q2 = c.put(f"/api/questions/{bad['code']}", json={"source": src}).json()
    assert q2["check_note"] is None
    assert c.post(f"/api/questions/group/{grp}/approve").json() == {"approved": 1, "skipped": []}


def make_group(c) -> list[str]:
    """Nhóm biến thể đã duyệt: 12V-001 và hai biến thể."""
    p = c.get("/api/questions/12V-001/variant-params", params={"count": 2}).json()
    fixed = VARIANTS.replace("{\\True $6$}{$5$}", "{$6$}{\\True $5$}").replace("Ghi sai đáp án.", "$3+2=5$.")
    b = c.post("/api/gen/batches", json={"params": p, "mode": "manual", "output": fixed}).json()
    codes = [it["code"] for it in b["items"]]
    c.post("/api/questions/bulk", json={"codes": ["12V-001", *codes], "status": "approved"})
    return ["12V-001", *codes]


def test_varying_exam_gives_unseen_variants(app):
    c = app.state.client
    group = make_group(c)
    exam = {"title": "Đề đổi biến thể", "variants": 1, "sections": [{"type": "mcq", "ids": ["12V-001", "12V-002"]}]}
    e = c.post("/api/exams", json=exam).json()
    assert e["vary"] is True
    seen = []
    for _ in range(3):
        a = c.post("/api/attempts", json={"exam_id": e["id"]}).json()
        codes = [q["code"] for q in a["data"]["sections"][0]["questions"]]
        assert "12V-002" in codes  # câu không có nhóm thì giữ nguyên
        seen.append(next(x for x in codes if x in group))
    assert sorted(seen) == sorted(group)  # ba lượt gặp đủ ba biến thể, không lặp
    assert a["data"]["seen_before"] == 1  # lượt thứ ba: chỉ 12V-002 là câu đã gặp
    # tắt công tắc thì mọi lượt làm đúng câu trong đề
    assert c.put(f"/api/exams/{e['id']}/vary", json={"vary": False}).json()["vary"] is False
    a = c.post("/api/attempts", json={"exam_id": e["id"]}).json()
    assert "12V-001" in [q["code"] for q in a["data"]["sections"][0]["questions"]]


def test_exam_takes_one_question_per_group_and_reports_unused(app):
    c = app.state.client
    group = make_group(c)
    sec = {"type": "mcq", "pick": [{"tag": "lop-12/vecto-trong-khong-gian/tich-vo-huong", "level": "NB", "count": 2}]}
    avail = c.post("/api/exams/availability", json={"sections": [sec]}).json()["sections"][0]
    n = avail["rows"][0]
    assert avail["unused"][0] == n
    for seed in range(5):
        e = c.post("/api/exams", json={"title": "Đề", "seed": seed, "sections": [sec]}).json()
        codes = [q["code"] for q in e["variants"][0]["data"]["sections"][0]["questions"]]
        if n - len(group) + 1 >= 2:  # đủ câu ngoài nhóm thì không lấy hai câu cùng nhóm
            assert len(set(codes) & set(group)) <= 1
    assert c.post("/api/exams/availability", json={"sections": [sec]}).json()["sections"][0]["unused"][0] < n


def test_variant_group_records(app):
    c = app.state.client
    codes = make_group(c)
    q = c.get("/api/questions/12V-001").json()
    group = q["variant_group"]
    assert group.startswith("N-") and q["variant_origin"] == "12V-001" and q["n_variants"] == 3
    # mô tả dạng
    assert c.put(f"/api/variant-groups/{group}", json={"label": "Tích vô hướng từ toạ độ"}).json()["label"] == "Tích vô hướng từ toạ độ"
    listed = c.get("/api/questions", params={"group": group}).json()["items"]
    assert all(it["variant_label"] == "Tích vô hướng từ toạ độ" for it in listed)
    # tách câu gốc khỏi nhóm: câu cũ nhất còn lại thành câu gốc
    assert c.put("/api/questions/12V-001/variant-group", json={"group": None}).json()["variant_group"] is None
    g = c.get(f"/api/variant-groups/{group}").json()
    assert g["n"] == 2 and g["origin_code"] == codes[1]
    # gộp lại: dùng nhóm sẵn có
    merged = c.post("/api/variant-groups/merge", json={"codes": ["12V-001", codes[1]]}).json()
    assert merged["code"] == group and merged["n"] == 3
    # chuyển sang nhóm không tồn tại / khác loại câu thì báo lỗi
    assert c.put("/api/questions/12V-001/variant-group", json={"group": "N-999999"}).status_code == 422
    log = c.get("/api/questions/12V-001/log").json()
    assert any(e["action"] == "nhom" for e in log)


def test_old_variant_groups_are_migrated(app):
    from nganhangde import bank
    from nganhangde.models import Question

    c = app.state.client
    codes = make_group(c)
    with Session(app.state.engine) as s:
        for q in s.query(Question).filter(Question.code.in_(["12V-001", *codes])):
            q.variant_group = "12V-001"  # dạng cũ: mã câu gốc
        s.commit()
        assert bank.migrate_groups(s) == 1
        g = bank.get_group(s, s.query(Question).filter_by(code="12V-001").one().variant_group)
        assert g.origin_code == "12V-001" and bank.group_size(s, g.code) == 3
        assert bank.migrate_groups(s) == 0


BULK = r"""% @bienthe: 12V-001
% @dang-bien-the: Tích vô hướng từ toạ độ
% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: NB
% @kiemtra: 4*1 + 1*2 + 0*1 = 6
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=(4;1;0)$ và $\vec v=(1;2;1)$. Tích vô hướng $\vec u\cdot\vec v$ bằng
  \choice{$5$}{\True $6$}{$7$}{$8$}
  \loigiai{$4+2+0=6$.}
\end{ex}

% @bienthe: 12V-001
% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: NB
\begin{ex}
  Trong $Oxyz$, với $\vec u=(1;2;-1)$, $\vec v=(2;0;1)$, giá trị $\vec u\cdot\vec v$ là
  \choice{$0$}{\True $1$}{$2$}{$3$}
  \loigiai{Trùng số liệu câu gốc.}
\end{ex}

% @bienthe: 12V-004
% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: TH
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec a=(2;m;1)$ và $\vec b=(1;-1;3)$. Giá trị của $m$ để $\vec a\perp\vec b$ là
  \choice{\True $m=5$}{$m=-5$}{$m=1$}{$m=0$}
  \loigiai{$2-m+3=0 \Leftrightarrow m=5$.}
\end{ex}

% @bienthe: 12V-999
\begin{ex}
  Câu ghi sai mã câu gốc. \choice{\True $1$}{$2$}{$3$}{$4$}
  \loigiai{.}
\end{ex}
"""


def test_bulk_variants_plan_prompt_and_save(app):
    c = app.state.client
    make_group(c)
    plan = c.post("/api/gen/variants/plan", json={"tag": "lop-12/vecto-trong-khong-gian/tich-vo-huong"}).json()
    codes = [s["code"] for s in plan["sources"]]
    assert "12V-001" in codes and "12V-004" in codes
    # biến thể của 12V-001 cùng nhóm nên bị bỏ qua, chỉ câu gốc làm đại diện
    assert any("cùng nhóm" in s["reason"] for s in plan["skipped"])
    by_exam = c.post("/api/gen/variants/plan", json={"codes": ["12V-001", "12V-004"], "levels": ["TH"]}).json()
    assert [s["code"] for s in by_exam["sources"]] == ["12V-004"]

    body = {"codes": ["12V-001", "12V-004"], "per": 2}
    parts = c.post("/api/gen/variants/prompts", json=body).json()["parts"]
    assert len(parts) == 1 and parts[0]["count"] == 4
    assert "% @bienthe: 12V-004" in parts[0]["combined"] and "@dang-bien-the" in parts[0]["combined"]
    # nhiều câu gốc khác thẻ hoặc vượt gói thì chia nhiều phần
    many = c.post("/api/gen/variants/prompts", json={"codes": ["12V-001", "12V-002", "12V-004"], "per": 10}).json()
    assert [p["codes"] for p in many["parts"]] == [["12V-001", "12V-004"], ["12V-002"]]

    items = c.post("/api/gen/variants/check", json={**body, "output": BULK}).json()
    assert [it["state"] for it in items] == ["new", "duplicate", "new", "error"]
    assert items[0]["variant_of"] == "12V-001" and items[2]["variant_of"] == "12V-004"
    assert any("@bienthe" in e for e in items[3]["errors"])

    g = c.post("/api/gen/variants/batches", json={**body, "mode": "manual", "output": BULK}).json()
    assert len(g["batches"]) == 1 and g["batches"][0]["n_added"] == 2
    q1 = c.get("/api/questions/12V-001").json()
    q4 = c.get("/api/questions/12V-004").json()
    assert q1["n_variants"] == 4 and q1["variant_label"] == "Tích vô hướng từ toạ độ"
    assert q4["n_variants"] == 2 and q4["variant_group"] != q1["variant_group"]
    # câu nháp không làm câu gốc được
    assert c.post("/api/gen/variants/prompts", json={"codes": [q4["variants"][1]["code"]], "per": 2}).status_code == 422


def test_bulk_variants_api_mode_one_batch_per_pack(app, monkeypatch):
    c = app.state.client
    monkeypatch.setattr(aigen, "CALLER", lambda s, u, m: ("", {"input_tokens": 1, "output_tokens": 1}))
    g = c.post("/api/gen/variants/batches", json={"codes": ["12V-001", "12V-002", "12V-004"], "per": 10}).json()
    assert len(g["batches"]) == 2 and len({b["group_id"] for b in g["batches"]}) == 1
    assert g["batches"][0]["params"]["variants_of"] == ["12V-001", "12V-004"]


TEMPLATE = r"""% @bienthe: 12V-001
% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: NB
% @thamso: a = 1..4; b = -3..3; c = -3..3
% @dieukien: c != 0
% @tinh: d = 2*a + c
\begin{ex}
  Trong không gian $Oxyz$, cho $\vec u=({{a}};{{b}};{{c}})$ và $\vec v=(2;0;1)$. Tích vô hướng $\vec u\cdot\vec v$ bằng
  \choice{${{d - 1}}$}{\True ${{d}}$}{${{d + 1}}$}{${{d + 2}}$}
  \loigiai{$\vec u\cdot\vec v = {{a}}\cdot 2 + {{b:()}}\cdot 0 + {{c:()}}\cdot 1 = {{d}}$.}
\end{ex}

% @bienthe: 12V-004
% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: TH
\begin{ex}
  Câu chưa tham số hoá. \choice{\True $1$}{$2$}{$3$}{$4$}
\end{ex}
"""


def test_convert_to_param_questions(app):
    c = app.state.client
    body = {"codes": ["12V-001", "12V-004"], "per": 5, "param": True}
    parts = c.post("/api/gen/variants/prompts", json=body).json()["parts"]
    assert len(parts) == 1 and parts[0]["count"] == 2  # mỗi câu gốc đúng một mẫu
    assert "# Câu tham số" in parts[0]["combined"] and "% @bienthe: 12V-004" in parts[0]["combined"]
    items = c.post("/api/gen/variants/check", json={**body, "output": TEMPLATE}).json()
    assert [it["state"] for it in items] == ["new", "error"]
    assert items[0]["param"] and items[0]["answer_checked"] and not items[0]["answer_errors"]
    assert any("@thamso" in e for e in items[1]["errors"])
    g = c.post("/api/gen/variants/batches", json={**body, "mode": "manual", "output": TEMPLATE}).json()
    assert g["batches"][0]["n_added"] == 1
    new = c.get(f"/api/gen/batches/{g['batches'][0]['id']}").json()["items"][0]["code"]
    q = c.get(f"/api/questions/{new}").json()
    assert q["params"] and q["status"] == "draft"
    assert q["variant_group"] == c.get("/api/questions/12V-001").json()["variant_group"]
    # câu tự luận / đúng sai, câu đã là câu tham số thì không chuyển được
    assert c.post("/api/gen/variants/prompts", json={"codes": [new], "per": 1, "param": True}).status_code == 422


NEW_TEMPLATE = TEMPLATE.split("\n\n% @bienthe: 12V-004")[0].replace("% @bienthe: 12V-001\n", "")


def test_generate_new_param_questions(app):
    c = app.state.client
    p = {**PARAMS, "level": "NB", "count": 1, "param": True}
    prompt = c.post("/api/gen/prompt", json=p).json()
    assert "# Câu tham số" in prompt["combined"] and "mẫu câu tham số mới" in prompt["combined"]
    b = c.post("/api/gen/batches", json={"params": p, "mode": "manual", "output": NEW_TEMPLATE}).json()
    assert b["n_added"] == 1
    plain = c.post("/api/gen/check", json={"params": p, "output": OUTPUT.split("```\n")[0] + "```"}).json()
    assert any("@thamso" in e for e in plain[0]["errors"])
    tf = {**p, "type": "tf"}
    assert c.post("/api/gen/prompt", json=tf).status_code == 422
    # prompt gộp nhiều ô: quy tắc câu tham số ghi một lần
    multi = c.post("/api/gen/prompt/multi", json={"rows": [p, {**p, "level": "TH"}]}).json()
    assert multi["combined"].count("# Câu tham số") == 1


def test_search_by_many_codes(app):
    c = app.state.client
    r = c.get("/api/questions", params={"q": "12v-004, 12V-001; KHONG-CO"}).json()
    assert sorted(x["code"] for x in r["items"]) == ["12V-001", "12V-004"]
    plan = c.post("/api/gen/variants/plan", json={"q": "12V-004, 12V-001, KHONG-CO"}).json()
    assert [s["code"] for s in plan["sources"]] == ["12V-004", "12V-001"]  # đúng thứ tự đã gõ
    assert plan["sources"][0]["choices"]  # có cả phương án để xem
    assert {"code": "KHONG-CO", "reason": "không có trong ngân hàng"} in plan["skipped"]
    assert c.post("/api/gen/variants/plan", json={"q": "Tích vô hướng"}).json()["sources"]


ALG = r"""% @tags: Đại số / Chương 3. Không gian vectơ / Độc lập tuyến tính, cơ sở và số chiều / Hạng của hệ vectơ ; @level: NB
\begin{ex}
  Hạng của hệ vectơ $\{(1;2;3),\ (2;4;6)\}$ bằng
  \choice{$2$}{\True $1$}{$3$}{$0$}
  \loigiai{Hai vectơ tỉ lệ nên hạng bằng $1$.}
\end{ex}

% @tags: Đại số / Chương 3. Không gian vectơ / Độc lập tuyến tính, cơ sở và số chiều / Hạng của hệ vectơ ; @level: VDC
\begin{ex}
  Hạng của hệ $\{u+v,\ v+w,\ u-w\}$ bằng
  \choice{$3$}{\True $2$}{$1$}{$0$}
  \loigiai{$u-w=(u+v)-(v+w)$ nên hạng bằng $2$.}
\end{ex}
"""


def test_topic_names_with_commas(app):
    """Tên chủ đề có dấu phẩy không bị tách thành hai thẻ; prompt gộp nhiều ô chia câu đúng ô."""
    from nganhangde.parser import parse_text, split_tags

    pq = parse_text(ALG)[0]
    assert pq.tags == [["Đại số", "Chương 3. Không gian vectơ", "Độc lập tuyến tính, cơ sở và số chiều",
                        "Hạng của hệ vectơ"]]
    assert split_tags("Lớp 12 / A, Lớp 11 / B") == [["Lớp 12", "A"], ["Lớp 11", "B"]]
    c = app.state.client
    row = {"grade": "Đại số", "topic": "Độc lập tuyến tính, cơ sở và số chiều", "type": "mcq", "count": 1}
    r = c.post("/api/gen/check/multi", json={"rows": [{**row, "level": "NB"}, {**row, "level": "VDC"}],
                                             "output": ALG}).json()
    assert r["unmatched"] == [] and [len(x) for x in r["rows"]] == [1, 1]


def test_repair_split_tags(app):
    from nganhangde import bank
    from nganhangde.parser import parse_text

    with Session(app.state.engine) as s:
        q = bank.create_question(s, parse_text(ALG)[0])
        q.tags = [bank.get_or_create_path(s, ["Đại số", "Chương 3. Không gian vectơ", "Độc lập tuyến tính"]),
                  bank.get_or_create_path(s, ["cơ sở và số chiều", "Hạng của hệ vectơ"])]
        s.commit()
        code = q.code
    c = app.state.client
    rows = c.get("/api/tags/split").json()
    assert rows == [{"before": ["Đại số / Chương 3. Không gian vectơ / Độc lập tuyến tính",
                                "cơ sở và số chiều / Hạng của hệ vectơ"],
                     "after": ["Đại số / Chương 3. Không gian vectơ / Độc lập tuyến tính, cơ sở và số chiều / "
                               "Hạng của hệ vectơ"], "codes": [code]}]
    with Session(app.state.engine) as s:
        assert len(bank.repair_split_tags(s)) == 1
        q = bank.get_question(s, rows[0]["codes"][0])
        assert [bank.tag_names(t) for t in q.tags] == [["Đại số", "Chương 3. Không gian vectơ",
                                                         "Độc lập tuyến tính, cơ sở và số chiều", "Hạng của hệ vectơ"]]
        assert bank.get_question(s, "12V-001") is not None  # câu khác không bị đụng
        assert bank.repair_split_tags(s) == []
    assert c.get("/api/tags/split").json() == []
    assert not any(t["names"][0] == "cơ sở và số chiều" for t in c.get("/api/tags").json())


def test_html_entities_from_web_copy():
    from nganhangde.parser import parse_text

    q = parse_text(ALG.replace(r"\{(1;2;3)", r"\{(1;2;3)&amp;").replace("tỉ lệ", "p&#39; tỉ lệ"))[0]
    assert "&amp;" not in q.stem and "(1;2;3)&" in q.stem and "p' tỉ lệ" in q.solution


def test_editing_keeps_comma_topic_as_one_tag(app):
    """Lưu lại câu ở trang soạn (mã nguồn có dòng @tags sinh lại) không tách thẻ có dấu phẩy."""
    c = app.state.client
    q = c.post("/api/questions", json={"source": ALG.split("\n\n% @tags")[0], "status": "draft"}).json()
    src = c.get(f"/api/questions/{q['code']}").json()["ex_source"]
    saved = c.put(f"/api/questions/{q['code']}", json={"source": src, "status": "approved"}).json()
    assert [t["names"] for t in saved["tags"]] == [["Đại số", "Chương 3. Không gian vectơ",
                                                     "Độc lập tuyến tính, cơ sở và số chiều", "Hạng của hệ vectơ"]]
