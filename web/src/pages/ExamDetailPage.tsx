import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, levelLabel, type ExamDetail, type ExamFile } from "../api";
import QuestionView from "../components/QuestionView";
import { buildSummary } from "./ExamListPage";
import { useAuth } from "../auth";

const STATUS_LABEL = { pending: "Đang chờ", running: "Đang biên dịch", done: "Xong", failed: "Lỗi" };

function FileCell({ f }: { f?: ExamFile }) {
  if (!f) return <td />;
  if (f.status === "done" && f.url)
    return (
      <td>
        <a href={f.url} target="_blank" rel="noreferrer">
          Tải PDF
        </a>
      </td>
    );
  if (f.status === "failed")
    return (
      <td className="file-error">
        Lỗi{f.error_question && <> ở câu <Link to={`/cau/${encodeURIComponent(f.error_question)}`}>{f.error_question}</Link></>}
        <div className="muted small">{f.error}</div>
      </td>
    );
  return <td className="muted">{STATUS_LABEL[f.status]}…</td>;
}

export default function ExamDetailPage() {
  const { id } = useParams();
  const examId = Number(id);
  const navigate = useNavigate();
  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [error, setError] = useState("");
  const [variant, setVariant] = useState(0);
  const [showAnswers, setShowAnswers] = useState(false);
  const { me } = useAuth();

  const load = useCallback(() => {
    api
      .getExam(examId)
      .then(setExam)
      .catch((e) => setError(String(e.message)));
  }, [examId]);

  useEffect(load, [load]);

  // Còn file đang biên dịch thì hỏi lại sau 2 giây
  const busy = !!exam && exam.files.some((f) => f.status === "pending" || f.status === "running");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [busy, load]);

  if (error) return <div className="alert error">{error}</div>;
  if (!exam) return <div className="muted">Đang tải…</div>;

  const file = (name: string) => exam.files.find((f) => f.name === name);
  const v = exam.variants[variant];

  const remove = async () => {
    if (!window.confirm(`Xoá đề "${exam.title}" cùng các file PDF? Không hoàn tác được.`)) return;
    await api.deleteExam(exam.id);
    navigate("/de");
  };

  return (
    <div className="exam-detail">
      <div className="editor-head">
        <Link to="/de">‹ Kho đề</Link>
        <h2>{exam.title}</h2>
        {buildSummary(exam.builds)}
        <span className="spacer" />
        <button className="primary" onClick={() => api.startAttempt({ exam_id: exam.id, variant: v.code }).then((a) => navigate(`/luyen/${a.id}`))}>
          Làm thử mã {v.code}
        </button>
        <a className="button" href={`/api/exams/${exam.id}/files.zip`}>
          Tải tất cả (.zip)
        </a>
        <Link className="button" to={`/de/moi?tu_de=${exam.id}`} title="Mở trang ghép đề với cùng các phần và ma trận, có thể lưu thành khung đề">
          Ghép đề theo khung này
        </Link>
        <button onClick={() => api.rebuildExam(exam.id).then(setExam)}>Biên dịch lại</button>
        {me.role === "admin" && (
          <button className="danger" onClick={remove}>
            Xoá đề
          </button>
        )}
      </div>
      <label className="inline publish-toggle">
        <input
          type="checkbox"
          checked={exam.published}
          onChange={(e) => api.publishExam(exam.id, e.target.checked).then((r) => setExam({ ...exam, published: r.published }))}
        />{" "}
        <b>Mở cho học viên</b>
        <span className="muted">
          {" "}
          · học viên thấy đề này ở trang Luyện đề, làm bài và tải file đề; đáp án, lời giải cần xin admin
        </span>
      </label>
      <div className="muted">
        {exam.date && <>Ngày {exam.date} · </>}
        {exam.duration && <>{exam.duration} phút · </>}
        {exam.n_questions} câu · {exam.n_variants} mã đề · seed {String(exam.config.seed)}
      </div>

      <h3>File PDF</h3>
      <table className="table files">
        <thead>
          <tr>
            <th>Mã đề</th>
            <th>Đề cho học sinh</th>
            <th>Đáp án và lời giải</th>
          </tr>
        </thead>
        <tbody>
          {exam.variants.map((x) => (
            <tr key={x.code}>
              <td className="code">{x.code}</td>
              <FileCell f={file(`de-${x.code}`)} />
              <FileCell f={file(`loigiai-${x.code}`)} />
            </tr>
          ))}
          <tr>
            <td>Bảng đáp án</td>
            <FileCell f={file("dapan")} />
            <td />
          </tr>
        </tbody>
      </table>

      <h3>Bảng đáp án</h3>
      {exam.variants[0].data.sections.map((sec, si) =>
        sec.type === "essay" || sec.questions.length === 0 ? null : (
          <div key={si} className="key-block">
            <div className="muted">{sec.name}</div>
            <table className="table key">
              <thead>
                <tr>
                  <th>Mã đề</th>
                  {sec.questions.map((_, qi) => (
                    <th key={qi}>{qi + 1}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {exam.variants.map((x) => (
                  <tr key={x.code}>
                    <td className="code">{x.code}</td>
                    {x.answer_key.sections[si].map((k, qi) => (
                      <td key={qi}>{k}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ),
      )}

      <h3>Xem đề</h3>
      <div className="toolbar">
        {exam.variants.map((x, i) => (
          <button key={x.code} className={i === variant ? "primary" : ""} onClick={() => setVariant(i)}>
            Mã {x.code}
          </button>
        ))}
        <label className="inline">
          <input type="checkbox" checked={showAnswers} onChange={(e) => setShowAnswers(e.target.checked)} /> Hiện đáp án và lời giải
        </label>
      </div>
      <div className="paper">
        {v.data.sections.map((sec, si) => (
          <div key={si}>
            <h4>
              {sec.name}
              {sec.points ? <span className="muted"> (mỗi câu {sec.points} điểm)</span> : null}
            </h4>
            {sec.questions.map((q, qi) => (
              <div key={qi} className="paper-q">
                <div className="paper-q-head">
                  <b>Câu {qi + 1}.</b>
                  <Link to={`/cau/${encodeURIComponent(q.code)}`} className="muted small">
                    {q.code} · {levelLabel(q.level)}
                  </Link>
                </div>
                <QuestionView
                  type={q.type}
                  stem={q.stem}
                  choices={q.choices.map((c) => ({ ...c, pinned: false }))}
                  shortAnswer={q.short_answer}
                  solution={q.solution}
                  showAnswer={showAnswers}
                />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
