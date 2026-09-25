import { useCallback, useEffect, useState, type FormEvent } from "react"

import { ApiRequestError } from "../api/client"
import {
  createKnowledgeDocument,
  createKnowledgeUrl,
  deleteKnowledgeDocument,
  getKnowledgeDocument,
  getKnowledgeDocuments,
  searchKnowledge,
  type KnowledgeDocument,
  type KnowledgeDocumentDetail,
  type KnowledgeSearchResult,
} from "../api/workspace"
import { ConfirmDialog } from "../components/ConfirmDialog"
import { Icon } from "../components/Icon"

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

export function KnowledgeSurface() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [selected, setSelected] = useState<KnowledgeDocumentDetail | null>(null)
  const [results, setResults] = useState<KnowledgeSearchResult[]>([])
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [form, setForm] = useState({ title: "", source: "", content: "" })
  const [url, setUrl] = useState("")
  const [copying, setCopying] = useState(false)
  const [copied, setCopied] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeDocument | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setDocuments(await getKnowledgeDocuments())
      setLastSyncedAt(new Date().toISOString())
    } catch (err) {
      setError(errorText(err, "NOVA could not load your knowledge base."))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!query.trim()) setResults([])
  }, [query])

  const createText = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.title.trim() || !form.content.trim() || working) return
    setWorking(true)
    setError(null)
    try {
      await createKnowledgeDocument({
        title: form.title.trim(),
        content: form.content,
        source: form.source.trim() || null,
      })
      setForm({ title: "", source: "", content: "" })
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not add that document."))
    } finally {
      setWorking(false)
    }
  }

  const createUrl = async (event: FormEvent) => {
    event.preventDefault()
    if (!url.trim() || working) return
    setWorking(true)
    setError(null)
    try {
      await createKnowledgeUrl(url.trim())
      setUrl("")
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not ingest that URL."))
    } finally {
      setWorking(false)
    }
  }

  const runSearch = async () => {
    if (!query.trim() || searching || working) return
    setSearching(true)
    setError(null)
    try {
      setResults(await searchKnowledge(query.trim()))
    } catch (err) {
      setError(errorText(err, "NOVA could not search the knowledge base."))
    } finally {
      setSearching(false)
    }
  }

  const clearSearch = () => {
    setQuery("")
    setResults([])
  }

  const openDocument = async (id: number) => {
    if (working) return
    setWorking(true)
    setError(null)
    try {
      setSelected(await getKnowledgeDocument(id))
    } catch (err) {
      setError(errorText(err, "NOVA could not open that document."))
    } finally {
      setWorking(false)
    }
  }

  const copySelected = async () => {
    if (!selected || copying) return
    setCopying(true)
    setError(null)
    setCopied(false)
    try {
      await navigator.clipboard.writeText(selected.content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setError("NOVA could not copy that document in this browser.")
    } finally {
      setCopying(false)
    }
  }

  const requestDelete = (document: KnowledgeDocument) => {
    if (working) return
    setDeleteTarget(document)
  }

  const confirmDelete = async () => {
    if (!deleteTarget || working) return

    const documentId = deleteTarget.id
    setWorking(true)
    setError(null)
    try {
      await deleteKnowledgeDocument(documentId)
      if (selected?.id === documentId) setSelected(null)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not delete that document."))
    } finally {
      setWorking(false)
    }
  }

  return (
    <>
    <div className="content-shell resource-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">KNOWLEDGE</div>
          <h1>Give NOVA a private knowledge layer.</h1>
          <p>Store documents or ingest URLs so future retrieval can use your own context alongside the assistant.</p>
        </div>
        <div className="resource-stat"><span>Documents</span><strong>{documents.length}</strong></div>
      </section>

      <section className="resource-two-column">
        <div className="resource-panel">
          <div className="resource-panel-head"><div><div className="section-kicker">DOCUMENT</div><h2>Add written knowledge.</h2></div></div>
          <form className="resource-form" onSubmit={createText}>
            <label className="field"><span>Title</span><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} maxLength={300} required placeholder="Project notes" /></label>
            <label className="field"><span>Source label</span><input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} maxLength={1000} placeholder="Notion, PDF, personal notes…" /></label>
            <label className="field"><span>Content</span><textarea className="large-textarea" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} maxLength={250000} required placeholder="Paste the content NOVA should be able to retrieve later." /></label>
            <button className="primary-action" type="submit" disabled={working}><Icon name="plus" size={16} />{working ? "Adding…" : "Add document"}</button>
          </form>
        </div>

        <div className="resource-panel">
          <div className="resource-panel-head"><div><div className="section-kicker">URL INGESTION</div><h2>Pull in a web source.</h2></div></div>
          <form className="resource-form" onSubmit={createUrl}>
            <label className="field"><span>URL</span><input type="url" value={url} onChange={(e) => setUrl(e.target.value)} maxLength={2048} required placeholder="https://example.com/article" /></label>
            <p className="resource-hint">The backend fetches and chunks the source before storing it in NOVA's knowledge system.</p>
            <button className="secondary-action" type="submit" disabled={working}>Ingest URL</button>
          </form>
        </div>
      </section>

      {error && <div className="resource-error" role="alert">{error}<button type="button" onClick={() => void load()}>Retry</button></div>}

      <section className="resource-panel">
        <div className="resource-panel-head">
          <div><div className="section-kicker">RETRIEVAL</div><h2>Search your knowledge.</h2></div>
          <div className="resource-toolbar-actions">
            <button className="primary-action compact" type="button" disabled={!query.trim() || searching || working} onClick={() => void runSearch()}>
              <Icon name="book" size={15} />{searching ? "Searching…" : "Search"}
            </button>
            {query && <button className="ghost-action compact" type="button" onClick={clearSearch}>Clear</button>}
            <button className="secondary-action compact" type="button" disabled={loading} onClick={() => void load()}><Icon name="activity" size={15} />Refresh</button>
          </div>
        </div>
        <div className="field"><span>Query</span><input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void runSearch() }} placeholder="What does my project plan say about the launch?" aria-label="Search private knowledge" /></div>
        <div className="resource-hint" role="status" aria-live="polite">
          {searching ? "Searching private knowledge…" : lastSyncedAt ? `Knowledge last synced ${formatDate(lastSyncedAt)}` : "Knowledge sync pending"}
        </div>
        {results.length > 0 && (
          <div className="search-result-list">
            {results.map((item) => (
              <button
                className="search-result-row interactive"
                key={`${item.document_id}-${item.chunk_index}`}
                type="button"
                onClick={() => void openDocument(item.document_id)}
              >
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.source || "Private source"} · Chunk {item.chunk_index + 1} · {item.content}</small>
                </span>
                <em>{Math.round(item.similarity * 100)}%</em>
              </button>
            ))}
          </div>
        )}
        {query.trim() && !working && results.length === 0 && (
          <div className="resource-empty inline-empty">
            <span>No knowledge matches found.</span>
          </div>
        )}
      </section>

      <section className="resource-two-column">
        <div className="resource-list">
          {loading ? <div className="resource-loading">Loading documents…</div> : documents.length === 0 ? (
            <div className="resource-empty"><Icon name="book" size={22} /><h3>No documents yet.</h3><p>Add text or ingest a URL to build NOVA's private knowledge layer.</p></div>
          ) : documents.map((doc) => (
            <article className="resource-card compact-card" key={doc.id}>
              <div><div className="resource-card-kicker">DOCUMENT #{doc.id}</div><h3>{doc.title}</h3><p className="resource-muted">{doc.source || "Private source"} · {doc.chunk_count} chunks · {formatDate(doc.updated_at)}</p></div>
              <div className="resource-actions"><button className="secondary-action compact" type="button" disabled={working} onClick={() => void openDocument(doc.id)}>Open</button><button className="icon-action danger" type="button" disabled={working} aria-label={`Delete ${doc.title}`} onClick={() => requestDelete(doc)}><Icon name="trash" size={14} /></button></div>
            </article>
          ))}
        </div>

        {selected ? (
          <article className="resource-panel document-preview">
            <div className="resource-panel-head">
              <div><div className="section-kicker">DOCUMENT #{selected.id}</div><h2>{selected.title}</h2></div>
              <div className="resource-toolbar-actions">
                <button className="secondary-action compact" type="button" disabled={copying} onClick={() => void copySelected()}>
                  {copied ? "Copied" : copying ? "Copying…" : "Copy content"}
                </button>
                <button className="icon-action" type="button" aria-label="Close document" onClick={() => setSelected(null)}>×</button>
              </div>
            </div>
            <p className="resource-muted">{selected.source || "Private source"} · {selected.chunk_count} chunks</p>
            <pre className="document-content">{selected.content}</pre>
          </article>
        ) : (
          <div className="resource-empty document-preview"><Icon name="book" size={22} /><h3>Select a document.</h3><p>Open a stored source to inspect the exact content available to retrieval.</p></div>
        )}
      </section>
    </div>
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete this knowledge document?"
        description={
          deleteTarget
            ? "“" + deleteTarget.title + "” and its stored chunks will be removed from NOVA. This cannot be undone."
            : "This knowledge document will be removed from NOVA. This cannot be undone."
        }
        confirmLabel="Delete document"
        busy={working}
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          if (!working) setDeleteTarget(null)
        }}
      />
    </>
  )
}
