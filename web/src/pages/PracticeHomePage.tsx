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

const fmt = (x: number | null) => (x === null ? "" : String(Math.round(x * 100) / 100).replace(".", ","));

export default function PracticeHomePage() {
  const navigate = useNavigate();
  const [tags, setTags] = useState<TagNode[]>([]);
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [attempts, setAttempts] = useState<AttemptSummary[] | null>(null);
  const [stats, setStats] = useState<PracticeStats | null>(null);
  const [quick, setQuick] = useState<QuickSpec>({ mcq: 10, tf: 0, short: 0, essay: 0 });
  const [timed, setTimed] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = () => {
    api.listAttempts().then(setAttempts);
    api.attemptStats().then(setStats);
  };

  useEffect(() => {
    api.tags().then(setTags);
    api.listExams().then(setExams);
    reload();
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

  const remove = async (a: AttemptSummary) => {
    if (!window.confirm(`Xoá lượt luyện "${a.title}"?`)) return;
    await api.deleteAttempt(a.id);
    reload();
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
      <h2>Luyện đề</h2>
      {error && <div className="alert error">{error}</div>}

      <div className="practice-cols">
        <section className="section-card">
          <h3>Luyện nhanh từ ngân hàng</h3>
          <div className="quick-grid">
            <label className="wide">
              Thẻ (lớp / chủ đề / dạng)
              <select value={quick.tag ?? ""} onChange={(e) => setQuick({ ...quick, tag: e.target.value || undefined })}>
                <option value="">Mọi thẻ</option>
                {tags.map((t) => (
                  <option key={t.path} value={t.path}>
                    {"  ".repeat(t.depth) + t.name} ({t.count})
                  </option>
                ))}
              </select>
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

        <section className="section-card">
          <h3>Làm đề trong kho</h3>
          <label className="inline">
            <input type="checkbox" checked={timed} onChange={(e) => setTimed(e.target.checked)} /> Tính giờ theo thời gian của đề
          </label>
          {exams.length === 0 ? (
            <div className="muted">
              Kho đề còn trống. <Link to="/de/moi">Ghép đề</Link>.
            </div>
          ) : (
            <table className="table">
              <tbody>
                {exams.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <Link to={`/de/${e.id}`}>{e.title}</Link>
                      <div className="muted small">
                        {e.n_questions} câu{e.duration ? ` · ${e.duration} phút` : ""} · {e.n_variants} mã đề
                      </div>
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

      <h3>Kết quả theo chủ đề và mức độ</h3>
      {stats && stats.attempts === 0 ? (
        <div className="muted">Chưa có lượt nào đã nộp.</div>
      ) : (
        stats && <StatsView stats={stats} />
      )}

      <h3>Lịch sử luyện</h3>
      {attempts && attempts.length === 0 && <div className="muted">Chưa có lượt luyện nào.</div>}
      {attempts && attempts.length > 0 && (
        <table className="table">
          <thead>
            <tr>
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
                  <button className="link danger" onClick={() => remove(a)}>
                    Xoá
                  </button>
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
