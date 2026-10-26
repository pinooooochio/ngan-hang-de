import type { TagNode } from "../api";

interface Props {
  tags: TagNode[];
  selected: string;
  total: number;
  onSelect: (path: string) => void;
}

/** Cây thẻ Lớp > Chủ đề > Dạng bài, kèm số câu mỗi nhánh. */
export default function TagTree({ tags, selected, total, onSelect }: Props) {
  return (
    <ul className="tag-tree">
      <li>
        <button className={selected === "" ? "active" : ""} onClick={() => onSelect("")}>
          <span>Tất cả</span>
          <span className="count">{total}</span>
        </button>
      </li>
      {tags.map((t) => (
        <li key={t.path} style={{ paddingLeft: t.depth * 14 }}>
          <button className={selected === t.path ? "active" : ""} onClick={() => onSelect(t.path)} title={t.path}>
            <span>{t.name}</span>
            <span className="count">{t.count}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
