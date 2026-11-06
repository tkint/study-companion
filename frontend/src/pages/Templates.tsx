import { useEffect, useRef, useState, type MouseEvent } from "react";
import { request, ApiError } from "../api";
import { Status, useLoad } from "../components/common";
import { when } from "../format";
import { href } from "../router";

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
      <p className="crumbs"><a href={href.prompt()}>Prompt builder</a></p>
      <h1>Prompt templates</h1>
      <p className="muted small">
        Each goal of the prompt builder comes from one of these templates. Edit one to change the
        prompts it builds; reset it to go back to the built-in version.
      </p>
      {id && !current && <p className="alert alert-error" role="alert">There is no template called “{id}”.</p>}
      <ul className="template-list">
        {data.templates.map((t) => (
          <li key={t.id}>
            <a className="template-row" href={href.templates(t.id)}>
              <span className="template-name">
                {t.title}
                {t.edited && <span className="tag ai">Edited</span>}
                {t.default_changed && <span className="tag warn">Built-in updated</span>}
              </span>
              <span className="muted small">{t.description}</span>
            </a>
          </li>
        ))}
      </ul>
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
    <div className="template-editor">
      <p className="crumbs"><a href={href.templates()} onClick={back}>Prompt templates</a></p>
      <h1>{template.title}</h1>
      <p className="muted small">
        {template.edited
          ? `Your version${template.updated_at ? `, saved ${when(template.updated_at)}` : ""}.`
          : "Built-in version."}
      </p>
      {template.default_changed && (
        <p className="banner warn small">
          An app update changed the built-in version since you edited this one. Compare it below,
          or reset to take the new one.
        </p>
      )}

      <textarea
        aria-label="Template text"
        className="template-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
      />

      {problems.length > 0 && (
        <ul className="alert alert-error template-problems" role="alert">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
      {saveError && problems.length === 0 && <p className="alert alert-error" role="alert">{saveError}</p>}
      {message && !dirty && <p className="muted small" role="status">{message}</p>}

      <div className="row template-actions">
        <button className="btn btn-primary" type="button" disabled={busy || !dirty || problems.length > 0} onClick={save}>
          Save
        </button>
        <button className="btn btn-ghost" type="button" disabled={busy || !dirty} onClick={() => setText(template.text)}>
          Undo changes
        </button>
        <button className="btn btn-ghost" type="button" disabled={busy || !template.edited} onClick={reset}>
          Reset to built-in
        </button>
      </div>

      <details className="section">
        <summary>How templates work</summary>
        <p className="small">
          The lines between the two <code>---</code> at the top set the goal’s <code>title</code>,{" "}
          <code>description</code>, <code>order</code> in the list and whether it asks for
          a <code>topic</code> (<code>required</code>, <code>optional</code> or <code>none</code>).
        </p>
        <p className="small">Placeholders the builder fills in:</p>
        <p className="small template-chips">{list.variables.map((v) => <code key={v}>{`{{${v}}}`}</code>)}</p>
        <p className="small">
          <code>{"{{#name}}…{{/name}}"}</code> keeps its text only when the option is on,{" "}
          <code>{"{{^name}}…{{/name}}"}</code> only when it is off:
        </p>
        <p className="small template-chips">{list.flags.map((v) => <code key={v}>{v}</code>)}</p>
        <p className="small">
          Keep <code>{"{{steps}}"}</code>: it lists the tool calls for the chosen courses and period.
          Anything written like a call, <code>name(…)</code>, must be one of the Study Companion tools:
        </p>
        <p className="small template-chips">{list.tools.map((v) => <code key={v}>{v}</code>)}</p>
      </details>

      {template.edited && (
        <details className="section">
          <summary>Built-in version</summary>
          <pre className="prompt-text">{template.default_text}</pre>
          <div className="row">
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setText(template.default_text)}>
              Copy into the editor
            </button>
          </div>
        </details>
      )}
    </div>
  );
}
