import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  LEVELS,
  TYPES,
  type Level,
  type LevelCounts,
  type QType,
  type TheoryTopicSummary,
  type TopicDocAvailability,
  type TopicDocConfig,
} from "../api";

type Grade = { ten: string; slug: string; topics: TheoryTopicSummary[] };
type Part = TopicDocConfig["parts"][number];

function Counts({ value, onChange }: { value: LevelCounts; onChange: (v: LevelCounts) => void }) {
  return (
    <span className="level-counts">
      {LEVELS.map((l) => (
        <label key={l.value} title={l.label}>
          {l.value}{" "}
          <input
            type="number"
            min={0}
            max={20}
            value={value[l.value] ?? 0}
            onChange={(e) => onChange({ ...value, [l.value]: Math.max(0, Math.min(20, Number(e.target.value) || 0)) })}
          />
        </label>
      ))}
    </span>
  );
}

function avail(q: Record<Level, number> | undefined) {
  if (!q) return "";
  return LEVELS.map((l) => `${l.value} ${q[l.value] ?? 0}`).join(" · ");
}

/** Tạo chuyên đề: chọn chủ đề, phần lý thuyết, số bài tập theo mức độ; đáp án và lời giải ở cuối quyển. */
export default function TopicDocNewPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [grades, setGrades] = useState<Grade[]>([]);
  const [title, setTitle] = useState("");
  const [parts, setParts] = useState<Part[]>([]);
  const [levels, setLevels] = useState<LevelCounts>({ NB: 2, TH: 2, VD: 1, VDC: 0 });
  const [mixed, setMixed] = useState<LevelCounts>({ NB: 0, TH: 0, VD: 0, VDC: 0 });
  const [types, setTypes] = useState<QType[]>(["mcq", "tf", "short", "essay"]);
  const [info, setInfo] = useState<Record<string, TopicDocAvailability>>({});
  const [adding, setAdding] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.theoryTopics().then((r) => setGrades(r.grades)).catch((e: Error) => setError(e.message));
    const from = Number(params.get("tu"));
    const topic = params.get("chude");
    if (from)
      api
        .topicDoc(from)
        .then((d) => {
          setTitle(d.config.title);
          setParts(d.config.parts);
          setLevels(d.config.levels);
          setMixed(d.config.mixed);
          setTypes(d.config.types);
        })
        .catch((e: Error) => setError(e.message));
    else if (topic) addTopic(topic);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cfg: TopicDocConfig = useMemo(() => ({ title, parts, levels, mixed, types }), [title, parts, levels, mixed, types]);

  // số khối lý thuyết, số câu có sẵn theo dạng / mức độ của các chủ đề đã chọn
  const key = JSON.stringify([parts.map((p) => p.path), types]);
  useEffect(() => {
    if (!parts.length) return;
    const t = setTimeout(() => {
      api
        .topicDocAvailability({ ...cfg, parts: parts.map((p) => ({ ...p, dang: [] })) })
        .then((rows) => setInfo(Object.fromEntries(rows.map((r) => [r.path, r]))))
        .catch((e: Error) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  async function addTopic(path: string) {
    if (!path) return;
    try {
      const [a] = await api.topicDocAvailability({ title: "", parts: [{ path, general: true, dang: [] }], levels: {}, mixed: {}, types });
      setInfo((old) => ({ ...old, [a.path]: a }));
      setParts((old) => (old.some((p) => p.path === a.path) ? old : [...old, { path: a.path, general: true, dang: a.dang_all }]));
      setAdding("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const update = (i: number, p: Part) => setParts(parts.map((x, j) => (j === i ? p : x)));
  const move = (i: number, d: number) => {
    const next = [...parts];
    const [x] = next.splice(i, 1);
    next.splice(i + d, 0, x);
    setParts(next);
  };

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const d = await api.createTopicDoc(cfg);
      navigate(`/chuyen-de/${d.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const perDang = LEVELS.reduce((a, l) => a + (levels[l.value] ?? 0), 0);
  const nDang = parts.reduce((a, p) => a + p.dang.length, 0);

  return (
    <div className="topic-doc-new">
      <div className="editor-head">
        <Link to="/chuyen-de">‹ Chuyên đề</Link>
        <h2>Tạo chuyên đề</h2>
      </div>
      <p className="hint">
        Chuyên đề gồm lý thuyết đã duyệt của các chủ đề (kiến thức chung, rồi từng dạng bài: phương pháp, ví dụ, lưu ý) và
        bài tập tự luyện chọn từ câu đã duyệt trong ngân hàng (ưu tiên câu ít dùng, mỗi nhóm biến thể một câu). Bảng đáp án
        và lời giải chi tiết ở cuối quyển. Câu đã dùng làm ví dụ trong lý thuyết không lặp lại ở bài tập.
      </p>
      {error && <div className="alert error">{error}</div>}
      <div className="toolbar">
        <label className="grow">
          Tên chuyên đề{" "}
          <input className="grow" value={title} placeholder="Để trống: Chuyên đề + tên các chủ đề" onChange={(e) => setTitle(e.target.value)} />
        </label>
      </div>
      <div className="toolbar">
        <select value={adding} onChange={(e) => setAdding(e.target.value)}>
          <option value="">Chọn chủ đề…</option>
          {grades.map((g) => (
            <optgroup key={g.slug} label={g.ten}>
              {g.topics.map((t) => (
                <option key={t.path} value={t.path} disabled={parts.some((p) => p.path === t.path)}>
                  {t.chuong ? `${t.chuong} › ` : ""}
                  {t.ten}
                  {t.approved ? ` (${t.approved} khối lý thuyết)` : " (chưa có lý thuyết)"}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <button disabled={!adding} onClick={() => addTopic(adding)}>
          Thêm chủ đề
        </button>
      </div>

      {parts.map((p, i) => {
        const a = info[p.path];
        const all = a?.dang_all ?? p.dang;
        return (
          <div key={p.path} className="card topic-doc-part">
            <div className="toolbar">
              <b>{a ? a.names.join(" › ") : p.path}</b>
              <span className="spacer" />
              <button className="link small" disabled={i === 0} onClick={() => move(i, -1)}>
                ↑
              </button>
              <button className="link small" disabled={i === parts.length - 1} onClick={() => move(i, 1)}>
                ↓
              </button>
              <Link className="small" to={`/ly-thuyet/cd/${p.path}`} target="_blank">
                Xem lý thuyết
              </Link>
              <button className="link small" onClick={() => setParts(parts.filter((_, j) => j !== i))}>
                Bỏ
              </button>
            </div>
            <label>
              <input type="checkbox" checked={p.general} onChange={(e) => update(i, { ...p, general: e.target.checked })} /> Kiến
              thức chung <span className="muted small">({a?.general_theory ?? 0} khối lý thuyết)</span>
            </label>
            <table className="topic-doc-dang small">
              <tbody>
                {all.map((d) => {
                  const row = a?.dang.find((x) => x.dang === d);
                  const on = p.dang.includes(d);
                  return (
                    <tr key={d} className={on ? "" : "muted"}>
                      <td>
                        <label>
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() =>
                              update(i, { ...p, dang: on ? p.dang.filter((x) => x !== d) : all.filter((x) => x === d || p.dang.includes(x)) })
                            }
                          />{" "}
                          {d}
                        </label>
                      </td>
                      <td className="nowrap">{row ? `${row.theory} khối lý thuyết` : ""}</td>
                      <td className="nowrap">{row ? `câu có sẵn: ${avail(row.questions)}` : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="toolbar small">
              <button className="link small" onClick={() => update(i, { ...p, dang: all })}>
                Chọn tất cả dạng
              </button>
              <button className="link small" onClick={() => update(i, { ...p, dang: [] })}>
                Bỏ chọn
              </button>
              {a && <span className="muted">Cả chủ đề có: {avail(a.topic_questions)} câu</span>}
            </div>
          </div>
        );
      })}

      {parts.length > 0 && (
        <div className="card">
          <div className="toolbar">
            <b>Bài tập tự luyện mỗi dạng</b>
            <Counts value={levels} onChange={setLevels} />
          </div>
          <div className="toolbar">
            <b>Bài tập tổng hợp cuối mỗi chủ đề</b>
            <Counts value={mixed} onChange={setMixed} />
          </div>
          <div className="toolbar">
            <b>Loại câu</b>
            {TYPES.map((t) => (
              <label key={t.value}>
                <input
                  type="checkbox"
                  checked={types.includes(t.value)}
                  onChange={(e) => setTypes(e.target.checked ? [...types, t.value] : types.filter((x) => x !== t.value))}
                />{" "}
                {t.label}
              </label>
            ))}
          </div>
          <div className="toolbar">
            <span className="muted small">
              {parts.length} chủ đề, {nDang} dạng bài, tối đa {perDang * nDang} bài tập theo dạng. Ngân hàng thiếu câu thì lấy
              hết câu có, trang chuyên đề sẽ ghi rõ chỗ thiếu.
            </span>
            <span className="spacer" />
            <button className="primary" disabled={busy || !types.length} onClick={create}>
              Tạo chuyên đề và xuất PDF
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
