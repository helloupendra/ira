import { useMemo } from 'react';
import { Link, useLocation, useSearch } from 'wouter';
import { admin, type ActionCounts, type ActionRow, type ToolDetail } from '../api/endpoints';
import { count, humanize, when } from '../lib/format';
import { actionBadge } from '../ui/badges';
import { Icon } from '../ui/icons';
import { Json } from '../ui/Json';
import { Page } from '../ui/Page';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useApi, type ApiState } from '../ui/useApi';
import {
  countFor,
  emptyText,
  FILTERS,
  hrefFor,
  labelFor,
  outcomeLine,
  proposedBy,
  statusFromSearch,
  whoMayConfirm,
} from './actions/text';
import { usePaged, type Paged } from './actions/usePaged';
import './Actions.css';

const LIMIT = 100;

function Filters({
  status,
  counts,
  onPick,
}: {
  status: string;
  counts: ActionCounts | undefined;
  onPick: (status: string) => void;
}) {
  const known = FILTERS.some((f) => f.value === status);
  const chips = known ? FILTERS : [...FILTERS, { value: status, label: labelFor(status) }];
  return (
    <div className="filters" role="group" aria-label="Filter by status">
      {chips.map((chip) => {
        const n = countFor(counts, chip.value);
        return (
          <button
            key={chip.value}
            type="button"
            className="filter"
            aria-pressed={chip.value === status}
            onClick={() => onPick(chip.value)}
          >
            {chip.label}
            {n !== null && (
              <>
                {' '}
                <span className="num">{count(n)}</span>
              </>
            )}
          </button>
        );
      })}
    </div>
  );
}

function ActionItem({
  row,
  tool,
  confirmText,
}: {
  row: ActionRow;
  tool: ToolDetail | undefined;
  confirmText: string;
}) {
  const line = outcomeLine(row);
  const hasResult = row.result !== null && row.result !== undefined;
  return (
    <details className="disclosure action">
      <summary>
        <Icon name="chevronRight" />
        <span className="disclosure-title">{row.summary}</span>
        <span className="action-meta">
          <span className={actionBadge(row.status)}>{row.status}</span>
          <span className="disclosure-meta">{when(row.created_at)}</span>
        </span>
      </summary>
      <div className="disclosure-body">
        <dl className="kv">
          <dt>Tool</dt>
          <dd>
            {humanize(row.tool)} <span className="mono muted">{row.tool}</span>
            {tool && !tool.enabled && <span className="muted"> (switched off)</span>}
          </dd>
          <dt>Proposed by</dt>
          <dd>{proposedBy(row.actor, row.channel)}</dd>
          <dt>Proposed at</dt>
          <dd>{when(row.created_at)}</dd>
          {line && (
            <>
              <dt>{line.label}</dt>
              <dd>{line.text}</dd>
            </>
          )}
          <dt>Who may confirm</dt>
          <dd>{confirmText}</dd>
          {row.conversation_id && (
            <>
              <dt>Conversation</dt>
              <dd>
                <Link href={`/conversations/${row.conversation_id}`}>Open the conversation</Link>
              </dd>
            </>
          )}
        </dl>
        <div className="action-part">
          <h3 className="action-part-title">Parameters</h3>
          <Json value={row.params} />
        </div>
        {hasResult && (
          <div className="action-part">
            <h3 className="action-part-title">{row.status === 'failed' ? 'Result (the error)' : 'Result'}</h3>
            <Json value={row.result} />
          </div>
        )}
      </div>
    </details>
  );
}

function List({ paged, status, tools }: { paged: Paged<ActionRow>; status: string; tools: ApiState<ToolDetail[]> }) {
  const byName = useMemo(() => new Map((tools.data ?? []).map((tool) => [tool.name, tool])), [tools.data]);
  const rows = paged.rows;

  if (rows === undefined) {
    if (paged.error) return <ErrorState error={paged.error} onRetry={paged.reload} needs="admin.read" />;
    return <Loading />;
  }

  function confirmText(name: string): string {
    if (tools.data) return whoMayConfirm(byName.get(name));
    if (tools.error) return 'unknown (the tool list could not be loaded)';
    return 'loading';
  }

  return (
    <>
      {paged.error && (
        <p className="error-line" role="alert">
          Couldn't refresh. {sentenceFor(paged.error)}
        </p>
      )}
      {rows.length === 0 ? (
        <Empty text={emptyText(status)} />
      ) : (
        <div className="action-list" aria-busy={paged.loading || paged.loadingMore || undefined}>
          {rows.map((row) => (
            <ActionItem key={row.id} row={row} tool={byName.get(row.tool)} confirmText={confirmText(row.tool)} />
          ))}
        </div>
      )}
      {paged.hasMore && (
        <div className="action-more">
          {paged.moreError && (
            <p className="error-line" role="alert">
              {sentenceFor(paged.moreError)}
            </p>
          )}
          <button type="button" className="btn btn-small" onClick={paged.loadMore} disabled={paged.loadingMore}>
            {paged.loadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </>
  );
}

export default function Actions() {
  const search = useSearch();
  const [, navigate] = useLocation();
  const status = statusFromSearch(search);

  const paged = usePaged<ActionRow>(
    (cursor, signal) =>
      admin.actionsPage(
        { status: status || null, limit: LIMIT, before: cursor?.before, before_id: cursor?.before_id },
        signal,
      ),
    status,
  );
  const counts = useApi((signal) => admin.actionCounts({}, signal), []);
  const tools = useApi((signal) => admin.tools(signal), []);

  function pick(next: string) {
    if (next !== status) navigate(hrefFor(next));
  }

  // Back to the first page, with the counts and the tool list fresh too.
  function reload() {
    paged.reload();
    counts.reload();
    tools.reload();
  }

  return (
    <Page
      title="Actions"
      subtitle="What Ira proposed, and who decided"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <section className="section">
        <Filters status={status} counts={counts.data} onPick={pick} />
        <List paged={paged} status={status} tools={tools} />
      </section>
    </Page>
  );
}
