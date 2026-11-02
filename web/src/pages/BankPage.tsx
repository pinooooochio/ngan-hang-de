import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  LEVELS,
  levelLabel,
  TYPES,
  typeLabel,
  type Level,
  type QuestionSummary,
  type Status,
  type TagNode,
  type VariantGroup,
} from "../api";
import TagTree from "../components/TagTree";
import { useAuth } from "../auth";
import Tex from "../components/Tex";

const PAGE = 20;

export default function BankPage() {
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const filters = {
    tag: params.get("the") ?? "",
    level: params.get("muc") ?? "",
    type: params.get("loai") ?? "",
    status: params.get("trangthai") ?? "",
    q: params.get("tim") ?? "",
    source: params.get("nguon") ?? "",
    group: params.get("nhom") ?? "",
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
  const [group, setGroup] = useState<VariantGroup | null>(null);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "trang") next.delete("trang");
    setParams(next);
  };

  const query = {
    tag: filters.tag,
    level: filters.level,
    type: filters.type,
    status: filters.status,
    q: filters.q,
    source: filters.source,
    group: filters.group,
  };

  const selectAll = async () => {
    try {
      setSelected(new Set(await api.questionCodes(query)));
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const load = useCallback(async () => {
    try {
      const [list, tagList, stats] = await Promise.all([
        api.listQuestions({
          ...query,
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

  // Đang lọc theo nhóm biến thể: tải mô tả dạng và câu gốc của nhóm
  useEffect(() => {
    if (!filters.group) return setGroup(null);
    api.variantGroup(filters.group).then(setGroup).catch(() => setGroup(null));
  }, [filters.group, items]);

  const editLabel = async () => {
    if (!group) return;
    const label = window.prompt("Mô tả dạng bài của nhóm (ví dụ: Độ dài vectơ từ toạ độ)", group.label ?? "");
    if (label === null) return;
    try {
      setGroup({ ...group, ...(await api.labelGroup(group.code, label)) });
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const mergeSelected = async () => {
    const label = window.prompt(
      `Gộp ${selected.size} câu thành một nhóm biến thể (các câu cùng dạng, khác số liệu). Mô tả dạng bài (có thể để trống):`,
      "",
    );
    if (label === null) return;
    try {
      const g = await api.mergeGroup([...selected], label || undefined);
      setMessage(`Đã gộp vào nhóm ${g.code} (${g.n} câu).`);
      setSelected(new Set());
      await load();
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const toggle = (code: string) => {
    const next = new Set(selected);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    setSelected(next);
  };

  const remove = async () => {
    if (!window.confirm(`Xoá ${selected.size} câu đã chọn? Không hoàn tác được. Câu đã nằm trong đề sẽ được giữ lại.`)) return;
    try {
      const r = await api.bulkDelete([...selected]);
      setMessage(`Đã xoá ${r.deleted} câu.` + (r.kept.length ? ` Giữ lại ${r.kept.join(", ")} vì đã nằm trong đề.` : ""));
      await load();
      setSelected(new Set());
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const bulk = async (body: { add_tag?: string; set_tag?: string; level?: Level; status?: Status }) => {
    try {
      const r = await api.bulk({ codes: [...selected], ...body });
      setMessage(`Đã cập nhật ${r.updated} câu.`);
      await load();
      setSelected(new Set());
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const approveGroup = async () => {
    try {
      const r = await api.approveGroup(filters.group);
      setMessage(
        `Đã duyệt ${r.approved} câu nháp của nhóm.` +
          (r.skipped.length ? ` Chưa duyệt ${r.skipped.join(", ")} vì còn cảnh báo lúc sinh, cần mở ra xem và sửa.` : ""),
      );
      await load();
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

        {selected.size > 0 && selected.size < total && items.every((q) => selected.has(q.code)) && total > items.length && (
          <div className="alert">
            Đã chọn {selected.size} câu trên trang này.{" "}
            <button className="link" onClick={selectAll}>
              Chọn tất cả {total} câu đang lọc
            </button>
          </div>
        )}
        {selected.size > 0 && selected.size === total && total > items.length && (
          <div className="alert">
            Đã chọn tất cả {total} câu đang lọc (mọi trang).{" "}
            <button className="link" onClick={() => setSelected(new Set())}>
              Bỏ chọn
            </button>
          </div>
        )}
        {selected.size > 0 && (
          <BulkBar
            admin={me.role === "admin"}
            count={selected.size}
            tags={tags}
            onApply={bulk}
            onDelete={remove}
            onMerge={mergeSelected}
            onClear={() => setSelected(new Set())}
          />
        )}

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
          {items.length > 0 && (
            <span className="select-links">
              <button className="link small" onClick={() => setSelected(new Set(items.map((q) => q.code)))}>
                Chọn trang này
              </button>
              {total > items.length && (
                <button className="link small" onClick={selectAll}>
                  Chọn tất cả {total} câu
                </button>
              )}
            </span>
          )}
          {filters.group && (
            <span className="tag">
              Nhóm biến thể {filters.group}
              {group?.label && <> · {group.label}</>}{" "}
              <button className="link" onClick={() => setFilter("nhom", "")}>
                ✕
              </button>
            </span>
          )}
          {group && (
            <button className="link small" onClick={editLabel}>
              {group.label ? "Sửa mô tả dạng" : "Thêm mô tả dạng"}
            </button>
          )}
          {group?.origin_code && (
            <Link className="small" to={`/sinh/bien-the/${encodeURIComponent(group.origin_code)}`}>
              Sinh thêm biến thể
            </Link>
          )}
          {filters.group && me.role === "admin" && items.some((q) => q.status === "draft") && (
            <button className="small" onClick={approveGroup} title="Duyệt mọi câu nháp trong nhóm này">
              Duyệt cả nhóm
            </button>
          )}
          {filters.source && (
            <span className="tag">
              Nguồn: {filters.source.split("|").join(", ")}{" "}
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
              {q.variant_group && (q.n_variants ?? 1) > 1 && !filters.group && (
                <button
                  className="badge variant"
                  title={`${q.variant_label ? q.variant_label + ". " : ""}Các câu cùng dạng, khác số liệu. Mỗi đề chỉ lấy một câu của nhóm.`}
                  onClick={() => setFilter("nhom", q.variant_group!)}
                >
                  Nhóm biến thể · {q.n_variants}
                </button>
              )}
              <span className="tags">
                {q.tags.map((t) => (
                  <span key={t.path} className="tag" onClick={() => setFilter("the", t.path)}>
                    {t.names.join(" › ")}
                  </span>
                ))}
              </span>
            </div>
            {q.check_note && <div className="alert error small">Cảnh báo lúc sinh: {q.check_note}</div>}
            <Link to={`/cau/${encodeURIComponent(q.code)}`} className="card-body">
              <Tex source={q.stem} />
            </Link>
            <div className="card-foot">
              <Link className="small" to={`/sinh/bien-the/${encodeURIComponent(q.code)}`}>
                Sinh biến thể
              </Link>
            </div>
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
  tags,
  onApply,
  onDelete,
  onMerge,
  onClear,
  admin,
}: {
  admin: boolean;
  onMerge: () => void;
  count: number;
  tags: TagNode[];
  onApply: (body: { add_tag?: string; set_tag?: string; level?: Level; status?: Status }) => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  const [tag, setTag] = useState("");
  return (
    <div className="bulkbar">
      <b>Đã chọn {count} câu</b>
      <input list="bulk-tags" placeholder="Thẻ, ví dụ: Lớp 12 / Vectơ" value={tag} onChange={(e) => setTag(e.target.value)} />
      <datalist id="bulk-tags">
        {tags.map((t) => (
          <option key={t.path} value={t.names.join(" / ")} />
        ))}
      </datalist>
      <button disabled={!tag.trim()} onClick={() => onApply({ add_tag: tag })} title="Giữ các thẻ cũ, gắn thêm thẻ này">
        Gắn thêm thẻ
      </button>
      <button disabled={!tag.trim()} onClick={() => onApply({ set_tag: tag })} title="Bỏ mọi thẻ cũ, chỉ để lại thẻ này">
        Đổi thẻ
      </button>
      <select defaultValue="" onChange={(e) => e.target.value && onApply({ level: e.target.value as Level })}>
        <option value="">Đặt mức độ…</option>
        {LEVELS.map((l) => (
          <option key={l.value} value={l.value}>
            {l.label}
          </option>
        ))}
      </select>
      {count > 1 && (
        <button onClick={onMerge} title="Các câu cùng dạng, chỉ khác số liệu: mỗi đề sẽ chỉ lấy một câu của nhóm">
          Gộp thành nhóm biến thể
        </button>
      )}
      {admin && (
        <>
          <button onClick={() => onApply({ status: "approved" })}>Duyệt</button>
          <button onClick={() => onApply({ status: "draft" })}>Chuyển về nháp</button>
          <button className="danger" onClick={onDelete}>
            Xoá
          </button>
        </>
      )}
      <button className="link" onClick={onClear}>
        Bỏ chọn
      </button>
    </div>
  );
}
