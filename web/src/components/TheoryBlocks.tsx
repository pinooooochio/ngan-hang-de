import { Link } from "react-router-dom";
import { slugify, type TheoryBlock } from "../api";
import QuestionView from "./QuestionView";
import Tex from "./Tex";

interface Props {
  blocks: TheoryBlock[];
  /** Hiện trạng thái nháp / mã khối (người soạn). */
  staff?: boolean;
  /** Dòng của khối trong bài soạn (khi xem trước), bấm để nhảy tới. */
  onLine?: (line: number) => void;
}

/** Một khối lý thuyết: khung màu theo loại, tiêu đề, nội dung; ví dụ từ ngân hàng hiện cả câu và lời giải. */
export function TheoryBlockView({ block, staff, onLine }: { block: TheoryBlock } & Omit<Props, "blocks">) {
  const q = block.question;
  const shown = q?.sample ?? q;
  return (
    <div className={`theory-block kind-${block.kind} ${block.status === "draft" ? "is-draft" : ""}`}>
      {block.kind !== "doan" && (
        <div className="theory-block-head">
          <b>{block.kind_name}</b>
          {block.title && (
            <span className="theory-title">
              <Tex source={block.title} inline />
            </span>
          )}
          {block.ref && (
            <span className="muted small">
              (câu{" "}
              {staff ? <Link to={`/cau/${encodeURIComponent(block.ref)}`}>{block.ref}</Link> : block.ref} trong ngân hàng)
            </span>
          )}
          <span className="spacer" />
          {staff && block.status === "draft" && <span className="badge draft">Nháp</span>}
          {onLine && block.line !== undefined && (
            <button className="link small" onClick={() => onLine(block.line!)}>
              dòng {block.line}
            </button>
          )}
        </div>
      )}
      {block.ref ? (
        shown ? (
          <QuestionView
            type={q!.type}
            stem={shown.stem}
            choices={shown.choices ?? []}
            shortAnswer={shown.short_answer ?? null}
            solution={shown.solution ?? ""}
          />
        ) : (
          <div className="alert error">Không có câu {block.ref} trong ngân hàng.</div>
        )
      ) : (
        <Tex source={block.content} />
      )}
      {block.kind === "doan" && staff && block.status === "draft" && <span className="badge draft">Nháp</span>}
    </div>
  );
}

/** Các khối của một chủ đề theo thứ tự, chèn tiêu đề dạng bài mỗi khi đổi dạng. */
export default function TheoryBlocks({ blocks, staff, onLine }: Props) {
  const out: React.ReactNode[] = [];
  let dang: string | null | undefined = undefined;
  blocks.forEach((b, i) => {
    if (b.dang !== dang) {
      dang = b.dang;
      if (b.dang || i > 0)
        out.push(
          <h3 key={`h${i}`} className="theory-dang" id={b.dang ? `dang-${slugify(b.dang)}` : undefined}>
            {b.dang ? `Dạng: ${b.dang}` : "Kiến thức chung"}
          </h3>,
        );
    }
    out.push(<TheoryBlockView key={b.code ?? i} block={b} staff={staff} onLine={onLine} />);
  });
  return <div className="theory-blocks">{out}</div>;
}
