import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, slugify, type Level, type Overview, type OverviewCount, type OverviewGrade, type OverviewTheory, type OverviewTopic } from "../api";

const LEVELS: Level[] = ["NB", "TH", "VD", "VDC"];
const LEVEL_NAME: Record<Level, string> = { NB: "Nhận biết", TH: "Thông hiểu", VD: "Vận dụng", VDC: "Vận dụng cao" };
const FEW = 10;
const fmt = (n: number) => n.toLocaleString("vi-VN");
const bankLink = (path: string, draft = false) => `/?the=${encodeURIComponent(path)}${draft ? "&trangthai=draft" : ""}`;

/** Thanh tỷ lệ câu đã duyệt theo mức độ. */
function LevelBar({ c }: { c: OverviewCount }) {
  const total = LEVELS.reduce((s, l) => s + c.levels[l], 0);
  return (
    <div className="ov-track" role="img" aria-label={LEVELS.map((l) => `${LEVEL_NAME[l]} ${c.levels[l]}`).join(", ")}>
      {total > 0 &&
        LEVELS.map((l) => <i key={l} className={`lv-${l}`} style={{ width: `${(100 * c.levels[l]) / total}%` }} title={`${LEVEL_NAME[l]}: ${c.levels[l]}`} />)}
    </div>
  );
}

function Meter({ label, value, of, kind }: { label: string; value: number; of: number; kind: "q" | "t" }) {
  return (
    <div className="ov-meter">
      <span>{label}</span>
      <div className="ov-track">
        <i className={`fill-${kind}`} style={{ width: of ? `${(100 * value) / of}%` : 0 }} />
      </div>
      <span>
        {value}/{of}
      </span>
    </div>
  );
}

function Legend() {
  return (
    <div className="ov-legend">
      {LEVELS.map((l) => (
        <span key={l}>
          <i className={`lv-${l}`} />
          {LEVEL_NAME[l]}
        </span>
      ))}
    </div>
  );
}

function TheoryPill({ t }: { t: OverviewTheory }) {
  if (t.approved) return <span className="pill ok">Có lý thuyết</span>;
  if (t.draft) return <span className="pill warn">Lý thuyết nháp</span>;
  return <span className="pill">Chưa có lý thuyết</span>;
}

/** Số liệu tổng hợp của một lớp / học phần. */
function gradeStats(g: OverviewGrade) {
  return {
    withQ: g.topics.filter((t) => t.approved > 0).length,
    withT: g.topics.filter((t) => t.theory.approved > 0).length,
    nDang: g.topics.reduce((s, t) => s + t.dang.length, 0),
  };
}

function GradeCard({ g }: { g: OverviewGrade }) {
  const s = gradeStats(g);
  return (
    <Link className="ov-card" to={`/chu-de/${g.slug}`}>
      <div className="ov-card-top">
        <b>{g.ten}</b>
        <span className="spacer" />
        <span className="pill acc">{g.bac}</span>
      </div>
      <div className="ov-big">
        <b>{fmt(g.approved)}</b>
        <span>câu đã duyệt</span>
        {g.draft > 0 && <span className="pill warn">{g.draft} nháp</span>}
      </div>
      <div className="ov-meter">
        <span>Mức độ</span>
        <LevelBar c={g} />
        <span />
      </div>
      <Meter label="Có câu hỏi" value={s.withQ} of={g.topics.length} kind="q" />
      <Meter label="Có lý thuyết" value={s.withT} of={g.topics.length} kind="t" />
      <div className="ov-card-foot">
        {g.topics.length} chủ đề · {s.nDang} dạng bài · {g.docs} chuyên đề
      </div>
    </Link>
  );
}

function Home({ data }: { data: Overview }) {
  const topics = data.grades.flatMap((g) => g.topics);
  const withQ = topics.filter((t) => t.approved > 0).length;
  const withT = topics.filter((t) => t.theory.approved > 0).length;
  const groups = [...new Set(data.grades.map((g) => g.bac))];
  return (
    <div className="ov">
      <div className="toolbar">
        <h2>Ngân hàng theo chủ đề</h2>
        <span className="spacer" />
        <Link className="button" to="/">
          Danh sách tất cả câu
        </Link>
        <Link className="button primary" to="/cau/moi">
          Soạn câu mới
        </Link>
      </div>
      <p className="hint">
        Mỗi thẻ là một lớp hoặc học phần trong khung chương trình. Bấm vào thẻ để xem từng chủ đề: số câu theo mức độ, câu nháp chờ duyệt, đã có lý
        thuyết chưa.
      </p>
      <div className="ov-totals">
        <div>
          <b>{fmt(data.total.approved)}</b>
          <span>câu đã duyệt</span>
        </div>
        <div>
          <b>{fmt(data.total.draft)}</b>
          <span>câu nháp chờ duyệt</span>
        </div>
        <div>
          <b>
            {withQ}/{topics.length}
          </b>
          <span>chủ đề có câu hỏi</span>
        </div>
        <div>
          <b>
            {withT}/{topics.length}
          </b>
          <span>chủ đề có lý thuyết</span>
        </div>
      </div>
      <Legend />
      {groups.map((bac) => (
        <Fragment key={bac}>
          <h3 className="ov-group">{bac === "THPT" ? "Trung học phổ thông" : bac === "Đại học" ? "Đại học (khung Bách khoa)" : bac}</h3>
          <div className="ov-grid">
            {data.grades
              .filter((g) => g.bac === bac)
              .map((g) => (
                <GradeCard key={g.slug} g={g} />
              ))}
          </div>
        </Fragment>
      ))}
      {data.other > 0 && (
        <p className="hint">
          Có {data.other} câu không thuộc lớp hoặc học phần nào trong khung chương trình (chưa gắn thẻ hoặc thẻ khung cũ), xem ở{" "}
          <Link to="/">Danh sách câu</Link> hoặc chuyển thẻ ở <Link to="/the">Quản lý thẻ</Link>.
        </p>
      )}
    </div>
  );
}

type Filter = "all" | "noq" | "few" | "notheory" | "draft";
const FILTERS: [Filter, string][] = [
  ["all", "Tất cả"],
  ["noq", "Chưa có câu"],
  ["few", `Ít câu (dưới ${FEW})`],
  ["notheory", "Chưa có lý thuyết"],
  ["draft", "Có câu nháp"],
];

function passes(t: OverviewTopic, f: Filter, q: string) {
  if (q && !`${t.ten} ${t.chuong}`.toLowerCase().includes(q.toLowerCase())) return false;
  switch (f) {
    case "noq":
      return t.approved === 0;
    case "few":
      return t.approved > 0 && t.approved < FEW;
    case "notheory":
      return t.theory.approved === 0;
    case "draft":
      return t.draft > 0;
    default:
      return true;
  }
}

function Count({ n }: { n: number }) {
  return n ? <b>{n}</b> : <span className="ov-zero">0</span>;
}

function GradeDetail({ g }: { g: OverviewGrade }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const s = gradeStats(g);
  const shown = g.topics.filter((t) => passes(t, filter, query));
  const toggle = (path: string) => {
    const next = new Set(open);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setOpen(next);
  };
  const genLink = (t?: OverviewTopic) => `/sinh?lop=${encodeURIComponent(g.ten)}${t ? `&chude=${encodeURIComponent(t.ten)}` : ""}`;

  return (
    <div className="ov">
      <div className="muted small">
        <Link to="/chu-de">Ngân hàng theo chủ đề</Link> › {g.bac}
      </div>
      <div className="toolbar">
        <h2>{g.ten}</h2>
        <span className="spacer" />
        <Link className="button" to={bankLink(g.slug)}>
          Xem các câu
        </Link>
        <Link className="button" to="/de/moi">
          Ghép đề
        </Link>
        <Link className="button" to="/chuyen-de/moi">
          Tạo chuyên đề
        </Link>
        <Link className="button primary" to={genLink()}>
          Sinh câu AI
        </Link>
      </div>
      {g.ghi_chu && <p className="hint">{g.ghi_chu}</p>}
      <div className="ov-totals">
        <div>
          <b>{fmt(g.approved)}</b>
          <span>câu đã duyệt</span>
        </div>
        <div>
          <b>{fmt(g.draft)}</b>
          <span>câu nháp</span>
        </div>
        <div>
          <b>
            {s.withQ}/{g.topics.length}
          </b>
          <span>chủ đề có câu</span>
        </div>
        <div>
          <b>
            {s.withT}/{g.topics.length}
          </b>
          <span>chủ đề có lý thuyết</span>
        </div>
        <div>
          <b>{g.docs}</b>
          <span>chuyên đề đã tạo</span>
        </div>
      </div>
      <div className="ov-filters">
        {FILTERS.map(([v, label]) => (
          <button key={v} className={`chip ${filter === v ? "on" : ""}`} onClick={() => setFilter(v)}>
            {label}
          </button>
        ))}
        <input placeholder="Tìm chủ đề…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <span className="spacer" />
        <Legend />
      </div>
      <div className="ov-table-box">
        <table className="table ov-table">
          <thead>
            <tr>
              <th>Chủ đề</th>
              <th>Đã duyệt</th>
              <th>Theo mức độ</th>
              <th>Chờ duyệt</th>
              <th>Lý thuyết</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((t, i) => {
              const isOpen = open.has(t.path);
              return (
                <Fragment key={t.path}>
                  {t.chuong && t.chuong !== shown[i - 1]?.chuong && (
                    <tr className="ov-chap">
                      <td colSpan={6}>{t.chuong}</td>
                    </tr>
                  )}
                  <tr
                    className={`ov-topic ${isOpen ? "open" : ""}`}
                    tabIndex={0}
                    aria-expanded={isOpen}
                    onClick={(e) => !(e.target as HTMLElement).closest("a") && toggle(t.path)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggle(t.path);
                      }
                    }}
                  >
                    <td>
                      <span className="ov-caret">▸</span>
                      <b>{t.ten}</b>
                      <div className="muted small ov-sub">{t.dang.length} dạng bài</div>
                    </td>
                    <td>
                      <Count n={t.approved} />
                    </td>
                    <td>
                      <div className="ov-lv">
                        <LevelBar c={t} />
                        <div className="ov-nums">
                          {LEVELS.map((l) => (
                            <span key={l}>
                              {l} <b>{t.levels[l]}</b>
                            </span>
                          ))}
                        </div>
                      </div>
                    </td>
                    <td>
                      {t.draft ? (
                        <Link className="pill warn" to={bankLink(t.path, true)}>
                          {t.draft} nháp
                        </Link>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <TheoryPill t={t.theory} />
                      {t.docs > 0 && <span className="pill acc">{t.docs} chuyên đề</span>}
                    </td>
                    <td>
                      <div className="ov-acts">
                        <Link to={bankLink(t.path)}>Xem câu</Link>
                        <Link to={`/ly-thuyet/cd/${t.path}`}>Lý thuyết</Link>
                        <Link to={genLink(t)}>Sinh câu AI</Link>
                        {t.theory.approved > 0 && <Link to={`/chuyen-de/moi?chude=${encodeURIComponent(t.path)}`}>Chuyên đề</Link>}
                      </div>
                    </td>
                  </tr>
                  {isOpen &&
                    t.dang.map((d) => (
                      <tr key={d.name} className="ov-dang">
                        <td>{d.name}</td>
                        <td>
                          <Count n={d.approved} />
                        </td>
                        <td>
                          {d.approved > 0 && (
                            <div className="ov-nums">
                              {LEVELS.map((l) => (
                                <span key={l}>
                                  {l} <b>{d.levels[l]}</b>
                                </span>
                              ))}
                            </div>
                          )}
                        </td>
                        <td>{d.draft > 0 && <span className="pill warn">{d.draft} nháp</span>}</td>
                        <td>
                          {d.theory.approved ? (
                            <span className="pill ok">Có lý thuyết</span>
                          ) : d.theory.draft ? (
                            <span className="pill warn">Nháp</span>
                          ) : (
                            <span className="pill">Chưa có</span>
                          )}
                        </td>
                        <td>
                          <div className="ov-acts">
                            <Link to={bankLink(`${t.path}/${slugify(d.name)}`)}>Xem câu</Link>
                            {d.theory.approved + d.theory.draft > 0 && <Link to={`/ly-thuyet/cd/${t.path}#dang-${slugify(d.name)}`}>Lý thuyết</Link>}
                          </div>
                        </td>
                      </tr>
                    ))}
                  {isOpen && !t.dang.length && (
                    <tr className="ov-dang">
                      <td colSpan={6}>Chủ đề chưa chia dạng bài trong khung chương trình.</td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {!shown.length && (
              <tr>
                <td colSpan={6} className="muted">
                  Không có chủ đề nào khớp bộ lọc.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="hint">Bấm vào một chủ đề để xem từng dạng bài. Số 0 màu đỏ là chỗ còn trống cần soạn thêm. Số câu tính câu đã duyệt.</p>
    </div>
  );
}

/** Ngân hàng theo chủ đề: tổng quan các lớp / học phần, hoặc bảng chủ đề của một lớp (/chu-de/:slug). */
export default function OverviewPage() {
  const { slug } = useParams();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.overview().then(setData).catch((e: Error) => setError(e.message));
  }, []);
  const grade = useMemo(() => data?.grades.find((g) => g.slug === slug), [data, slug]);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [slug]);

  if (error) return <div className="alert error">{error}</div>;
  if (!data) return <p className="muted">Đang tải…</p>;
  if (slug && !grade)
    return (
      <div className="alert error">
        Không có lớp / học phần "{slug}" trong khung chương trình. <Link to="/chu-de">Về tổng quan</Link>
      </div>
    );
  return grade ? <GradeDetail key={grade.slug} g={grade} /> : <Home data={data} />;
}
