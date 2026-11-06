import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist/legacy/build/pdf.mjs";
import { api, fileUrl, type FileDetail, type TeacherPage } from "../api";
import { HtmlContent } from "../components/HtmlContent";
import { href } from "../router";

// The legacy build supports older phone browsers (Safari 15+).
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];

export default function FileViewer({ id, course }: { id: number; course?: number }) {
  const [file, setFile] = useState<FileDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setFile(null);
    setError(null);
    api.file(id).then(setFile, (e: Error) => setError(e.message));
  }, [id]);
  const back = course ? href.course(course) : href.dashboard;
  if (file?.page) return <PageViewer file={file} back={back} />;
  if (error) {
    return (
      <div className="viewer">
        <header className="viewer-bar">
          <a className="btn small ghost" href={back} aria-label="Back">←</a>
          <span className="viewer-title">File</span>
        </header>
        <div className="viewer-pages"><p className="alert">Could not open this file: {error}</p></div>
      </div>
    );
  }
  if (!file) return <div className="viewer"><div className="viewer-pages"><p className="loading">Loading…</p></div></div>;
  return <PdfViewer file={file} back={back} />;
}

// A teacher page (Moodle page or book chapter), shown like a reading view.
function PageViewer({ file, back }: { file: FileDetail; back: string }) {
  const [page, setPage] = useState<TeacherPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setPage(null);
    setError(null);
    api.page(file.id).then(setPage, (e: Error) => setError(e.message));
  }, [file.id]);
  const at = page ? page.chapters.findIndex((c) => c.id === page.id) : -1;
  const prev = at > 0 ? page!.chapters[at - 1] : null;
  const next = at >= 0 && at < page!.chapters.length - 1 ? page!.chapters[at + 1] : null;
  const title = page?.title ?? file.title;
  return (
    <div className="viewer page-viewer">
      <header className="viewer-bar">
        <a className="btn small ghost" href={back} aria-label="Back">←</a>
        <span className="viewer-title" title={title}>{title}</span>
        {page && page.chapters.length > 1 && (
          <span className="viewer-page">{at + 1}/{page.chapters.length}</span>
        )}
        <a className="btn small ghost" href={fileUrl(file, true)} aria-label="Download" title="Download">⤓</a>
      </header>
      <div className="viewer-pages">
        {error && <p className="alert">Could not open this page: {error}</p>}
        {!page && !error && <p className="loading">Loading…</p>}
        {page && (
          <article className="page-sheet">
            {page.module && page.chapters.length > 1 && <p className="muted page-kicker">{page.module.name}</p>}
            <h1>{page.title}</h1>
            <HtmlContent html={page.html} />
            {page.attachments.length > 0 && (
              <section className="page-attachments">
                <h2>Attached files</h2>
                <ul>
                  {page.attachments.map((a) => (
                    <li key={a.id}>{a.href ? <a href={a.href}>{a.filename}</a> : a.filename}</li>
                  ))}
                </ul>
              </section>
            )}
            {(prev || next) && (
              <nav className="page-nav" aria-label="Chapters">
                {prev ? <a className="btn ghost" href={href.file(prev.id, page.course_id)}>← {prev.title}</a> : <span />}
                {next && <a className="btn ghost" href={href.file(next.id, page.course_id)}>{next.title} →</a>}
              </nav>
            )}
          </article>
        )}
      </div>
    </div>
  );
}

function PdfViewer({ file, back }: { file: FileDetail; back: string }) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(2); // index into ZOOMS: 1 = fit width
  const [page, setPage] = useState(1);
  const [ratio, setRatio] = useState(1.414);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const task = pdfjs.getDocument({
      url: fileUrl(file),
      cMapUrl: "/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/pdfjs/standard_fonts/",
      wasmUrl: "/pdfjs/wasm/",
      iccUrl: "/pdfjs/iccs/",
    });
    let cancelled = false;
    task.promise.then(
      async (d) => {
        if (cancelled) return;
        const first = await d.getPage(1);
        const vp = first.getViewport({ scale: 1 });
        setRatio(vp.height / vp.width);
        setDoc(d);
      },
      (e: Error) => !cancelled && setError(e.message || "Could not open the PDF"),
    );
    return () => {
      cancelled = true;
      task.destroy();
    };
  }, [file]);

  return (
    <div className="viewer">
      <header className="viewer-bar">
        <a className="btn small ghost" href={back} aria-label="Back">←</a>
        <span className="viewer-title" title={file.filename}>{file.filename}</span>
        {doc && (
          <span className="viewer-page" aria-live="polite">
            {page}/{doc.numPages}
          </span>
        )}
        <button className="btn small ghost" onClick={() => setZoom(Math.max(0, zoom - 1))} disabled={zoom === 0} aria-label="Zoom out">−</button>
        <button className="btn small ghost" onClick={() => setZoom(Math.min(ZOOMS.length - 1, zoom + 1))} disabled={zoom === ZOOMS.length - 1} aria-label="Zoom in">+</button>
        {file && (
          <a className="btn small ghost" href={fileUrl(file, true)} aria-label="Download">⤓</a>
        )}
      </header>
      <div className="viewer-pages" ref={scroller}>
        {error && <p className="alert">Could not open this file: {error}</p>}
        {!doc && !error && <p className="loading">Loading PDF…</p>}
        {doc &&
          Array.from({ length: doc.numPages }, (_, i) => (
            <PdfPage key={i} doc={doc} number={i + 1} zoom={ZOOMS[zoom]} ratio={ratio} root={scroller} onVisible={setPage} />
          ))}
      </div>
    </div>
  );
}

function PdfPage({
  doc,
  number,
  zoom,
  ratio,
  root,
  onVisible,
}: {
  doc: PDFDocumentProxy;
  number: number;
  zoom: number;
  ratio: number;
  root: React.RefObject<HTMLDivElement | null>;
  onVisible: (n: number) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [near, setNear] = useState(number <= 2);
  const [pageRatio, setPageRatio] = useState(ratio);

  // Render only pages near the screen; report the page in the middle of the screen.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const nearObs = new IntersectionObserver(([e]) => e.isIntersecting && setNear(true), {
      root: root.current,
      rootMargin: "150% 0px",
    });
    const midObs = new IntersectionObserver(([e]) => e.isIntersecting && onVisible(number), {
      root: root.current,
      rootMargin: "-50% 0px -50% 0px",
    });
    nearObs.observe(el);
    midObs.observe(el);
    return () => {
      nearObs.disconnect();
      midObs.disconnect();
    };
  }, [number, root, onVisible]);

  useEffect(() => {
    if (!near) return;
    let task: RenderTask | null = null;
    let cancelled = false;
    (async () => {
      const page = await doc.getPage(number);
      const el = box.current;
      const c = canvas.current;
      if (cancelled || !el || !c) return;
      const base = page.getViewport({ scale: 1 });
      setPageRatio(base.height / base.width);
      const cssWidth = el.clientWidth;
      const dpr = Math.min(window.devicePixelRatio || 1, 3);
      const viewport = page.getViewport({ scale: (cssWidth / base.width) * dpr });
      c.width = Math.floor(viewport.width);
      c.height = Math.floor(viewport.height);
      task = page.render({ canvas: c, viewport });
      await task.promise.catch(() => undefined);
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [near, doc, number, zoom]);

  return (
    <div
      ref={box}
      className="pdf-page"
      style={{ width: `calc(${zoom} * min(100%, 900px))`, aspectRatio: `1 / ${pageRatio}` }}
      aria-label={`Page ${number}`}
    >
      <canvas ref={canvas} />
    </div>
  );
}
