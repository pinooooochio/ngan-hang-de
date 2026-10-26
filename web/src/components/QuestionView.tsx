import type { ChoiceData, QType } from "../api";
import Tex from "./Tex";

interface Props {
  type: QType;
  stem: string;
  choices: ChoiceData[];
  shortAnswer?: string | null;
  solution?: string;
  showAnswer?: boolean;
}

/** Hiển thị một câu hỏi: đề, lựa chọn, đáp án và lời giải. */
export default function QuestionView({ type, stem, choices, shortAnswer, solution, showAnswer = true }: Props) {
  const longest = Math.max(0, ...choices.map((c) => c.content.length));
  const cols = longest < 18 ? 4 : longest < 45 ? 2 : 1;
  return (
    <div className="question">
      <Tex source={stem} />
      {type === "mcq" && (
        <div className={`choices cols-${cols}`}>
          {choices.map((c, i) => (
            <div key={i} className={`choice ${showAnswer && c.correct ? "correct" : ""}`}>
              <span className="label">{"ABCD"[i]}.</span>
              <Tex source={c.content} inline />
              {c.pinned && <span className="pin" title="Giữ cố định khi đảo">ghim</span>}
            </div>
          ))}
        </div>
      )}
      {type === "tf" && (
        <div className="statements">
          {choices.map((c, i) => (
            <div key={i} className="statement">
              <span className="label">{"abcd"[i]})</span>
              <Tex source={c.content} inline />
              {showAnswer && <span className={`tf ${c.correct ? "yes" : "no"}`}>{c.correct ? "Đúng" : "Sai"}</span>}
            </div>
          ))}
        </div>
      )}
      {type === "short" && showAnswer && (
        <div className="short-answer">
          Đáp án: <b>{shortAnswer}</b>
        </div>
      )}
      {showAnswer && solution && (
        <div className="solution">
          <span className="solution-title">Lời giải.</span>
          <Tex source={solution} />
        </div>
      )}
    </div>
  );
}
