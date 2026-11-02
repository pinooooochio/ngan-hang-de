import type { ParamReport, QType } from "../api";
import QuestionView from "./QuestionView";
import Tex from "./Tex";

interface Props {
  report: ParamReport;
  type: QType;
  busy?: boolean;
  onReroll: () => void;
}

/** Xem trước câu tham số: thống kê bốc số và 3 bản mẫu đã thay số, để người soạn kiểm tra trước khi duyệt. */
export default function ParamPreview({ report, type, busy, onReroll }: Props) {
  const rate = report.tried ? Math.round((100 * report.valid) / report.tried) : 0;
  const reasons = Object.entries(report.reasons).sort((a, b) => b[1] - a[1]);
  return (
    <div className="param-preview">
      <div className="toolbar">
        <b>Câu tham số</b>
        <span className="muted small">
          {report.valid}/{report.tried} lần bốc hợp lệ ({rate}%), {report.distinct} bộ số khác nhau
          {report.domain > 0 && <> trên {report.domain} tổ hợp</>}
        </span>
        <span className="spacer" />
        <button disabled={busy} onClick={onReroll}>
          Bộ số khác
        </button>
      </div>
      {reasons.length > 0 && (
        <details className="small">
          <summary>Lý do bộ số bị loại</summary>
          <ul>
            {reasons.map(([r, n]) => (
              <li key={r}>
                {r}: {n} lần
              </li>
            ))}
          </ul>
        </details>
      )}
      {report.samples.map((s, i) => (
        <div key={i} className="card param-sample">
          <div className="card-head small">
            <b>Bản mẫu {i + 1}</b>
            <span className="muted">
              {Object.entries(s.values).map(([k, v], j) => (
                <span key={k}>
                  {j > 0 && ", "}
                  <Tex source={`$${k} = ${v}$`} inline />
                </span>
              ))}
            </span>
          </div>
          <QuestionView
            type={type}
            stem={s.stem}
            choices={s.choices ?? []}
            shortAnswer={s.short_answer ?? null}
            solution={s.solution ?? ""}
          />
        </div>
      ))}
    </div>
  );
}
