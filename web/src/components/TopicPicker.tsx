import { useMemo, useState } from "react";
import { LEVELS, TYPES, type CurriculumGrade, type GenParams, type Level, type QType } from "../api";

interface Props {
  grades: CurriculumGrade[];
  grade: string;
  maxCount: number;
  defaultCount: number;
  onAdd: (rows: Omit<GenParams, "notes">[]) => void;
  onClose: () => void;
}

/** Khoá một mục được chọn: lớp, chủ đề, dạng ("" = đều các dạng). */
const key = (g: string, t: string, d = "") => `${g}\u0001${t}\u0001${d}`;
const unkey = (k: string) => {
  const [grade, topic, dang] = k.split("\u0001");
  return { grade, topic, dang: dang || undefined };
};
const fold = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();

/** Hộp chọn nhiều chủ đề (hoặc dạng) trên cây khung chương trình để thêm vào danh sách sinh,
 *  mỗi chủ đề × mỗi mức độ đã tick thành một dòng. */
export default function TopicPicker({ grades, grade: initialGrade, maxCount, defaultCount, onAdd, onClose }: Props) {
  const [grade, setGrade] = useState(initialGrade);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [levels, setLevels] = useState<Set<Level>>(new Set(["NB", "TH", "VD"]));
  const [type, setType] = useState<QType>("mcq");
  const [count, setCount] = useState(defaultCount);
  const [figure, setFigure] = useState(false);
  const [param, setParam] = useState(false);
  const canParam = type === "mcq" || type === "short";

  const g = grades.find((x) => x.ten === grade);
  const q = fold(search.trim());
  const match = (t: CurriculumGrade["chu_de"][number]) =>
    !q || fold(t.ten).includes(q) || fold(t.chuong).includes(q) || t.dang.some((d) => fold(d).includes(q));
  const topics = useMemo(() => (g?.chu_de ?? []).filter((t) => !t.label && match(t)), [g, q]); // eslint-disable-line react-hooks/exhaustive-deps

  // Gom theo chương (THPT không có chương: một nhóm tên rỗng)
  const chapters = useMemo(() => {
    const out: { name: string; topics: typeof topics }[] = [];
    for (const t of topics) {
      let c = out.find((x) => x.name === t.chuong);
      if (!c) out.push((c = { name: t.chuong, topics: [] }));
      c.topics.push(t);
    }
    return out;
  }, [topics]);

  const toggle = (k: string, on?: boolean) =>
    setPicked((s) => {
      const n = new Set(s);
      if (on ?? !n.has(k)) n.add(k);
      else n.delete(k);
      return n;
    });
  const setMany = (keys: string[], on: boolean) =>
    setPicked((s) => {
      const n = new Set(s);
      for (const k of keys) {
        if (on) n.add(k);
        else n.delete(k);
      }
      return n;
    });
  const allOn = (keys: string[]) => keys.length > 0 && keys.every((k) => picked.has(k));
  const toggleOpen = (k: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  const allLevels = levels.size === LEVELS.length;
  const nRows = picked.size * levels.size;
  const add = () => {
    const rows: Omit<GenParams, "notes">[] = [];
    for (const k of picked)
      for (const l of LEVELS)
        if (levels.has(l.value)) rows.push({
            ...unkey(k),
            level: l.value,
            type,
            count,
            figure: (figure && !param) || undefined,
            param: (param && canParam) || undefined,
          });
    onAdd(rows);
  };

  const topicKeys = (list: typeof topics) => list.map((t) => key(grade, t.ten));
  const byGrade = [...new Set(grades.map((x) => x.bac))];
  const pickedHere = [...picked].filter((k) => unkey(k).grade === grade).length;

  return (
    <div className="topic-picker section-card">
      <div className="toolbar">
        <b>Thêm chủ đề vào danh sách sinh</b>
        <span className="spacer" />
        <button className="link" onClick={onClose}>
          Đóng
        </button>
      </div>
      <div className="toolbar">
        <select value={grade} onChange={(e) => setGrade(e.target.value)}>
          {byGrade.map((bac) => (
            <optgroup key={bac} label={bac}>
              {grades
                .filter((x) => x.bac === bac)
                .map((x) => (
                  <option key={x.slug} value={x.ten}>
                    {x.ten}
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
        <input placeholder="Tìm chủ đề hoặc dạng" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="inline">
          <input
            type="checkbox"
            checked={allOn(topicKeys(topics))}
            onChange={(e) => setMany(topicKeys(topics), e.target.checked)}
          />{" "}
          Chọn tất cả{search ? " kết quả tìm" : ` chủ đề ${grade}`}
        </label>
        {pickedHere > 0 && <span className="muted small">đã chọn {pickedHere} mục ở {grade}</span>}
      </div>

      <div className="picker-tree">
        {chapters.length === 0 && <div className="muted">Không có chủ đề nào khớp.</div>}
        {chapters.map((c) => (
          <div key={c.name || "-"}>
            {c.name && (
              <label className="picker-chapter">
                <input
                  type="checkbox"
                  checked={allOn(topicKeys(c.topics))}
                  onChange={(e) => setMany(topicKeys(c.topics), e.target.checked)}
                />{" "}
                {c.name}
              </label>
            )}
            {c.topics.map((t) => {
              const tk = key(grade, t.ten);
              const nDang = t.dang.filter((d) => picked.has(key(grade, t.ten, d))).length;
              return (
                <div key={t.path} className={`picker-topic ${c.name ? "indent" : ""}`}>
                  <label>
                    <input type="checkbox" checked={picked.has(tk)} onChange={() => toggle(tk)} /> {t.ten}
                  </label>
                  {t.dang.length > 0 && (
                    <button className="link small" onClick={() => toggleOpen(tk)}>
                      {open.has(tk) || q ? "▾" : "▸"} {t.dang.length} dạng
                      {nDang > 0 && ` (chọn ${nDang})`}
                    </button>
                  )}
                  {(open.has(tk) || (q && !fold(t.ten).includes(q))) && (
                    <div className="picker-dang">
                      {t.dang
                        .filter((d) => !q || fold(t.ten).includes(q) || fold(d).includes(q))
                        .map((d) => (
                          <label key={d}>
                            <input
                              type="checkbox"
                              checked={picked.has(key(grade, t.ten, d))}
                              onChange={() => toggle(key(grade, t.ten, d))}
                            />{" "}
                            {d}
                          </label>
                        ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <p className="hint">Tick chủ đề để sinh đều các dạng, hoặc mở chủ đề để tick từng dạng bài.</p>

      <div className="toolbar picker-defaults">
        <span>Mức độ:</span>
        <label className="inline">
          <input
            type="checkbox"
            checked={allLevels}
            onChange={(e) => setLevels(new Set(e.target.checked ? LEVELS.map((l) => l.value) : []))}
          />{" "}
          Tất cả
        </label>
        {LEVELS.map((l) => (
          <label key={l.value} className="inline">
            <input
              type="checkbox"
              checked={levels.has(l.value)}
              onChange={(e) =>
                setLevels((s) => {
                  const n = new Set(s);
                  if (e.target.checked) n.add(l.value);
                  else n.delete(l.value);
                  return n;
                })
              }
            />{" "}
            {l.label}
          </label>
        ))}
      </div>
      <div className="toolbar picker-defaults">
        <label className="inline">
          Loại câu
          <select value={type} onChange={(e) => setType(e.target.value as QType)}>
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="inline">
          Số câu mỗi dòng
          <input
            type="number"
            className="num"
            min={1}
            max={maxCount}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(maxCount, Number(e.target.value) || 1)))}
          />
        </label>
        <label className="inline">
          <input type="checkbox" checked={figure && !param} disabled={param} onChange={(e) => setFigure(e.target.checked)} /> Có
          hình vẽ
        </label>
        <label className="inline" title="Chỉ trắc nghiệm và trả lời ngắn">
          <input
            type="checkbox"
            checked={param && canParam}
            disabled={!canParam}
            onChange={(e) => setParam(e.target.checked)}
          />{" "}
          Câu tham số
        </label>
        <span className="spacer" />
        <span className="muted small">
          {picked.size} mục × {levels.size} mức độ = {nRows} dòng, {nRows * count} câu
        </span>
        <button className="primary" disabled={nRows === 0} onClick={add}>
          Thêm {nRows} dòng
        </button>
      </div>
    </div>
  );
}
