import { useMemo } from 'react';
import { Link, useLocation, useSearch } from 'wouter';
import { admin, type ActionRow, type ToolDetail } from '../api/endpoints';
import { humanize, when } from '../lib/format';
import { actionBadge } from '../ui/badges';
import { Icon } from '../ui/icons';
import { Json } from '../ui/Json';
import { Page } from '../ui/Page';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useApi, type ApiState } from '../ui/useApi';
import {
  emptyText,
  FILTERS,
  hrefFor,
  labelFor,
  outcomeLine,
  proposedBy,
  statusFromSearch,
  whoMayConfirm,
} from './actions/text';
import { useNow } from './actions/useNow';
import './Actions.css';

const LIMIT = 100;

// The rows come back with the filter they were fetched for, so a list for the
// previous filter is never shown under the new chip while the next one loads.
interface Fetched {
  status: string;
  rows: ActionRow[];
}

function Filters({ status, onPick }: { status: string; onPick: (status: string) => void }) {
  const known = FILTERS.some((f) => f.value === status);
  const chips = known ? FILTERS : [...FILTERS, { value: status, label: labelFor(status) }];
  return (
    <div className="filters" role="group" aria-label="Filter by status">
      {chips.map((chip) => (
        <button
          key={chip.value}
          type="button"
          className="filter"
          aria-pressed={chip.value === status}
          onClick={() => onPick(chip.value)}
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}

function ActionItem({
  row,
  tool,
  confirmText,
  now,
}: {
  row: ActionRow;
  tool: ToolDetail | undefined;
  confirmText: string;
  now: number;
}) {
  const line = outcomeLine(row, now);
  const hasResult = row.result !== null && row.result !== undefined;
  return (
    <details className="disclosure action">
      <summary>
        <Icon name="chevronRight" />
        <span className="disclosure-title">{row.summary}</span>
        <span className="action-meta">
          <span className={actionBadge(row.status)}>{row.status}</span>
          <span className="disclosure-meta">{when(row.created_at, now)}</span>
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
          <dd>{when(row.created_at, now)}</dd>
          {line && (
            <>
              <dt>{line.label}</dt>
              <dd>
                {line.text}
                {line.note && <span className="muted">, {line.note}</span>}
              </dd>
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

function List({
  state,
  status,
  tools,
  now,
}: {
  state: ApiState<Fetched>;
  status: string;
  tools: ApiState<ToolDetail[]>;
  now: number;
}) {
  const byName = useMemo(() => new Map((tools.data ?? []).map((tool) => [tool.name, tool])), [tools.data]);
  const rows = state.data?.status === status ? state.data.rows : undefined;

  if (rows === undefined) {
    if (state.error) return <ErrorState error={state.error} onRetry={state.reload} needs="admin.read" />;
    return <Loading />;
  }

  function confirmText(name: string): string {
    if (tools.data) return whoMayConfirm(byName.get(name));
    if (tools.error) return 'unknown (the tool list could not be loaded)';
    return 'loading';
  }

  return (
    <>
      {state.error && (
        <p className="error-line" role="alert">
          Couldn't refresh. {sentenceFor(state.error)}
        </p>
      )}
      {rows.length === 0 ? (
        <Empty text={emptyText(status)} />
      ) : (
        <div className="action-list" aria-busy={state.loading || undefined}>
          {rows.map((row) => (
            <ActionItem key={row.id} row={row} tool={byName.get(row.tool)} confirmText={confirmText(row.tool)} now={now} />
          ))}
        </div>
      )}
      {rows.length >= LIMIT && <p className="inline-note">The latest {LIMIT} are shown.</p>}
    </>
  );
}

export default function Actions() {
  const search = useSearch();
  const [, navigate] = useLocation();
  const status = statusFromSearch(search);
  const now = useNow();

  const actions = useApi<Fetched>(
    async (signal) => ({ status, rows: await admin.actions({ status: status || null, limit: LIMIT }, signal) }),
    [status],
  );
  const tools = useApi((signal) => admin.tools(signal), []);

  function pick(next: string) {
    if (next !== status) navigate(hrefFor(next));
  }

  function reload() {
    actions.reload();
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
        <Filters status={status} onPick={pick} />
        <List state={actions} status={status} tools={tools} now={now} />
      </section>
    </Page>
  );
}
