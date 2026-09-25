import { useCallback, useEffect, useState } from "react"

import { ApiRequestError } from "../api/client"
import {
  deleteMemory,
  getMemories,
  searchMemories,
  updateMemory,
  type Memory,
  type MemorySearchResult,
} from "../api/workspace"
import { ConfirmDialog } from "../components/ConfirmDialog"
import { Icon } from "../components/Icon"

const categories = ["identity", "goal", "preference", "project", "interest", "context", "personal"] as const
const importance = ["high", "medium", "low"] as const

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

export function MemorySurface() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [results, setResults] = useState<MemorySearchResult[]>([])
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState("")
  const [importanceFilter, setImportanceFilter] = useState("")
  const [loading, setLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null)
  const [editing, setEditing] = useState<Record<number, Memory>>({})
  const [saveState, setSaveState] = useState<Record<number, "saving" | "saved">>({})
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Memory | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getMemories({
        category: category || undefined,
        importance: importanceFilter || undefined,
      })
      setMemories(result)
      setEditing(Object.fromEntries(result.map((memory) => [memory.id, { ...memory }])))
      setLastSyncedAt(new Date().toISOString())
    } catch (err) {
      setError(errorText(err, "NOVA could not load memory."))
    } finally {
      setLoading(false)
    }
  }, [category, importanceFilter])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setResults([])
    setSelectedId(null)
  }, [category, importanceFilter])

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      setSelectedId(null)
    }
  }, [query])

  useEffect(() => {
    if (selectedId === null) return
    document.getElementById(`memory-${selectedId}`)?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    })
  }, [selectedId])

  const runSearch = async () => {
    if (!query.trim() || searching) return
    setSearching(true)
    setError(null)
    try {
      setResults(await searchMemories(query.trim()))
    } catch (err) {
      setError(errorText(err, "NOVA could not search memory."))
    } finally {
      setSearching(false)
    }
  }

  const clearSearch = () => {
    setQuery("")
    setResults([])
    setSelectedId(null)
  }

  const save = async (memory: Memory) => {
    const edit = editing[memory.id]
    if (!edit || busy !== null || !edit.memory.trim()) return
    setBusy(memory.id)
    setSaveState((current) => ({ ...current, [memory.id]: "saving" }))
    setError(null)
    try {
      await updateMemory(memory.id, {
        memory: edit.memory.trim(),
        category: edit.category,
        importance: edit.importance,
      })
      await load()
      if (query.trim()) await runSearch()
      setSaveState((current) => ({ ...current, [memory.id]: "saved" }))
    } catch (err) {
      setSaveState((current) => {
        const nextState = { ...current }
        delete nextState[memory.id]
        return nextState
      })
      setError(errorText(err, "NOVA could not update that memory."))
    } finally {
      setBusy(null)
    }
  }

  const requestDelete = (memory: Memory) => {
    if (busy !== null) return
    setDeleteTarget(memory)
  }

  const confirmDelete = async () => {
    if (!deleteTarget || busy !== null) return

    const memoryId = deleteTarget.id
    setBusy(memoryId)
    setError(null)
    try {
      await deleteMemory(memoryId)
      setDeleteTarget(null)
      await load()
      if (query.trim()) await runSearch()
    } catch (err) {
      setError(errorText(err, "NOVA could not delete that memory."))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
    <div className="content-shell resource-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">MEMORY</div>
          <h1>Keep NOVA's personal context useful.</h1>
          <p>Review stored memories, search semantically, and correct or remove context when it changes.</p>
        </div>
        <div className="resource-stat"><span>Stored</span><strong>{memories.length}</strong></div>
      </section>

      <section className="resource-panel">
        <div className="resource-panel-head">
          <div><div className="section-kicker">SEMANTIC SEARCH</div><h2>Find relevant memories.</h2></div>
          <div className="resource-toolbar-actions">
            <button className="primary-action compact" type="button" disabled={!query.trim() || searching} onClick={() => void runSearch()}><Icon name="brain" size={15} />{searching ? "Searching…" : "Search"}</button>
            {(query || results.length > 0) && <button className="ghost-action compact" type="button" onClick={clearSearch}>Clear</button>}
            <button className="secondary-action compact" type="button" disabled={loading} onClick={() => void load()}><Icon name="activity" size={15} />Refresh</button>
          </div>
        </div>
        <div className="field-grid">
          <label className="field field-span-2"><span>Query</span><input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void runSearch() }} placeholder="What are my current AI engineering goals?" aria-label="Search stored memories" /></label>
          <label className="field"><span>Category</span><select value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All</option>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="field"><span>Importance</span><select value={importanceFilter} onChange={(e) => setImportanceFilter(e.target.value)}><option value="">All</option>{importance.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        </div>
        <div className="resource-hint" role="status" aria-live="polite">
          {searching ? "Searching stored memories…" : lastSyncedAt ? `Memory last synced ${formatDate(lastSyncedAt)}` : "Memory sync pending"}
        </div>
        {results.length > 0 && (
          <div className="search-result-list">
            <div className="resource-card-kicker">SEARCH RESULTS</div>
            {results.map((item) => (
              <button
                className="search-result-row interactive"
                key={item.id}
                type="button"
                onClick={() => setSelectedId(item.id)}
              >
                <span>
                  <strong>{item.memory}</strong>
                  <small>{item.category} · {item.importance} importance</small>
                </span>
                <em>{Math.round(item.similarity * 100)}% match · {Math.round(item.ranking_score * 100)} rank</em>
              </button>
            ))}
          </div>
        )}
        {query.trim() && !searching && results.length === 0 && (
          <div className="resource-empty inline-empty">
            <span>No matching memories found.</span>
          </div>
        )}
      </section>

      {error && <div className="resource-error" role="alert">{error}<button type="button" onClick={() => void load()}>Retry</button></div>}

      <section className="resource-list">
        {loading ? <div className="resource-loading">Loading memory…</div> : memories.length === 0 ? (
          <div className="resource-empty"><Icon name="brain" size={22} /><h3>No stored memories.</h3><p>As NOVA learns stable context from conversations, it will appear here.</p></div>
        ) : memories.map((memory) => {
          const edit = editing[memory.id] ?? memory
          return (
            <article
              className={selectedId === memory.id ? "resource-card memory-card-selected" : "resource-card"}
              key={memory.id}
              id={`memory-${memory.id}`}
            >
              <div className="resource-card-head">
                <div className="resource-card-title-row">
                  <div><div className="resource-card-kicker">MEMORY #{memory.id}</div><h3>{memory.category}</h3></div>
                  <span className={`status-pill importance-${memory.importance}`}>{memory.importance}</span>
                </div>
                <small className="resource-muted">Updated {formatDate(memory.updated_at)}</small>
              </div>
              <div className="resource-card-body">
                <label className="field"><span>Memory</span><textarea value={edit.memory} onChange={(e) => setEditing({ ...editing, [memory.id]: { ...edit, memory: e.target.value } })} maxLength={10000} /></label>
                <div className="field-grid">
                  <label className="field"><span>Category</span><select value={edit.category} onChange={(e) => setEditing({ ...editing, [memory.id]: { ...edit, category: e.target.value as Memory["category"] } })}>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
                  <label className="field"><span>Importance</span><select value={edit.importance} onChange={(e) => setEditing({ ...editing, [memory.id]: { ...edit, importance: e.target.value as Memory["importance"] } })}>{importance.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
                </div>
                <div className="resource-actions">
                  <span className="resource-hint" role="status" aria-live="polite">
                    {saveState[memory.id] === "saving"
                      ? "Saving…"
                      : saveState[memory.id] === "saved"
                        ? "Saved"
                        : ""}
                  </span>
                  <button className="secondary-action compact" type="button" disabled={busy === memory.id} onClick={() => void save(memory)}><Icon name="edit" size={14} />{saveState[memory.id] === "saving" ? "Saving…" : "Save"}</button>
                  <button className="danger-action compact" type="button" disabled={busy === memory.id} onClick={() => requestDelete(memory)}><Icon name="trash" size={14} />Delete</button>
                </div>
              </div>
            </article>
          )
        })}
      </section>
    </div>
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete this memory?"
        description={
          deleteTarget
            ? "This stored memory will be removed from NOVA’s personal context. This cannot be undone."
            : "This stored memory will be removed from NOVA’s personal context. This cannot be undone."
        }
        confirmLabel="Delete memory"
        busy={deleteTarget !== null && busy === deleteTarget.id}
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          if (busy === null) setDeleteTarget(null)
        }}
      />
    </>
  )
}
