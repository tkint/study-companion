import { api, type QuizResult } from "../api";
import { when } from "../format";
import { href } from "../router";

export function QuizResults({ results, onDelete, showCourse = false, limit = 10 }: {
  results: QuizResult[];
  onDelete?: (id: number) => void;
  showCourse?: boolean;
  limit?: number;
}) {
  if (!results.length) return null;
  async function remove(r: QuizResult) {
    if (!window.confirm("Delete this result?")) return;
    await api.deleteResult(r.id);
    onDelete?.(r.id);
  }
  return (
    <>
      <h3 className="sub">Quiz results</h3>
      <ul className="results">
        {results.slice(0, limit).map((r) => (
          <li key={r.id} className="result">
            <span className={`score${r.percent != null && r.percent < 50 ? " low" : ""}`}>
              {r.percent != null ? `${r.percent}%` : "–"}
            </span>
            <div className="result-main">
              <div>
                <strong>{r.score % 1 ? r.score.toFixed(1) : r.score}/{r.total}</strong>
                {r.topic && <span> · {r.topic}</span>}
                {showCourse && r.course_name && (
                  <> · <a href={href.course(r.course_id)}>{r.course_name}</a></>
                )}
              </div>
              <div className="muted small">
                <span className="tag">{r.source === "claude" ? "Quiz with Claude" : "Flashcards"}</span> {when(r.taken_at)}
              </div>
              {r.notes && <div className="small">{r.notes}</div>}
            </div>
            {onDelete && (
              <button className="link danger" onClick={() => remove(r)} aria-label="Delete this result">✕</button>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}
