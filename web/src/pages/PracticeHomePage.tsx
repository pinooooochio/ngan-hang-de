import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  api,
  LEVELS,
  levelLabel,
  type AttemptSummary,
  type ExamSummary,
  type Level,
  type PracticeStats,
  type QuickSpec,
  type StatBucket,
  type TagNode,
} from "../api";
import { TagSelect } from "../components/TagTree";
import { isStaff, useAuth } from "../auth";

const fmt = (x: number | null) => (x === null ? "" : String(Math.round(x * 100) / 100).replace(".", ","));

const FILE_LABEL = { de: "Đề", loigiai: "Lời giải", dapan: "Đáp án" };

export default function PracticeHomePage() {
  const navigate = useNavigate();
  const { me } = useAuth();
  const staff = isStaff(me.role);
  const showQuick = staff || me.settings.student_quick;
  const [tags, setTags] = useState<TagNode[]>([]);
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [doing, setDoing] = useState<AttemptSummary[]>([]);
  const [quick, setQuick] = useState<QuickSpec>({ mcq: 10, tf: 0, short: 0, essay: 0 });
  const [timed, setTimed] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (showQuick) api.tags().then(setTags);
    api.listExams().then(setExams);
    api.listAttempts().then((all) => setDoing(all.filter((a) => !a.submitted_at)));
  }, []);

  const start = async (body: Parameters<typeof api.startAttempt>[0]) => {
    setBusy(true);
    setError("");
    try {
      const a = await api.startAttempt(body);
      navigate(`/luyen/${a.id}`);
    } catch (e) {
      setError(String((e as Error).message));
      setBusy(false);
    }
  };

  const nQuick = quick.mcq + quick.tf + quick.short + quick.essay;
  const count = (key: "mcq" | "tf" | "short" | "essay", label: string) => (
    <label>
      {label}
      <input type="number" min={0} value={quick[key]} onChange={(e) => setQuick({ ...quick, [key]: Number(e.target.value) || 0 })} />
    </label>
  );

  return (
    <div className="practice-home">
      <h2>Chọn đề làm</h2>
      {error && <div className="alert error">{error}</div>}
      {doing.length > 0 && (
        <div className="alert">
          Đang làm dở:{" "}
          {doing.map((a, i) => (
            <span key={a.id}>
              {i > 0 && ", "}
              <Link to={`/luyen/${a.id}`}>{a.title}</Link>
            </span>
          ))}
          . Xem tất cả ở <Link to="/luyen/ket-qua">Lịch sử và thống kê</Link>.
        </div>
      )}

      <div className={showQuick ? "practice-cols" : ""}>
        {showQuick && (
        <section className="section-card">
          <h3>Luyện nhanh từ ngân hàng</h3>
          <div className="quick-grid">
            <label className="wide">
              Thẻ (lớp / chủ đề / dạng)
              <TagSelect
                tags={tags}
                value={quick.tag ?? ""}
                placeholder="Mọi thẻ"
                showCount
                onChange={(p) => setQuick({ ...quick, tag: p || undefined })}
              />
            </label>
            <label>
              Mức độ
              <select value={quick.level ?? ""} onChange={(e) => setQuick({ ...quick, level: (e.target.value || undefined) as Level | undefined })}>
                <option value="">Mọi mức độ</option>
                {LEVELS.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
            {count("mcq", "Trắc nghiệm")}
            {count("tf", "Đúng/sai")}
            {count("short", "Trả lời ngắn")}
            {count("essay", "Tự luận")}
            <label>
              Thời gian (phút)
              <input
                type="number"
                min={1}
                placeholder="Không giới hạn"
                value={quick.duration ?? ""}
                onChange={(e) => setQuick({ ...quick, duration: e.target.value ? Number(e.target.value) : undefined })}
              />
            </label>
          </div>
          <button className="primary" disabled={busy || nQuick === 0} onClick={() => start({ quick })}>
            Bắt đầu luyện {nQuick} câu
          </button>
          <p className="hint">Chỉ lấy câu đã duyệt. Câu được chọn ngẫu nhiên và đảo đáp án mỗi lần.</p>
        </section>
        )}

        <section className="section-card">
          <h3>{staff ? "Làm đề trong kho" : "Đề được mở"}</h3>
          <label className="inline">
            <input type="checkbox" checked={timed} onChange={(e) => setTimed(e.target.checked)} /> Tính giờ theo thời gian của đề
          </label>
          {exams.length === 0 ? (
            staff ? (
              <div className="muted">
                Kho đề còn trống. <Link to="/de/moi">Ghép đề</Link>.
              </div>
            ) : (
              <div className="muted">Chưa có đề nào được mở. Khi admin mở đề, đề sẽ hiện ở đây.</div>
            )
          ) : (
            <table className="table">
              <tbody>
                {exams.map((e) => (
                  <tr key={e.id}>
                    <td>
                      {staff ? <Link to={`/de/${e.id}`}>{e.title}</Link> : <b>{e.title}</b>}
                      {staff && !e.published && <span className="badge draft">Chưa mở cho học viên</span>}
                      <div className="muted small">
                        {e.n_questions} câu{e.duration ? ` · ${e.duration} phút` : ""} · {e.n_variants} mã đề
                      </div>
                      {!staff && <StudentFiles exam={e} onChange={(x) => setExams(exams.map((y) => (y.id === x.id ? x : y)))} />}
                    </td>
                    <td className="right">
                      <button disabled={busy} onClick={() => start({ exam_id: e.id, timed })}>
                        Làm đề
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="hint">Mỗi lần làm lấy ngẫu nhiên một mã đề.</p>
        </section>
      </div>

    </div>
  );
}

/** File học viên tải được (đề; đáp án, lời giải khi admin đã đồng ý) và nút xin tải đáp án. */
function StudentFiles({ exam, onChange }: { exam: ExamSummary; onChange: (e: ExamSummary) => void }) {
  const [error, setError] = useState("");
  const files = (exam.files ?? []).filter((f) => f.url);
  const req = exam.request;
  const ask = async () => {
    setError("");
    try {
      onChange(await api.requestAnswers(exam.id));
    } catch (e) {
      setError(String((e as Error).message));
    }
  };
  return (
    <div className="student-files small">
      {files.map((f) => (
        <a key={f.name} href={f.url!} target="_blank" rel="noreferrer">
          {FILE_LABEL[f.kind]}
          {f.variant_code ? ` ${f.variant_code}` : ""}
        </a>
      ))}
      {req?.status === "approved" ? null : req?.status === "pending" ? (
        <span className="muted">Đã xin tải đáp án, chờ admin</span>
      ) : (
        <button className="link small" onClick={ask}>
          {req?.status === "rejected" ? `Xin lại đáp án${req.note ? ` (bị từ chối: ${req.note})` : ""}` : "Xin tải đáp án và lời giải"}
        </button>
      )}
      {error && <span className="bad">{error}</span>}
    </div>
  );
}

/** Lịch sử các lượt luyện và thống kê theo chủ đề, mức độ. */
export function PracticeResultsPage() {
  const { me } = useAuth();
  const [attempts, setAttempts] = useState<AttemptSummary[] | null>(null);
  const [stats, setStats] = useState<PracticeStats | null>(null);
  const [everyone, setEveryone] = useState(false);

  const reload = () => {
    api.listAttempts(undefined, everyone).then(setAttempts);
    api.attemptStats().then(setStats);
  };

  useEffect(reload, [everyone]);
  const canDelete = (a: AttemptSummary) => me.role === "admin" || (me.role === "editor" && a.user_id === me.id);

  const remove = async (a: AttemptSummary) => {
    if (!window.confirm(`Xoá lượt luyện "${a.title}"?`)) return;
    await api.deleteAttempt(a.id);
    reload();
  };

  return (
    <div className="practice-home">
      <h2>Lịch sử và thống kê</h2>
      <h3>Kết quả theo chủ đề và mức độ</h3>
      {stats && stats.attempts === 0 ? (
        <div className="muted">Chưa có lượt nào đã nộp.</div>
      ) : (
        stats && <StatsView stats={stats} />
      )}

      <div className="editor-head">
        <h3>Lịch sử luyện</h3>
        {me.role === "admin" && (
          <label className="inline">
            <input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} /> Xem bài của mọi người
          </label>
        )}
      </div>
      {attempts && attempts.length === 0 && <div className="muted">Chưa có lượt luyện nào.</div>}
      {attempts && attempts.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              {everyone && <th>Người làm</th>}
              <th>Đề</th>
              <th>Mã đề</th>
              <th>Bắt đầu</th>
              <th>Điểm</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {attempts.map((a) => (
              <tr key={a.id}>
                {everyone && <td>{a.user_name ?? <span className="muted">(không rõ)</span>}</td>}
                <td>
                  <Link to={`/luyen/${a.id}`}>{a.title}</Link>
                  <div className="muted small">{a.n_questions} câu</div>
                </td>
                <td>{a.variant_code ?? (a.kind === "quick" ? "Luyện nhanh" : "")}</td>
                <td className="muted">{a.started_at.replace("T", " ")}</td>
                <td>
                  {a.submitted_at ? (
                    <>
                      <b>{fmt(a.score)}</b>/{fmt(a.max_score)}
                      {a.late && <span className="badge state-error">quá giờ</span>}
                    </>
                  ) : (
                    <Link to={`/luyen/${a.id}`} className="badge draft">
                      Đang làm, tiếp tục
                    </Link>
                  )}
                </td>
                <td className="right">
                  {canDelete(a) && (
                    <button className="link danger" onClick={() => remove(a)}>
                      Xoá
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Bar({ b }: { b: StatBucket }) {
  const pct = b.ratio === null ? 0 : Math.round(b.ratio * 100);
  const cls = pct >= 80 ? "good" : pct >= 50 ? "mid" : "low";
  return (
    <div className="stat-bar" title={`${fmt(b.points)}/${fmt(b.max_points)} điểm`}>
      <div className={`stat-fill ${cls}`} style={{ width: `${pct}%` }} />
      <span>{pct}%</span>
    </div>
  );
}

function StatsView({ stats }: { stats: PracticeStats }) {
  const levels = LEVELS.map((l) => l.value as string)
    .concat([""])
    .filter((k) => stats.by_level[k]);
  return (
    <div className="practice-cols">
      <table className="table stats">
        <thead>
          <tr>
            <th>Mức độ</th>
            <th>Số câu đã làm</th>
            <th>Đúng hoàn toàn</th>
            <th>Tỉ lệ điểm</th>
          </tr>
        </thead>
        <tbody>
          {levels.map((k) => (
            <tr key={k}>
              <td>{levelLabel((k || null) as Level | null)}</td>
              <td>{stats.by_level[k].n}</td>
              <td>{stats.by_level[k].right}</td>
              <td>
                <Bar b={stats.by_level[k]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <table className="table stats">
        <thead>
          <tr>
            <th>Lớp / chủ đề</th>
            <th>Số câu</th>
            <th>Đúng</th>
            <th>Tỉ lệ điểm</th>
          </tr>
        </thead>
        <tbody>
          {stats.by_tag.map((t) => (
            <tr key={t.path}>
              <td style={{ paddingLeft: 6 + t.depth * 16 }}>{t.names[t.names.length - 1]}</td>
              <td>{t.n}</td>
              <td>{t.right}</td>
              <td>
                <Bar b={t} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
