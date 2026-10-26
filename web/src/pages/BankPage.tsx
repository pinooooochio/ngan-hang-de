import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, LEVELS, levelLabel, TYPES, typeLabel, type Level, type QuestionSummary, type Status, type TagNode } from "../api";
import TagTree from "../components/TagTree";
import Tex from "../components/Tex";

const PAGE = 20;

export default function BankPage() {
  const [params, setParams] = useSearchParams();
  const filters = {
    tag: params.get("the") ?? "",
    level: params.get("muc") ?? "",
    type: params.get("loai") ?? "",
    status: params.get("trangthai") ?? "",
    q: params.get("tim") ?? "",
    source: params.get("nguon") ?? "",
    page: Number(params.get("trang") ?? "0"),
  };
  const [items, setItems] = useState<QuestionSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [tags, setTags] = useState<TagNode[]>([]);
  const [bankTotal, setBankTotal] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState(filters.q);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "trang") next.delete("trang");
    setParams(next);
  };

  const load = useCallback(async () => {
    try {
      const [list, tagList, stats] = await Promise.all([
        api.listQuestions({
          tag: filters.tag,
          level: filters.level,
          type: filters.type,
          status: filters.status,
          q: filters.q,
          source: filters.source,
          limit: PAGE,
          offset: filters.page * PAGE,
        }),
        api.tags(),
        api.stats(),
      ]);
      setItems(list.items);
      setTotal(list.total);
      setTags(tagList);
      setBankTotal(stats.total);
      setError("");
    } catch (e) {
      setError(String((e as Error).message));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  useEffect(() => {
    load();
    setSelected(new Set());
  }, [load]);

  const toggle = (code: string) => {
    const next = new Set(selected);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    setSelected(next);
  };

  const bulk = async (body: { add_tag?: string; level?: Level; status?: Status }) => {
    try {
      const r = await api.bulk({ codes: [...selected], ...body });
      setMessage(`Đã cập nhật ${r.updated} câu.`);
      await load();
      setSelected(new Set());
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const pages = Math.ceil(total / PAGE);

  return (
    <div className="bank">
      <aside className="sidebar">
        <h3>Cây thẻ</h3>
        <TagTree tags={tags} selected={filters.tag} total={bankTotal} onSelect={(p) => setFilter("the", p)} />
      </aside>
      <section className="content">
        <div className="filters">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setFilter("tim", search.trim());
            }}
          >
            <input placeholder="Tìm theo nội dung hoặc mã câu" value={search} onChange={(e) => setSearch(e.target.value)} />
          </form>
          <select value={filters.level} onChange={(e) => setFilter("muc", e.target.value)}>
            <option value="">Mọi mức độ</option>
            {LEVELS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
          <select value={filters.type} onChange={(e) => setFilter("loai", e.target.value)}>
            <option value="">Mọi loại câu</option>
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <select value={filters.status} onChange={(e) => setFilter("trangthai", e.target.value)}>
            <option value="">Mọi trạng thái</option>
            <option value="draft">Nháp</option>
            <option value="approved">Đã duyệt</option>
          </select>
        </div>

        {error && <div className="alert error">{error}</div>}
        {message && (
          <div className="alert ok" onClick={() => setMessage("")}>
            {message}
          </div>
        )}

        {selected.size > 0 && <BulkBar count={selected.size} onApply={bulk} onClear={() => setSelected(new Set())} />}

        <div className="result-count">
          {items.length > 0 && (
            <input
              type="checkbox"
              title="Chọn tất cả câu trên trang này"
              checked={items.every((q) => selected.has(q.code))}
              onChange={(e) => setSelected(e.target.checked ? new Set(items.map((q) => q.code)) : new Set())}
            />
          )}{" "}
          {total} câu{filters.tag && <> trong thẻ <code>{filters.tag}</code></>}
          {filters.source && (
            <span className="tag">
              Nguồn: {filters.source}{" "}
              <button className="link" onClick={() => setFilter("nguon", "")}>
                ✕
              </button>
            </span>
          )}
        </div>

        {items.map((q) => (
          <article key={q.code} className={`card ${selected.has(q.code) ? "selected" : ""}`}>
            <div className="card-head">
              <input type="checkbox" checked={selected.has(q.code)} onChange={() => toggle(q.code)} />
              <Link to={`/cau/${encodeURIComponent(q.code)}`} className="code">
                {q.code}
              </Link>
              <span className={`badge level-${q.level ?? "none"}`}>{levelLabel(q.level)}</span>
              <span className="badge">{typeLabel(q.type)}</span>
              {q.status === "draft" && <span className="badge draft">Nháp</span>}
              <span className="tags">
                {q.tags.map((t) => (
                  <span key={t.path} className="tag" onClick={() => setFilter("the", t.path)}>
                    {t.names.join(" › ")}
                  </span>
                ))}
              </span>
            </div>
            <Link to={`/cau/${encodeURIComponent(q.code)}`} className="card-body">
              <Tex source={q.stem} />
            </Link>
          </article>
        ))}
        {items.length === 0 && !error && (
          <div className="empty">
            Chưa có câu nào khớp bộ lọc. <Link to="/cau/moi">Soạn câu mới</Link> hoặc <Link to="/import">import từ file</Link>.
          </div>
        )}

        {pages > 1 && (
          <div className="pager">
            <button disabled={filters.page === 0} onClick={() => setFilter("trang", String(filters.page - 1))}>
              ‹ Trước
            </button>
            <span>
              Trang {filters.page + 1}/{pages}
            </span>
            <button disabled={filters.page + 1 >= pages} onClick={() => setFilter("trang", String(filters.page + 1))}>
              Sau ›
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

function BulkBar({
  count,
  onApply,
  onClear,
}: {
  count: number;
  onApply: (body: { add_tag?: string; level?: Level; status?: Status }) => void;
  onClear: () => void;
}) {
  const [tag, setTag] = useState("");
  return (
    <div className="bulkbar">
      <b>Đã chọn {count} câu</b>
      <input placeholder="Gắn thêm thẻ, ví dụ: Lớp 12 / Vectơ" value={tag} onChange={(e) => setTag(e.target.value)} />
      <button disabled={!tag.trim()} onClick={() => onApply({ add_tag: tag })}>
        Gắn thẻ
      </button>
      <select defaultValue="" onChange={(e) => e.target.value && onApply({ level: e.target.value as Level })}>
        <option value="">Đặt mức độ…</option>
        {LEVELS.map((l) => (
          <option key={l.value} value={l.value}>
            {l.label}
          </option>
        ))}
      </select>
      <button onClick={() => onApply({ status: "approved" })}>Duyệt</button>
      <button onClick={() => onApply({ status: "draft" })}>Chuyển về nháp</button>
      <button className="link" onClick={onClear}>
        Bỏ chọn
      </button>
    </div>
  );
}
