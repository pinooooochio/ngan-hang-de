import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, levelLabel, type Answer, type AttemptDetail, type AttemptQuestion, type AttemptResult } from "../api";
import Tex from "../components/Tex";

const fmtScore = (x: number | null) => (x === null ? "" : String(Math.round(x * 100) / 100).replace(".", ","));

function fmtClock(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

const answered = (a: Answer | undefined) =>
  a !== undefined && a !== null && (Array.isArray(a) ? a.some((x) => x !== null) : a !== "");

export default function AttemptPage() {
  const { id } = useParams();
  const attemptId = Number(id);
  const [attempt, setAttempt] = useState<AttemptDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getAttempt(attemptId)
      .then(setAttempt)
      .catch((e) => setError(String(e.message)));
  }, [attemptId]);

  if (error) return <div className="alert error">{error}</div>;
  if (!attempt) return <div className="muted">Đang tải…</div>;
  return attempt.submitted_at ? <Review attempt={attempt} /> : <Doing attempt={attempt} onSubmitted={setAttempt} />;
}

/** Làm bài: đồng hồ đếm ngược, tự lưu câu trả lời, tự nộp khi hết giờ. */
function Doing({ attempt, onSubmitted }: { attempt: AttemptDetail; onSubmitted: (a: AttemptDetail) => void }) {
  const [answers, setAnswers] = useState<Record<string, Answer>>(attempt.answers ?? {});
  const [saved, setSaved] = useState<"saved" | "saving" | "error">("saved");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const dirty = useRef(false);
  const answersRef = useRef(answers);
  answersRef.current = answers;

  // Lệch giờ giữa máy chủ và trình duyệt, để đồng hồ đếm đúng hạn nộp
  const skew = useRef(new Date(attempt.server_time).getTime() - Date.now());
  const deadline = attempt.deadline ? new Date(attempt.deadline).getTime() : null;
  const left = deadline === null ? null : deadline - (now + skew.current);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);

  // Tự lưu sau 800 ms kể từ lần sửa cuối
  useEffect(() => {
    if (!dirty.current) return;
    setSaved("saving");
    const t = setTimeout(() => {
      api
        .saveAnswers(attempt.id, answers)
        .then(() => setSaved("saved"))
        .catch(() => setSaved("error"));
    }, 800);
    return () => clearTimeout(t);
  }, [answers, attempt.id]);

  const submit = useCallback(async () => {
    setSubmitting(true);
    setError("");
    try {
      onSubmitted(await api.submitAttempt(attempt.id, answersRef.current));
      window.scrollTo(0, 0);
    } catch (e) {
      setError(String((e as Error).message));
      setSubmitting(false);
    }
  }, [attempt.id, onSubmitted]);

  const timeUp = left !== null && left <= 0;
  useEffect(() => {
    if (timeUp && !submitting) submit();
  }, [timeUp, submitting, submit]);

  const setAnswer = (key: string, value: Answer) => {
    dirty.current = true;
    setAnswers((a) => ({ ...a, [key]: value }));
  };

  const keys = attempt.data.sections.flatMap((s, si) => s.questions.map((_, qi) => `${si}.${qi}`));
  const nDone = keys.filter((k) => answered(answers[k])).length;

  const confirmSubmit = () => {
    const missing = keys.length - nDone;
    const msg = missing ? `Còn ${missing} câu chưa trả lời. Vẫn nộp bài?` : "Nộp bài và xem kết quả?";
    if (window.confirm(msg)) submit();
  };

  let number = 0;
  return (
    <div className="attempt">
      <div className="attempt-bar">
        <div>
          <b>{attempt.title}</b>
          {attempt.variant_code && <span className="muted"> · Mã đề {attempt.variant_code}</span>}
        </div>
        <span className="spacer" />
        <span className="muted small">
          {saved === "saving" ? "Đang lưu…" : saved === "error" ? "Chưa lưu được, sẽ thử lại khi sửa tiếp" : "Đã lưu"}
        </span>
        <span>
          {nDone}/{keys.length} câu
        </span>
        {left !== null && <span className={`clock ${left < 5 * 60 * 1000 ? "low" : ""}`}>{fmtClock(left)}</span>}
        <button className="primary" disabled={submitting} onClick={confirmSubmit}>
          {submitting ? "Đang nộp…" : "Nộp bài"}
        </button>
      </div>
      {error && <div className="alert error">{error}</div>}

      <div className="attempt-grid">
        <div className="paper">
          {attempt.data.sections.map((sec, si) => (
            <div key={si}>
              <h4>{sec.name}</h4>
              {sec.questions.map((q, qi) => {
                const key = `${si}.${qi}`;
                number += 1;
                return (
                  <div key={key} id={`q-${key}`} className="paper-q">
                    <div className="paper-q-head">
                      <b>Câu {number}.</b>
                    </div>
                    <AnswerQuestion q={q} value={answers[key]} onChange={(v) => setAnswer(key, v)} />
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <Navigator attempt={attempt} state={(k) => (answered(answers[k]) ? "done" : "")} />
      </div>
    </div>
  );
}

function Navigator({ attempt, state }: { attempt: AttemptDetail; state: (key: string) => string }) {
  let n = 0;
  return (
    <aside className="navigator">
      {attempt.data.sections.map((sec, si) => (
        <div key={si}>
          <div className="muted small">{sec.name}</div>
          <div className="nav-grid">
            {sec.questions.map((_, qi) => {
              const key = `${si}.${qi}`;
              n += 1;
              return (
                <a key={key} href={`#q-${key}`} className={`nav-cell ${state(key)}`}>
                  {n}
                </a>
              );
            })}
          </div>
        </div>
      ))}
    </aside>
  );
}

/** Ô trả lời cho một câu, tuỳ loại câu. */
function AnswerQuestion({ q, value, onChange }: { q: AttemptQuestion; value: Answer | undefined; onChange: (v: Answer) => void }) {
  return (
    <div className="question">
      <Tex source={q.stem} />
      {q.type === "mcq" && (
        <div className="answer-choices">
          {q.choices.map((c, i) => (
            <button key={i} className={`answer-choice ${value === i ? "picked" : ""}`} onClick={() => onChange(value === i ? null : i)}>
              <span className="label">{"ABCD"[i]}.</span>
              <Tex source={c.content} inline />
            </button>
          ))}
        </div>
      )}
      {q.type === "tf" && (
        <div className="statements">
          {q.choices.map((c, i) => {
            const cur = Array.isArray(value) ? value : [null, null, null, null];
            const set = (v: boolean) => onChange(cur.map((x, k) => (k === i ? (x === v ? null : v) : x)));
            return (
              <div key={i} className="statement">
                <span className="label">{"abcd"[i]})</span>
                <span className="statement-text">
                  <Tex source={c.content} inline />
                </span>
                <span className="tf-pick">
                  <button className={cur[i] === true ? "picked" : ""} onClick={() => set(true)}>
                    Đúng
                  </button>
                  <button className={cur[i] === false ? "picked" : ""} onClick={() => set(false)}>
                    Sai
                  </button>
                </span>
              </div>
            );
          })}
        </div>
      )}
      {q.type === "short" && (
        <label className="inline short-input">
          Đáp số
          <input value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} placeholder="Ví dụ: 1,5" />
        </label>
      )}
      {q.type === "essay" && (
        <textarea
          className="essay-input"
          rows={4}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Ghi bài làm hoặc ý chính (không chấm tự động, sau khi nộp sẽ so với lời giải)"
        />
      )}
    </div>
  );
}

/** Xem kết quả sau khi nộp: điểm, đáp án đã chọn so với đáp án đúng, lời giải. */
function Review({ attempt }: { attempt: AttemptDetail }) {
  const navigate = useNavigate();
  const [onlyWrong, setOnlyWrong] = useState(false);
  const [busy, setBusy] = useState(false);
  const results = attempt.results ?? {};
  const graded = Object.values(results).filter((r) => r.correct !== null);
  const nRight = graded.filter((r) => r.correct).length;
  const nWrong = graded.length - nRight;
  const ratio = attempt.max_score ? (attempt.score ?? 0) / attempt.max_score : 0;
  const scale10 = attempt.max_score ? (ratio * 10).toFixed(2).replace(".", ",") : null;

  const retry = async () => {
    setBusy(true);
    const a = await api.startAttempt({ retry_of: attempt.id });
    navigate(`/luyen/${a.id}`);
  };

  let number = 0;
  return (
    <div className="attempt">
      <div className="editor-head">
        <Link to="/luyen">‹ Luyện đề</Link>
        <h2>{attempt.title}</h2>
        {attempt.variant_code && <span className="muted">Mã đề {attempt.variant_code}</span>}
      </div>
      <div className="score-card">
        <div className="score-big">
          {fmtScore(attempt.score)}
          <span className="muted"> / {fmtScore(attempt.max_score)} điểm</span>
        </div>
        {scale10 && attempt.max_score !== 10 && <div className="muted">Quy ra thang 10: {scale10}</div>}
        <div>
          Đúng hoàn toàn {nRight}/{graded.length} câu chấm tự động
          {attempt.late && <span className="badge state-error"> Nộp quá giờ</span>}
        </div>
        <div className="toolbar">
          <label className="inline">
            <input type="checkbox" checked={onlyWrong} onChange={(e) => setOnlyWrong(e.target.checked)} /> Chỉ xem câu chưa đúng
          </label>
          {nWrong > 0 && (
            <button className="primary" disabled={busy} onClick={retry}>
              Luyện lại {nWrong} câu chưa đúng
            </button>
          )}
          {attempt.exam_id && <Link to={`/de/${attempt.exam_id}`}>Xem đề gốc</Link>}
        </div>
      </div>

      <div className="attempt-grid">
        <div className="paper">
          {attempt.data.sections.map((sec, si) => (
            <div key={si}>
              <h4>{sec.name}</h4>
              {sec.questions.map((q, qi) => {
                const key = `${si}.${qi}`;
                number += 1;
                const r = results[key];
                if (onlyWrong && r?.correct !== false) return null;
                return (
                  <div key={key} id={`q-${key}`} className="paper-q">
                    <div className="paper-q-head">
                      <b>Câu {number}.</b>
                      <ResultBadge r={r} />
                      <Link to={`/cau/${encodeURIComponent(q.code)}`} className="muted small">
                        {q.code} · {levelLabel(q.level)}
                      </Link>
                    </div>
                    <ReviewQuestion q={q} value={attempt.answers[key]} />
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <Navigator
          attempt={attempt}
          state={(k) => {
            const c = results[k]?.correct;
            return c === true ? "right" : c === false ? (results[k].points > 0 ? "partial" : "wrong") : "";
          }}
        />
      </div>
    </div>
  );
}

function ResultBadge({ r }: { r?: AttemptResult }) {
  if (!r) return null;
  if (r.correct === null) return <span className="badge">Tự luận, tự đối chiếu</span>;
  const cls = r.correct ? "approved" : r.points > 0 ? "draft" : "state-error";
  return (
    <span className={`badge ${cls}`}>
      {fmtScore(r.points)}/{fmtScore(r.max_points)} điểm
    </span>
  );
}

function ReviewQuestion({ q, value }: { q: AttemptQuestion; value: Answer | undefined }) {
  return (
    <div className="question">
      <Tex source={q.stem} />
      {q.type === "mcq" && (
        <div className="answer-choices">
          {q.choices.map((c, i) => (
            <div key={i} className={`answer-choice ${c.correct ? "correct" : ""} ${value === i && !c.correct ? "wrong" : ""}`}>
              <span className="label">{"ABCD"[i]}.</span>
              <Tex source={c.content} inline />
              {value === i && <span className="mine">bạn chọn</span>}
            </div>
          ))}
          {(value === undefined || value === null) && <div className="muted small">Bỏ trống</div>}
        </div>
      )}
      {q.type === "tf" && (
        <div className="statements">
          {q.choices.map((c, i) => {
            const mine = Array.isArray(value) ? value[i] : null;
            return (
              <div key={i} className="statement">
                <span className="label">{"abcd"[i]})</span>
                <span className="statement-text">
                  <Tex source={c.content} inline />
                </span>
                <span className={`tf ${c.correct ? "yes" : "no"}`}>{c.correct ? "Đúng" : "Sai"}</span>
                <span className={`mine ${mine === null || mine === undefined ? "" : mine === c.correct ? "ok" : "bad"}`}>
                  {mine === null || mine === undefined ? "bỏ trống" : `bạn chọn ${mine ? "Đúng" : "Sai"}`}
                </span>
              </div>
            );
          })}
        </div>
      )}
      {q.type === "short" && (
        <div className="short-answer">
          Bạn trả lời: <b>{typeof value === "string" && value ? value : "bỏ trống"}</b> · Đáp án: <b>{q.short_answer}</b>
        </div>
      )}
      {q.type === "essay" && typeof value === "string" && value && (
        <div className="essay-mine">
          <div className="muted small">Bài làm của bạn</div>
          {value}
        </div>
      )}
      {q.solution && (
        <div className="solution">
          <span className="solution-title">Lời giải.</span>
          <Tex source={q.solution} />
        </div>
      )}
    </div>
  );
}
