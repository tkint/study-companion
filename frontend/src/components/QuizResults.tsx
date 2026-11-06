import styled from "styled-components";
import { api, type QuizResult } from "../api";
import { when } from "../format";
import { href } from "../router";
import { Badge, Card, List, Muted, TextButton } from "../ui";

const Result = styled(Card)`
  display: flex;
  align-items: flex-start;
  gap: 12px;
`;

const Score = styled.span<{ $low?: boolean }>`
  flex: none;
  min-width: 3.4em;
  padding: 6px 8px;
  border-radius: ${({ theme }) => theme.radii.sm};
  text-align: center;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  color: ${({ theme, $low }) => ($low ? theme.colors.dangerText : theme.colors.successText)};
  background: ${({ theme, $low }) => ($low ? theme.colors.dangerSoft : theme.colors.successSoft)};
`;

const Main = styled.div`
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: ${({ theme }) => theme.fontSizes.md};
`;

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
      <h3>Quiz results</h3>
      <List $gap="8px">
        {results.slice(0, limit).map((r) => (
          <Result as="li" key={r.id} $pad="sm">
            <Score $low={r.percent != null && r.percent < 50}>
              {r.percent != null ? `${r.percent}%` : "–"}
            </Score>
            <Main>
              <div>
                <strong>{r.score % 1 ? r.score.toFixed(1) : r.score}/{r.total}</strong>
                {r.topic && <span> · {r.topic}</span>}
                {showCourse && r.course_name && (
                  <> · <a href={href.course(r.course_id)}>{r.course_name}</a></>
                )}
              </div>
              <Muted $small>
                <Badge $tone={r.source === "claude" ? "primary" : "sky"}>{r.source === "claude" ? "Quiz with Claude" : "Flashcards"}</Badge>{" "}
                {when(r.taken_at)}
              </Muted>
              {r.notes && <div>{r.notes}</div>}
            </Main>
            {onDelete && (
              <TextButton $danger onClick={() => remove(r)} aria-label="Delete this result">✕</TextButton>
            )}
          </Result>
        ))}
      </List>
    </>
  );
}
