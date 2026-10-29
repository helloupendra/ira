import { useState, type ReactNode } from 'react';
import { useLocation, useSearch } from 'wouter';
import { admin, type AuditRow, type CallRow, type ChangeRow, type CostDay } from '../api/endpoints';
import { clock, costText, count, dayDate, humanize, seconds, when } from '../lib/format';
import { outcomeBadge } from '../ui/badges';
import { Icon } from '../ui/icons';
import { Json } from '../ui/Json';
import { Page } from '../ui/Page';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useApi, type ApiState } from '../ui/useApi';
import {
  byDayDesc,
  changeWords,
  dayEpoch,
  hrefFor,
  okLabel,
  totals,
  triedLine,
  viaLine,
  VIEWS,
  viewFromSearch,
  type View,
} from './audit/text';
import { usePaged, type Paged } from './audit/usePaged';
import './Audit.css';

const CHANGES_PAGE = 100;
const AUDIT_PAGE = 100;
const COST_DAYS = 30;
const CALLS_PAGE = 50;

// The data when there is any, with a quiet line when a refresh failed;
// otherwise the loading or error state for that request alone.
function Body<T>({ state, children }: { state: ApiState<T>; children: (data: T) => ReactNode }) {
  if (state.data === undefined) {
    if (state.error) return <ErrorState error={state.error} onRetry={state.reload} needs="admin.read" />;
    return <Loading />;
  }
  return (
    <>
      {state.error && (
        <p className="error-line" role="alert">
          Couldn't refresh. {sentenceFor(state.error)}
        </p>
      )}
      {children(state.data)}
    </>
  );
}

function LoadMore<T>({ paged }: { paged: Paged<T> }) {
  if (!paged.hasMore) return null;
  return (
    <div className="more">
      {paged.moreError && (
        <p className="error-line" role="alert">
          {sentenceFor(paged.moreError)}
        </p>
      )}
      <button type="button" className="btn btn-small" onClick={paged.loadMore} disabled={paged.loadingMore}>
        {paged.loadingMore ? 'Loading…' : 'Load more'}
      </button>
    </div>
  );
}

function Filters({ view, onPick }: { view: View; onPick: (view: View) => void }) {
  return (
    <div className="filters" role="group" aria-label="View">
      {VIEWS.map((chip) => (
        <button
          key={chip.value}
          type="button"
          className="filter"
          aria-pressed={chip.value === view}
          onClick={() => onPick(chip.value)}
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}

// Changes: everything done from the console, with the value before and after.

function hasValue(value: unknown): boolean {
  return value !== null && value !== undefined;
}

function Change({ row }: { row: ChangeRow }) {
  return (
    <details className="disclosure change">
      <summary>
        <Icon name="chevronRight" />
        <span className="change-main">
          <span className="change-line">
            <span className="change-what">{changeWords(row.what)}</span>
            {row.target && <span className="mono">{row.target}</span>}
          </span>
          <span className="change-who">{viaLine(row.actor, row.channel)}</span>
        </span>
        <span className="disclosure-meta">{when(row.at)}</span>
      </summary>
      <div className="disclosure-body">
        <dl className="kv">
          <dt>Event</dt>
          <dd>
            <span className="mono">{row.what}</span>
          </dd>
          <dt>At</dt>
          <dd>
            {dayDate(row.at)}, {clock(row.at)}
          </dd>
        </dl>
        {hasValue(row.before) && (
          <div className="change-part">
            <h3 className="change-part-title">Before</h3>
            <Json value={row.before} compact />
          </div>
        )}
        {hasValue(row.after) && (
          <div className="change-part">
            <h3 className="change-part-title">After</h3>
            <Json value={row.after} compact />
          </div>
        )}
      </div>
    </details>
  );
}

function Changes({ tick }: { tick: number }) {
  const paged = usePaged<ChangeRow>(
    (beforeId, signal) => admin.changesPage({ limit: CHANGES_PAGE, before_id: beforeId }, signal),
    [tick],
  );
  return (
    <Body state={paged.first}>
      {() =>
        paged.rows.length === 0 ? (
          <Empty text="No changes yet. Everything done from the console appears here: who, what, and the value before and after." />
        ) : (
          <>
            <div className="change-list" aria-busy={paged.first.loading || undefined}>
              {paged.rows.map((row) => (
                <Change key={row.id} row={row} />
              ))}
            </div>
            <LoadMore paged={paged} />
          </>
        )
      }
    </Body>
  );
}

// Actions: the action audit log, one event per row.

function AuditCards({ rows }: { rows: AuditRow[] }) {
  return (
    <ul className="cards audit-cards">
      {rows.map((row) => (
        <li key={row.id}>
          <div className="card-head">
            <span className="card-title">{row.tool ? humanize(row.tool) : <span className="muted">no tool</span>}</span>
            <span className={outcomeBadge(row.outcome)}>{row.outcome}</span>
          </div>
          {row.detail && <p className="audit-card-detail">{row.detail}</p>}
          <div className="card-meta audit-card-meta">
            <span>{when(row.at)}</span>
            <span>{viaLine(row.actor, row.channel)}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function AuditTable({ rows }: { rows: AuditRow[] }) {
  return (
    <div className="table-wrap audit-table">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Outcome</th>
            <th scope="col">Tool</th>
            <th scope="col">Who</th>
            <th scope="col">Channel</th>
            <th scope="col">Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="audit-when">{when(row.at)}</td>
              <td>
                <span className={outcomeBadge(row.outcome)}>{row.outcome}</span>
              </td>
              <td>{row.tool ? humanize(row.tool) : <span className="muted">none</span>}</td>
              <td>{row.actor ?? <span className="muted">not recorded</span>}</td>
              <td>{row.channel ? <span className="badge badge-muted">{row.channel}</span> : <span className="muted">none</span>}</td>
              <td className="audit-detail">{row.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ActionEvents({ tick }: { tick: number }) {
  const paged = usePaged<AuditRow>(
    (beforeId, signal) => admin.auditPage({ limit: AUDIT_PAGE, before_id: beforeId }, signal),
    [tick],
  );
  return (
    <Body state={paged.first}>
      {() =>
        paged.rows.length === 0 ? (
          <Empty text="No action events yet." />
        ) : (
          <div aria-busy={paged.first.loading || undefined}>
            <AuditCards rows={paged.rows} />
            <AuditTable rows={paged.rows} />
            <LoadMore paged={paged} />
          </div>
        )
      }
    </Body>
  );
}

// Cost: the last 30 days, by day, and the model calls behind them.

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <dt className="stat-label">{label}</dt>
      <dd className="stat-value">{value}</dd>
    </div>
  );
}

function Day({ day }: { day: string }) {
  const epoch = dayEpoch(day);
  return <>{epoch === null ? day : dayDate(epoch)}</>;
}

function CostDays({ rows }: { rows: CostDay[] }) {
  const sum = totals(rows);
  return (
    <>
      <h2 className="section-title">Last {COST_DAYS} days</h2>
      <dl className="stats cost-stats">
        <Stat label="Calls" value={count(sum.calls)} />
        <Stat label="Failures" value={count(sum.failures)} />
        <Stat label="Cost" value={costText(sum.cost_usd, sum.cost_unknown)} />
        <Stat label="Tokens in / out" value={`${count(sum.input_tokens)} / ${count(sum.output_tokens)}`} />
      </dl>
      <p className="inline-note cost-note">Cost is in US dollars, as configured in ira.yaml's price table.</p>
      <section className="section">
        <h2 className="section-title">By day</h2>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Day</th>
                <th scope="col" className="num">
                  Calls
                </th>
                <th scope="col" className="num">
                  Failures
                </th>
                <th scope="col" className="num">
                  Cost
                </th>
                <th scope="col" className="num">
                  Tokens in
                </th>
                <th scope="col" className="num">
                  Tokens out
                </th>
              </tr>
            </thead>
            <tbody>
              {byDayDesc(rows).map((row) => (
                <tr key={row.day}>
                  <td className="cost-day">
                    <Day day={row.day} />
                  </td>
                  <td className="num">{count(row.calls)}</td>
                  <td className={row.failures > 0 ? 'num danger' : 'num'}>{count(row.failures)}</td>
                  <td className="num">{costText(row.cost_usd, row.cost_unknown ?? 0)}</td>
                  <td className="num">{count(row.input_tokens)}</td>
                  <td className="num">{count(row.output_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function CallsTable({ rows }: { rows: CallRow[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Model</th>
            <th scope="col">Purpose</th>
            <th scope="col">Tier</th>
            <th scope="col">OK</th>
            <th scope="col" className="num">
              Time
            </th>
            <th scope="col" className="num">
              Tokens in / out
            </th>
            <th scope="col" className="num">
              Cost
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const tried = triedLine(row);
            return (
              <tr key={row.id}>
                <td className="call-when">{when(row.at)}</td>
                <td>
                  <span className="call-model">
                    {row.model ? <span className="mono">{row.model}</span> : <span className="muted">none</span>}
                    {tried && <span className="muted call-tried">{tried}</span>}
                  </span>
                </td>
                <td>{humanize(row.purpose)}</td>
                <td>{row.tier}</td>
                <td>
                  <span className={row.ok ? 'badge badge-ok' : 'badge badge-danger'}>{okLabel(row)}</span>
                </td>
                <td className="num">{seconds(row.seconds)}</td>
                <td className="num">
                  {count(row.input_tokens)} / {count(row.output_tokens)}
                </td>
                <td className="num">{costText(row.cost_usd)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Cost({ tick }: { tick: number }) {
  const costs = useApi((signal) => admin.costs({ days: COST_DAYS }, signal), [tick]);
  const calls = usePaged<CallRow>(
    (beforeId, signal) => admin.callsPage({ limit: CALLS_PAGE, before_id: beforeId }, signal),
    [tick],
  );
  return (
    <>
      <Body state={costs}>
        {(rows) =>
          rows.length === 0 ? <Empty text="No cost yet: nothing has been asked." /> : <CostDays rows={rows} />
        }
      </Body>
      <section className="section">
        <h2 className="section-title">Recent model calls</h2>
        <Body state={calls.first}>
          {() =>
            calls.rows.length === 0 ? (
              <Empty text="No model calls yet." />
            ) : (
              <div aria-busy={calls.first.loading || undefined}>
                <CallsTable rows={calls.rows} />
                <LoadMore paged={calls} />
              </div>
            )
          }
        </Body>
      </section>
    </>
  );
}

export default function Audit() {
  const search = useSearch();
  const [, navigate] = useLocation();
  const view = viewFromSearch(search);
  // Refresh bumps this; every request on the screen lists it as a dependency.
  const [tick, setTick] = useState(0);

  function pick(next: View) {
    if (next !== view) navigate(hrefFor(next));
  }

  return (
    <Page
      title="Audit & cost"
      subtitle="Who did what, and what it cost"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setTick((t) => t + 1)}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <section className="section">
        <Filters view={view} onPick={pick} />
        {view === 'changes' && <Changes tick={tick} />}
        {view === 'actions' && <ActionEvents tick={tick} />}
        {view === 'cost' && <Cost tick={tick} />}
      </section>
    </Page>
  );
}
