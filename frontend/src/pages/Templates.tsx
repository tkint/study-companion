import { useEffect, useRef, useState, type MouseEvent } from "react";
import { request, ApiError } from "../api";
import { Status, useLoad } from "../components/common";
import { when } from "../format";
import { href } from "../router";
import styled from "styled-components";
import { Alert, Badge, Button, Card, Crumbs, DetailsCard, Lead, List, Muted, Pre, Row, Small, Textarea } from "../ui";

const TemplateRow = styled(Card)`
  display: grid;
  gap: 2px;
`;

const Name = styled.span`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  overflow-wrap: anywhere;
`;

const Editor_ = styled.div`
  code {
    padding: 1px 5px;
    border-radius: 4px;
    background: ${({ theme }) => theme.colors.surfaceSunken};
  }
  ${DetailsCard} { margin-top: 12px; }
`;

const TemplateText = styled(Textarea)`
  min-height: 55vh;
  margin: 12px 0 8px;
  font-family: ${({ theme }) => theme.fonts.mono};
  tab-size: 2;
  ${({ theme }) => theme.media.notPhone} { font-size: .9rem; }
`;

const Actions = styled(Row)`
  & > button { flex: 1 1 auto; }
  ${({ theme }) => theme.media.notPhone} { & > button { flex: 0 0 auto; } }
`;

const Codes = styled.p`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: ${({ theme }) => theme.fontSizes.sm};
`;

// Types of /api/prompt/templates (backend: app/prompts/store.py and app/api/prompts.py).
interface PromptTemplate {
  id: string;
  title: string;
  description: string;
  text: string;
  default_text: string;
  edited: boolean;
  updated_at: number | null;
  default_changed: boolean;
}
interface TemplateList {
  templates: PromptTemplate[];
  variables: string[];
  flags: string[];
  tools: string[];
}

const send = (id: string, method: string, text?: string) =>
  request<PromptTemplate>(`/api/prompt/templates/${encodeURIComponent(id)}`, {
    method,
    ...(text !== undefined ? { body: JSON.stringify({ text }) } : {}),
  });

export default function Templates({ id }: { id?: string }) {
  const { data, error, setData } = useLoad(() => request<TemplateList>("/api/prompt/templates"), []);
  if (!data) return <Status error={error} loading />;
  const current = id ? data.templates.find((t) => t.id === id) : undefined;
  const update = (t: PromptTemplate) =>
    setData({ ...data, templates: data.templates.map((x) => (x.id === t.id ? t : x)) });
  if (id && current) return <Editor key={current.id} template={current} list={data} onSaved={update} />;
  return (
    <>
      <h1>Prompt templates</h1>
      <Lead $small>
        Each goal of the prompt builder comes from one of these templates. Edit one to change the
        prompts it builds; reset it to go back to the built-in version.
      </Lead>
      {id && !current && <Alert role="alert">There is no template called “{id}”.</Alert>}
      <List>
        {data.templates.map((t) => (
          <li key={t.id}>
            <TemplateRow as="a" href={href.templates(t.id)} $interactive>
              <Name>
                {t.title}
                {t.edited && <Badge $tone="primary">Edited</Badge>}
                {t.default_changed && <Badge $tone="warning">Built-in updated</Badge>}
              </Name>
              <Muted $small>{t.description}</Muted>
            </TemplateRow>
          </li>
        ))}
      </List>
    </>
  );
}

function Editor({ template, list, onSaved }: {
  template: PromptTemplate;
  list: TemplateList;
  onSaved: (t: PromptTemplate) => void;
}) {
  const [text, setText] = useState(template.text);
  const [problems, setProblems] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const dirty = text !== template.text;

  // Check the text on the server while typing (same rules as saving).
  useEffect(() => {
    const n = ++seq.current;
    const timer = window.setTimeout(() => {
      request<{ problems: string[] }>(`/api/prompt/templates/${encodeURIComponent(template.id)}/check`, {
        method: "POST",
        body: JSON.stringify({ text }),
      })
        .then((r) => n === seq.current && setProblems(r.problems))
        .catch(() => undefined);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [text, template.id]);

  // Warn before leaving the page with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const onLeave = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, [dirty]);

  async function run(action: () => Promise<PromptTemplate>, done: string) {
    setBusy(true);
    setSaveError(null);
    setMessage(null);
    try {
      const t = await action();
      onSaved(t);
      setText(t.text);
      setMessage(done);
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  const save = () => run(() => send(template.id, "PUT", text), "Saved. The prompt builder uses it from now on.");
  const reset = () => {
    if (!window.confirm("Go back to the built-in version of this template? Your edits are lost.")) return;
    void run(() => send(template.id, "DELETE"), "Back to the built-in version.");
  };
  const back = (e: MouseEvent) => {
    if (dirty && !window.confirm("Leave without saving your changes?")) e.preventDefault();
  };

  return (
    <Editor_>
      <Crumbs><a href={href.templates()} onClick={back}>← Prompt templates</a></Crumbs>
      <h1>{template.title}</h1>
      <Lead $small>
        {template.edited
          ? `Your version${template.updated_at ? `, saved ${when(template.updated_at)}` : ""}.`
          : "Built-in version."}
      </Lead>
      {template.default_changed && (
        <Alert $tone="warning">
          An app update changed the built-in version since you edited this one. Compare it below,
          or reset to take the new one.
        </Alert>
      )}

      <TemplateText
        aria-label="Template text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
      />

      {problems.length > 0 && (
        <Alert role="alert"><ul>{problems.map((p) => <li key={p}>{p}</li>)}</ul></Alert>
      )}
      {saveError && problems.length === 0 && <Alert role="alert">{saveError}</Alert>}
      {message && !dirty && <Small $muted role="status">{message}</Small>}

      <Actions>
        <Button $variant="primary" type="button" disabled={busy || !dirty || problems.length > 0} onClick={save}>
          Save
        </Button>
        <Button $variant="outline" type="button" disabled={busy || !dirty} onClick={() => setText(template.text)}>
          Undo changes
        </Button>
        <Button $variant="ghost" type="button" disabled={busy || !template.edited} onClick={reset}>
          Reset to built-in
        </Button>
      </Actions>

      <DetailsCard>
        <summary>How templates work</summary>
        <Small>
          The lines between the two <code>---</code> at the top set the goal’s <code>title</code>,{" "}
          <code>description</code>, <code>order</code> in the list and whether it asks for
          a <code>topic</code> (<code>required</code>, <code>optional</code> or <code>none</code>).
        </Small>
        <Small>Placeholders the builder fills in:</Small>
        <Codes>{list.variables.map((v) => <code key={v}>{`{{${v}}}`}</code>)}</Codes>
        <Small>
          <code>{"{{#name}}…{{/name}}"}</code> keeps its text only when the option is on,{" "}
          <code>{"{{^name}}…{{/name}}"}</code> only when it is off:
        </Small>
        <Codes>{list.flags.map((v) => <code key={v}>{v}</code>)}</Codes>
        <Small>
          Keep <code>{"{{steps}}"}</code>: it lists the tool calls for the chosen courses and period.
          Anything written like a call, <code>name(…)</code>, must be one of the Study Companion tools:
        </Small>
        <Codes>{list.tools.map((v) => <code key={v}>{v}</code>)}</Codes>
      </DetailsCard>

      {template.edited && (
        <DetailsCard>
          <summary>Built-in version</summary>
          <Pre>{template.default_text}</Pre>
          <Row>
            <Button $variant="soft" $size="sm" type="button" onClick={() => setText(template.default_text)}>
              Copy into the editor
            </Button>
          </Row>
        </DetailsCard>
      )}
    </Editor_>
  );
}
