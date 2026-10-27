import { useEffect, useMemo, useRef, useState } from "react";
import type { TagNode } from "../api";

/** Bỏ dấu và chữ hoa để tìm "ham so" vẫn ra "Hàm số". */
const fold = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();

const ancestors = (path: string) => {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
};

function loadOpen(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch {
    // trình duyệt chặn lưu trữ: coi như chưa mở nhánh nào
  }
  return new Set();
}

interface Props {
  tags: TagNode[];
  selected: string;
  onSelect: (path: string) => void;
  /** Thêm dòng "Tất cả" ở đầu cây (mặc định: khi có `total`). */
  showAll?: boolean;
  /** Tổng số câu, hiện ở dòng "Tất cả". */
  total?: number;
  allLabel?: string;
  showCount?: boolean;
  /** Khoá localStorage để nhớ các nhánh đang mở. */
  storageKey?: string;
  autoFocus?: boolean;
}

/** Cây thẻ Lớp > Chủ đề > Dạng bài thu gọn được, kèm ô tìm thẻ và số câu mỗi nhánh. */
export default function TagTree({
  tags,
  selected,
  onSelect,
  total,
  showAll = total !== undefined,
  allLabel = "Tất cả",
  showCount = true,
  storageKey = "nhd.tagtree.open",
  autoFocus,
}: Props) {
  const [open, setOpen] = useState<Set<string>>(() => loadOpen(storageKey));
  const [query, setQuery] = useState("");

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify([...open]));
    } catch {
      // không lưu được thì thôi
    }
  }, [open, storageKey]);

  // thẻ đang chọn (kể cả mở từ đường dẫn) luôn nằm trong nhánh đang mở
  useEffect(() => {
    const need = ancestors(selected).filter((a) => !open.has(a));
    if (need.length) setOpen(new Set([...open, ...need]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const hasChildren = useMemo(() => {
    const s = new Set<string>();
    tags.forEach((t, i) => {
      if (tags[i + 1] && tags[i + 1].depth > t.depth) s.add(t.path);
    });
    return s;
  }, [tags]);

  const q = fold(query.trim());
  const visible = useMemo(() => {
    if (q) {
      // giữ thẻ khớp, các nhánh cha để biết nó nằm đâu, và cả nhánh con của nó
      const hits = tags.filter((t) => fold(t.name).includes(q)).map((t) => t.path);
      const keep = new Set(hits.flatMap(ancestors));
      return tags.filter((t) => keep.has(t.path) || hits.some((h) => t.path === h || t.path.startsWith(h + "/")));
    }
    return tags.filter((t) => ancestors(t.path).every((a) => open.has(a)));
  }, [tags, q, open]);

  const isOpen = (path: string) => !!q || open.has(path);

  const toggle = (path: string) => {
    const next = new Set(open);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setOpen(next);
  };

  return (
    <div className="tag-tree-box">
      <div className="tag-tree-tools">
        <input
          type="search"
          placeholder="Tìm thẻ…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus={autoFocus}
        />
        <button type="button" className="link small" title="Mở hết" onClick={() => setOpen(new Set(hasChildren))}>
          Mở hết
        </button>
        <button type="button" className="link small" title="Thu gọn" onClick={() => setOpen(new Set())}>
          Thu gọn
        </button>
      </div>
      <ul className="tag-tree">
        {showAll && !q && (
          <li>
            <div className={"tag-row" + (selected === "" ? " active" : "")}>
              <span className="twisty" />
              <button type="button" className="tag-name" onClick={() => onSelect("")}>
                <span>{allLabel}</span>
                {showCount && total !== undefined && <span className="count">{total}</span>}
              </button>
            </div>
          </li>
        )}
        {visible.map((t) => (
          <li key={t.path} style={{ paddingLeft: t.depth * 14 }}>
            <div className={"tag-row" + (selected === t.path ? " active" : "")}>
              {hasChildren.has(t.path) ? (
                <button type="button"
                  className="twisty"
                  aria-label={isOpen(t.path) ? "Thu gọn" : "Mở"}
                  aria-expanded={isOpen(t.path)}
                  onClick={() => toggle(t.path)}
                >
                  {isOpen(t.path) ? "▾" : "▸"}
                </button>
              ) : (
                <span className="twisty" />
              )}
              <button type="button" className="tag-name" onClick={() => onSelect(t.path)} title={t.path}>
                <span>{t.name}</span>
                {showCount && <span className="count">{t.count}</span>}
              </button>
            </div>
          </li>
        ))}
        {q && visible.length === 0 && <li className="muted small">Không có thẻ nào khớp.</li>}
      </ul>
    </div>
  );
}

interface SelectProps {
  tags: TagNode[];
  value: string;
  onChange: (path: string) => void;
  /** Nhãn khi chưa chọn thẻ, ví dụ "Mọi thẻ". */
  placeholder: string;
  /** Có thì dòng đầu cây cho phép bỏ chọn (về placeholder). */
  allowEmpty?: boolean;
  showCount?: boolean;
}

/** Ô chọn thẻ dạng thả xuống: bấm mở cây thẻ thu gọn được, chọn xong tự đóng. */
export function TagSelect({ tags, value, onChange, placeholder, allowEmpty = true, showCount = false }: SelectProps) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const node = tags.find((t) => t.path === value);
  const label = node ? node.names.join(" › ") : placeholder;

  return (
    <div className="tag-select" ref={box}>
      <button type="button" className="tag-select-btn" title={label} onClick={() => setOpen(!open)}>
        <span className={node ? "" : "muted"}>{label}</span>
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="tag-select-pop" onClick={(e) => e.preventDefault()}>
          <TagTree
            tags={tags}
            selected={value}
            showAll={allowEmpty}
            allLabel={placeholder}
            showCount={showCount}
            storageKey="nhd.tagselect.open"
            autoFocus
            onSelect={(p) => {
              onChange(p);
              setOpen(false);
            }}
          />
        </div>
      )}
    </div>
  );
}
