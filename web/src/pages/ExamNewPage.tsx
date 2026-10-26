import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  LEVELS,
  TYPES,
  typeLabel,
  type Level,
  type PickRow,
  type QType,
  type QuestionSummary,
  type SectionSpec,
  type TagNode,
} from "../api";
import Tex from "../components/Tex";

const SECTION_NAMES: Record<QType, string> = {
  mcq: "Câu trắc nghiệm nhiều phương án lựa chọn",
  tf: "Câu trắc nghiệm đúng sai",
  short: "Câu trắc nghiệm trả lời ngắn",
  essay: "Tự luận",
};

const ROMAN = ["I", "II", "III", "IV", "V", "VI"];

// Cấu trúc đề tốt nghiệp THPT môn Toán từ 2025
const THPT_2025: SectionSpec[] = [
  { name: `PHẦN I. ${SECTION_NAMES.mcq}`, type: "mcq", points: 0.25, pick: [{ count: 12 }], ids: [] },
  { name: `PHẦN II. ${SECTION_NAMES.tf}`, type: "tf", pick: [{ count: 4 }], ids: [] },
  { name: `PHẦN III. ${SECTION_NAMES.short}`, type: "short", points: 0.5, pick: [{ count: 6 }], ids: [] },
];

const today = () => new Date().toISOString().slice(0, 10);

export default function ExamNewPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(today());
  const [duration, setDuration] = useState<number | "">(90);
  const [variants, setVariants] = useState(4);
  const [firstCode, setFirstCode] = useState(101);
  const [sections, setSections] = useState<SectionSpec[]>(THPT_2025);
  const [tags, setTags] = useState<TagNode[]>([]);
  const [avail, setAvail] = useState<{ rows: number[]; problems: string[] }[]>([]);
  const [picked, setPicked] = useState<Record<string, QuestionSummary>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.tags().then(setTags);
  }, []);

  // Kiểm tra số câu còn trong ngân hàng mỗi khi ma trận đổi
  useEffect(() => {
    const t = setTimeout(() => {
      api
        .availability(sections)
        .then((r) => setAvail(r.sections))
        .catch(() => setAvail([]));
    }, 300);
    return () => clearTimeout(t);
  }, [sections]);

  const updateSection = (i: number, patch: Partial<SectionSpec>) =>
    setSections(sections.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const updateRow = (i: number, r: number, patch: Partial<PickRow>) =>
    updateSection(i, { pick: sections[i].pick.map((row, k) => (k === r ? { ...row, ...patch } : row)) });

  const addSection = () => {
    const type: QType = "essay";
    setSections([...sections, { name: `PHẦN ${ROMAN[sections.length] ?? sections.length + 1}. ${SECTION_NAMES[type]}`, type, pick: [], ids: [] }]);
  };

  const totalOf = (s: SectionSpec) => s.ids.length + s.pick.reduce((n, r) => n + (r.count || 0), 0);
  const total = sections.reduce((n, s) => n + totalOf(s), 0);
  const shortages = sections.flatMap((s, i) =>
    s.pick.flatMap((r, k) => {
      const have = avail[i]?.rows[k];
      return have !== undefined && have < r.count ? [`${s.name || `Phần ${i + 1}`}: dòng ${k + 1} cần ${r.count} câu, chỉ có ${have}`] : [];
    }),
  );
  const problems = [...shortages, ...avail.flatMap((a) => a.problems)];

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const exam = await api.createExam({
        title: title.trim(),
        date: date || undefined,
        duration: duration === "" ? undefined : duration,
        variants,
        first_code: firstCode,
        sections: sections.map((s) => ({ ...s, pick: s.pick.filter((r) => r.count > 0) })),
      });
      navigate(`/de/${exam.id}`);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="exam-new">
      <h2>Ghép đề mới</h2>
      <div className="form-grid">
        <label>
          Tiêu đề (chủ đề)
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ví dụ: Kiểm tra giữa kỳ Vectơ trong không gian" />
        </label>
        <label>
          Ngày
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          Thời gian (phút)
          <input type="number" min={1} value={duration} onChange={(e) => setDuration(e.target.value === "" ? "" : Number(e.target.value))} />
        </label>
        <label>
          Số mã đề
          <input type="number" min={1} max={30} value={variants} onChange={(e) => setVariants(Number(e.target.value))} />
        </label>
        <label>
          Mã đề đầu tiên
          <input type="number" value={firstCode} onChange={(e) => setFirstCode(Number(e.target.value))} />
        </label>
      </div>

      <div className="toolbar">
        <button onClick={() => setSections(THPT_2025)}>Điền cấu trúc THPT 2025</button>
        <button onClick={addSection}>+ Thêm phần</button>
      </div>

      {sections.map((s, i) => (
        <section key={i} className="section-card">
          <div className="section-head">
            <input className="section-name" value={s.name} onChange={(e) => updateSection(i, { name: e.target.value })} />
            <select
              value={s.type}
              onChange={(e) => updateSection(i, { type: e.target.value as QType, ids: [] })}
              title="Loại câu của phần này"
            >
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <label className="inline">
              Điểm mỗi câu
              <input
                type="number"
                step={0.05}
                min={0}
                value={s.points ?? ""}
                onChange={(e) => updateSection(i, { points: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
            </label>
            <span className="muted">{totalOf(s)} câu</span>
            <button className="link danger" onClick={() => setSections(sections.filter((_, k) => k !== i))}>
              Xoá phần
            </button>
          </div>

          <table className="matrix">
            <thead>
              <tr>
                <th>Thẻ (lớp / chủ đề / dạng)</th>
                <th>Mức độ</th>
                <th>Số câu</th>
                <th>Ngân hàng có</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {s.pick.map((r, k) => {
                const have = avail[i]?.rows[k];
                return (
                  <tr key={k}>
                    <td>
                      <select value={r.tag ?? ""} onChange={(e) => updateRow(i, k, { tag: e.target.value || undefined })}>
                        <option value="">Mọi thẻ</option>
                        {tags.map((t) => (
                          <option key={t.path} value={t.path}>
                            {"  ".repeat(t.depth) + t.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select value={r.level ?? ""} onChange={(e) => updateRow(i, k, { level: (e.target.value || undefined) as Level | undefined })}>
                        <option value="">Mọi mức độ</option>
                        {LEVELS.map((l) => (
                          <option key={l.value} value={l.value}>
                            {l.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input type="number" min={1} className="count" value={r.count} onChange={(e) => updateRow(i, k, { count: Number(e.target.value) })} />
                    </td>
                    <td className={have !== undefined && have < r.count ? "short" : "muted"}>
                      {have === undefined ? "…" : `${have} câu ${typeLabel(s.type).toLowerCase()}`}
                    </td>
                    <td>
                      <button className="link" onClick={() => updateSection(i, { pick: s.pick.filter((_, x) => x !== k) })}>
                        Xoá
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <button className="link" onClick={() => updateSection(i, { pick: [...s.pick, { count: 1 }] })}>
            + Thêm dòng ma trận
          </button>

          {s.ids.length > 0 && (
            <div className="picked">
              <div className="muted">Câu chọn tay:</div>
              {s.ids.map((code) => (
                <div key={code} className="picked-item">
                  <span className="code">{code}</span>
                  <span className="picked-stem">{picked[code] ? <Tex source={picked[code].stem} inline /> : null}</span>
                  <button className="link" onClick={() => updateSection(i, { ids: s.ids.filter((c) => c !== code) })}>
                    Bỏ
                  </button>
                </div>
              ))}
            </div>
          )}
          <QuestionPicker
            type={s.type}
            tags={tags}
            exclude={new Set(sections.flatMap((x) => x.ids))}
            onPick={(q) => {
              setPicked({ ...picked, [q.code]: q });
              updateSection(i, { ids: [...s.ids, q.code] });
            }}
          />
        </section>
      ))}

      <div className="submit-bar">
        <div>
          <b>Tổng {total} câu</b>, {variants} mã đề.
          {problems.map((p) => (
            <div key={p} className="alert warn">
              {p}
            </div>
          ))}
          {error && <div className="alert error">{error}</div>}
        </div>
        <button className="primary" disabled={busy || !title.trim() || total === 0 || problems.length > 0} onClick={submit}>
          {busy ? "Đang tạo…" : "Tạo đề"}
        </button>
      </div>
    </div>
  );
}

/** Tìm và chọn tay câu đã duyệt trong ngân hàng cho một phần. */
function QuestionPicker({
  type,
  tags,
  exclude,
  onPick,
}: {
  type: QType;
  tags: TagNode[];
  exclude: Set<string>;
  onPick: (q: QuestionSummary) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [items, setItems] = useState<QuestionSummary[]>([]);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      api.listQuestions({ type, status: "approved", q, tag, limit: 10 }).then((r) => setItems(r.items));
    }, 250);
    return () => clearTimeout(t);
  }, [open, q, tag, type]);

  if (!open)
    return (
      <button className="link" onClick={() => setOpen(true)}>
        + Chọn tay câu từ ngân hàng
      </button>
    );
  return (
    <div className="picker">
      <div className="picker-head">
        <input placeholder="Tìm theo nội dung hoặc mã câu" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
        <select value={tag} onChange={(e) => setTag(e.target.value)}>
          <option value="">Mọi thẻ</option>
          {tags.map((t) => (
            <option key={t.path} value={t.path}>
              {"  ".repeat(t.depth) + t.name}
            </option>
          ))}
        </select>
        <button className="link" onClick={() => setOpen(false)}>
          Đóng
        </button>
      </div>
      {items
        .filter((it) => !exclude.has(it.code))
        .map((it) => (
          <div key={it.code} className="picker-item" onClick={() => onPick(it)}>
            <span className="code">{it.code}</span>
            <Tex source={it.stem} inline />
          </div>
        ))}
      {items.length === 0 && <div className="muted">Không có câu {typeLabel(type).toLowerCase()} đã duyệt nào khớp.</div>}
    </div>
  );
}
