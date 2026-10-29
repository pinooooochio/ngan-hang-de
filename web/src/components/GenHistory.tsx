import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { levelLabel, typeLabel, type CurriculumGrade, type GenBatch } from "../api";
import { useAuth } from "../auth";

export const STATUS_LABEL = { pending: "Đang chờ", running: "Đang sinh", done: "Xong", failed: "Lỗi" };

export function bankLink(source: string) {
  return `/?nguon=${encodeURIComponent(source)}&trangthai=draft`;
}

const PAGE = 5; // số lần sinh hiện sẵn trong mỗi chủ đề
const RECENT_FAIL_MS = 24 * 3600 * 1000; // lần lỗi trong 24 giờ qua được ghim lên đầu

type Filter = "all" | "running" | "failed" | "review";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "Mọi trạng thái" },
  { value: "running", label: "Đang chạy" },
  { value: "failed", label: "Lỗi" },
  { value: "review", label: "Còn câu chờ duyệt" },
];

const isRunning = (b: GenBatch) => b.status === "pending" || b.status === "running";
const pinned = (b: GenBatch) =>
  isRunning(b) || (b.status === "failed" && Date.now() - new Date(b.created_at).getTime() < RECENT_FAIL_MS);

interface TopicGroup {
  key: string;
  name: string;
  batches: GenBatch[];
}
interface ChapterGroup {
  key: string;
  name: string; // "" = chủ đề nằm thẳng dưới lớp (THPT)
  topics: TopicGroup[];
}
interface GradeGroup {
  key: string;
  name: string;
  chapters: ChapterGroup[];
  batches: GenBatch[];
}

const gradeKey = (g: string) => `g:${g}`;
const chapterKey = (g: string, c: string) => `c:${g}/${c}`;
const topicKey = (g: string, t: string) => `t:${g}/${t}`;

/** Gom các lần sinh theo khung chương trình: Lớp/Học phần › (Chương) › Chủ đề, giữ thứ tự của khung;
 *  lớp, chủ đề ngoài khung xếp sau theo tên. Trong mỗi chủ đề, lần mới nhất đứng trước. */
function groupBatches(batches: GenBatch[], grades: CurriculumGrade[]): GradeGroup[] {
  const gradeOrder = new Map(grades.map((g, i) => [g.ten, i]));
  const out = new Map<string, GradeGroup>();
  for (const b of batches) {
    const gname = b.params.grade;
    const cg = grades.find((g) => g.ten === gname);
    const ct = cg?.chu_de.find((t) => t.ten === b.params.topic);
    const cname = ct?.chuong ?? "";
    let g = out.get(gname);
    if (!g) out.set(gname, (g = { key: gradeKey(gname), name: gname, chapters: [], batches: [] }));
    g.batches.push(b);
    let c = g.chapters.find((x) => x.name === cname);
    if (!c) g.chapters.push((c = { key: chapterKey(gname, cname), name: cname, topics: [] }));
    let t = c.topics.find((x) => x.name === b.params.topic);
    if (!t) c.topics.push((t = { key: topicKey(gname, b.params.topic), name: b.params.topic, batches: [] }));
    t.batches.push(b);
  }
  const byName = (a: string, b: string) => a.localeCompare(b, "vi");
  const rank = (order: Map<string, number>, name: string) => order.get(name) ?? order.size;
  const groups = [...out.values()];
  for (const g of groups) {
    const cg = grades.find((x) => x.ten === g.name);
    const chapterOrder = new Map((cg?.chuong ?? []).map((c, i) => [c.ten, i]));
    const topicOrder = new Map((cg?.chu_de ?? []).map((t, i) => [t.ten, i]));
    // chủ đề thẳng dưới lớp đứng trước các chương
    g.chapters.sort((a, b) =>
      a.name === "" ? -1 : b.name === "" ? 1 : rank(chapterOrder, a.name) - rank(chapterOrder, b.name) || byName(a.name, b.name),
    );
    for (const c of g.chapters) {
      c.topics.sort((a, b) => rank(topicOrder, a.name) - rank(topicOrder, b.name) || byName(a.name, b.name));
      for (const t of c.topics) t.batches.sort((a, b) => b.id - a.id);
    }
  }
  return groups.sort((a, b) => rank(gradeOrder, a.name) - rank(gradeOrder, b.name) || byName(a.name, b.name));
}

function Summary({ batches }: { batches: GenBatch[] }) {
  const pending = batches.reduce((s, b) => s + (b.n_pending ?? 0), 0);
  const running = batches.filter(isRunning).length;
  return (
    <span className="muted small gen-sum">
      {batches.length} lần
      {pending > 0 && <span className="badge draft">{pending} câu chờ duyệt</span>}
      {running > 0 && <span className="badge">{running} đang chạy</span>}
    </span>
  );
}

function BatchTable({ batches, showTopic = false }: { batches: GenBatch[]; showTopic?: boolean }) {
  return (
    <table className="table gen-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Yêu cầu</th>
          <th>Người tạo</th>
          <th>Trạng thái</th>
          <th>Kết quả</th>
          <th>Lúc</th>
        </tr>
      </thead>
      <tbody>
        {batches.map((b) => (
          <tr key={b.id}>
            <td>
              <Link to={`/sinh/${b.id}`}>#{b.id}</Link>
            </td>
            <td>
              {showTopic && <div>{b.params.topic}</div>}
              <div className={showTopic ? "muted small" : ""}>
                {showTopic && <>{b.params.grade} · </>}
                {levelLabel(b.params.level)} · {typeLabel(b.params.type)} · {b.params.count} câu
                {b.params.dang && <> · {b.params.dang}</>}
                {b.params.figure && <> · có hình</>}
              </div>
            </td>
            <td>
              {b.username ?? <span className="muted">—</span>}
              <div className="muted small">{b.mode === "api" ? "Claude API" : "Dán tay"}</div>
            </td>
            <td>
              <span className={`badge ${b.status === "done" ? "approved" : b.status === "failed" ? "state-error" : "draft"}`}>
                {STATUS_LABEL[b.status]}
              </span>
              {b.error && <div className="muted small">{b.error}</div>}
            </td>
            <td>
              {b.status === "done" && (
                <>
                  {b.n_added > 0 ? (
                    <Link to={bankLink(b.source)}>
                      {b.n_pending ? `Duyệt ${b.n_pending}/${b.n_added} câu` : `${b.n_added} câu đã duyệt hết`}
                    </Link>
                  ) : (
                    "0 câu mới"
                  )}
                  {(b.n_duplicate > 0 || b.n_error > 0) && (
                    <div className="muted small">
                      {b.n_duplicate} trùng, {b.n_error} lỗi
                    </div>
                  )}
                </>
              )}
            </td>
            <td className="muted">{b.created_at.replace("T", " ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TopicBatches({ batches }: { batches: GenBatch[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? batches : batches.slice(0, PAGE);
  return (
    <div className="gen-topic-body">
      <BatchTable batches={shown} />
      {batches.length > PAGE && (
        <button className="link" onClick={() => setAll(!all)}>
          {all ? "Thu gọn" : `Xem thêm ${batches.length - PAGE} lần cũ hơn`}
        </button>
      )}
    </div>
  );
}

interface Props {
  batches: GenBatch[];
  grades: CurriculumGrade[];
  /** Lớp đang chọn ở bảng độ phủ: nhóm này mở sẵn. */
  grade: string;
  /** Chủ đề vừa bấm ở bảng độ phủ: mở đúng nhóm đó. */
  focusTopic?: string;
}

/** Lịch sử các lần sinh, nhóm theo khung chương trình và thu gọn được. */
export default function GenHistory({ batches, grades, grade, focusTopic }: Props) {
  const { me } = useAuth();
  const [filter, setFilter] = useState<Filter>("all");
  const [mine, setMine] = useState(false);
  const [open, setOpen] = useState<Set<string>>(() => new Set([gradeKey(grade)]));

  const visible = useMemo(
    () =>
      batches.filter(
        (b) =>
          (!mine || b.user_id === me.id) &&
          (filter === "all" ||
            (filter === "running" && isRunning(b)) ||
            (filter === "failed" && b.status === "failed") ||
            (filter === "review" && (b.n_pending ?? 0) > 0)),
      ),
    [batches, filter, mine, me.id],
  );
  const groups = useMemo(() => groupBatches(visible, grades), [visible, grades]);
  const pins = batches.filter(pinned);

  const add = (...keys: string[]) => setOpen((s) => new Set([...s, ...keys]));
  useEffect(() => add(gradeKey(grade)), [grade]);
  useEffect(() => {
    if (!focusTopic) return;
    const ct = grades.find((g) => g.ten === grade)?.chu_de.find((t) => t.ten === focusTopic);
    add(gradeKey(grade), chapterKey(grade, ct?.chuong ?? ""), topicKey(grade, focusTopic));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusTopic]);

  const toggle = (key: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  const allKeys = () =>
    groups.flatMap((g) => [g.key, ...g.chapters.flatMap((c) => [c.key, ...c.topics.map((t) => t.key)])]);
  // đang lọc thì mở hết để thấy ngay kết quả lọc
  const filtering = filter !== "all" || mine;
  const isOpen = (key: string) => filtering || open.has(key);

  const head = (key: string, name: string, list: GenBatch[], level: number) => (
    <button className={`gen-group-head lvl-${level}`} aria-expanded={isOpen(key)} onClick={() => toggle(key)}>
      <span className="twisty">{isOpen(key) ? "▾" : "▸"}</span>
      <span className="gen-group-name">{name}</span>
      <Summary batches={list} />
    </button>
  );

  return (
    <section className="gen-history">
      <div className="toolbar">
        <h3>Các lần sinh</h3>
        <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
        <label className="inline">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Chỉ lần của tôi
        </label>
        <span className="spacer" />
        <button className="link" onClick={() => setOpen(new Set(allKeys()))}>
          Mở hết
        </button>
        <button className="link" onClick={() => setOpen(new Set())}>
          Thu gọn
        </button>
      </div>

      {pins.length > 0 && (
        <div className="gen-pins">
          <div className="muted small">Đang chạy và lỗi trong 24 giờ qua</div>
          <BatchTable batches={pins} showTopic />
        </div>
      )}

      {batches.length === 0 ? (
        <div className="muted">Chưa có lần sinh nào.</div>
      ) : groups.length === 0 ? (
        <div className="muted">Không có lần sinh nào khớp bộ lọc.</div>
      ) : (
        <div className="gen-groups">
          {groups.map((g) => (
            <div key={g.key} className="gen-group">
              {head(g.key, g.name, g.batches, 0)}
              {isOpen(g.key) &&
                g.chapters.map((c) => {
                  const topics = c.topics.map((t) => (
                    <div key={t.key} className="gen-group">
                      {head(t.key, t.name, t.batches, c.name ? 2 : 1)}
                      {isOpen(t.key) && <TopicBatches batches={t.batches} />}
                    </div>
                  ));
                  if (!c.name) return topics;
                  return (
                    <div key={c.key} className="gen-group">
                      {head(c.key, c.name, c.topics.flatMap((t) => t.batches), 1)}
                      {isOpen(c.key) && topics}
                    </div>
                  );
                })}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
