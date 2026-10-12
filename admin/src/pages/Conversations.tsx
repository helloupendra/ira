import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { Link, useLocation } from 'wouter';
import { admin, type ConversationRow } from '../api/endpoints';
import { count, when } from '../lib/format';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useApi } from '../ui/useApi';
import { hrefOf, turnsLabel, whoOf } from './conversations/turns';
import './Conversations.css';

const PAGE = 50;

// The pages loaded after the first, kept with the first page they follow: a
// refresh replaces that page, and these are dropped with it.
interface Tail {
  after: ConversationRow[];
  rows: ConversationRow[];
  lastSize: number;
}

function Preview({ row }: { row: ConversationRow }) {
  return row.preview ? <>{row.preview}</> : <span className="mono">{row.id}</span>;
}

// A phone: one card per conversation, the whole card a link.
function Cards({ rows }: { rows: ConversationRow[] }) {
  return (
    <ul className="cards conv-cards">
      {rows.map((row) => (
        <li key={row.id}>
          <Link href={hrefOf(row.id)} className="conv-card">
            <span className="card-title">
              <Preview row={row} />
            </span>
            <span className="card-meta">
              <span>{when(row.last_at)}</span>
              <span>{whoOf(row)}</span>
              <span className="badge badge-muted">{row.channel}</span>
              <span>{turnsLabel(row.turns)}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

// A desktop: a table. The preview is the link; a click anywhere else on the
// row opens it too, unless the person is selecting text or wants a new tab.
function Table({ rows }: { rows: ConversationRow[] }) {
  const [, navigate] = useLocation();

  function open(event: MouseEvent<HTMLTableRowElement>, id: string) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if ((event.target as Element).closest('a')) return;
    if (window.getSelection()?.toString()) return;
    navigate(hrefOf(id));
  }

  return (
    <div className="table-wrap conv-table">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Who</th>
            <th scope="col">Channel</th>
            <th scope="col" className="num">
              Turns
            </th>
            <th scope="col">Preview</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="conv-row" onClick={(event) => open(event, row.id)}>
              <td className="conv-when">{when(row.last_at)}</td>
              <td className="conv-who">{whoOf(row)}</td>
              <td>
                <span className="badge badge-muted">{row.channel}</span>
              </td>
              <td className="num">{count(row.turns)}</td>
              <td className="conv-preview muted">
                <Link href={hrefOf(row.id)} className="conv-open">
                  <Preview row={row} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Conversations() {
  const first = useApi((signal) => admin.conversations({ limit: PAGE }, signal), []);
  const [tail, setTail] = useState<Tail | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<Error | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const base = first.data;
  const extra = tail && base && tail.after === base ? tail : null;
  const rows = base ? (extra ? [...base, ...extra.rows] : base) : [];
  const lastSize = extra ? extra.lastSize : (base?.length ?? 0);
  const hasMore = lastSize >= PAGE;

  async function loadMore() {
    const last = rows[rows.length - 1];
    if (!base || !last || loadingMore) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await admin.conversations({ limit: PAGE, before: last.last_at }, controller.signal);
      if (controller.signal.aborted) return;
      setTail((prev) => {
        const kept = prev && prev.after === base ? prev.rows : [];
        const seen = new Set([...base, ...kept].map((row) => row.id));
        return { after: base, rows: [...kept, ...page.filter((row) => !seen.has(row.id))], lastSize: page.length };
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      setMoreError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  return (
    <Page
      title="Conversations"
      subtitle="Every conversation, on every channel"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={first.reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      {base === undefined ? (
        first.error ? (
          <ErrorState error={first.error} onRetry={first.reload} needs="admin.read" />
        ) : (
          <Loading />
        )
      ) : (
        <div className="conv-list">
          {first.error && (
            <p className="error-line" role="alert">
              Couldn't refresh. {sentenceFor(first.error)}
            </p>
          )}
          {rows.length === 0 ? (
            <Empty text="No conversations yet. They appear here as soon as someone asks Ira something, on the web, over the API or on Telegram." />
          ) : (
            <>
              <Cards rows={rows} />
              <Table rows={rows} />
              {hasMore && (
                <div className="conv-more">
                  {moreError && (
                    <p className="error-line" role="alert">
                      {sentenceFor(moreError)}
                    </p>
                  )}
                  <button type="button" className="btn btn-small" onClick={() => void loadMore()} disabled={loadingMore}>
                    {loadingMore ? 'Loading…' : 'Load more'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Page>
  );
}
