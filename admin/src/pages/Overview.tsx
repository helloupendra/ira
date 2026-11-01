import type { ReactNode } from 'react';
import { Link } from 'wouter';
import { admin, type ChannelView, type Overview as OverviewData } from '../api/endpoints';
import { costText, count, dayDate, humanize, seconds } from '../lib/format';
import type { Permission } from '../lib/roles';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useApi, type ApiState } from '../ui/useApi';

// Shows the data when there is any, with a quiet line when a refresh failed;
// otherwise the loading or error state for that request alone. A second
// section fed by the same request leaves out the Retry button.
function Body<T>({
  state,
  needs,
  retry = true,
  children,
}: {
  state: ApiState<T>;
  needs: Permission;
  retry?: boolean;
  children: (data: T) => ReactNode;
}) {
  if (state.data === undefined) {
    if (state.error) {
      return <ErrorState error={state.error} onRetry={retry ? state.reload : undefined} needs={needs} />;
    }
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

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="stat">
      <dt className="stat-label">{label}</dt>
      <dd className="stat-value">
        {value}
        {note && <span className="stat-note">{note}</span>}
      </dd>
    </div>
  );
}

// People first (questions, conversations), then the model's work, then what it cost.
function Stats({ data }: { data: OverviewData }) {
  const unknown = data.cost_unknown ?? 0;
  return (
    <dl className="stats">
      <Stat label="Questions" value={count(data.questions)} />
      <Stat label="Conversations" value={count(data.conversations)} />
      <Stat label="Model calls" value={count(data.calls)} />
      <Stat label="Failures" value={count(data.failures)} />
      <Stat
        label="Cost"
        value={costText(data.cost_usd)}
        note={unknown > 0 && data.cost_usd != null ? `+ ${count(unknown)} unknown` : undefined}
      />
      <Stat label="Tokens in / out" value={`${count(data.input_tokens)} / ${count(data.output_tokens)}`} />
      <Stat label="Latency p50 / p95" value={`${seconds(data.latency_p50)} / ${seconds(data.latency_p95)}`} />
    </dl>
  );
}

function ByModel({ data }: { data: OverviewData }) {
  return (
    <section className="section">
      <h2 className="section-title">By model</h2>
      {data.by_model.length === 0 ? (
        <Empty text="No model calls yet today." />
      ) : (
        <div className="table-wrap">
          <table className="table table-stack">
            <thead>
              <tr>
                <th scope="col">Model</th>
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
                  Avg time
                </th>
              </tr>
            </thead>
            <tbody>
              {data.by_model.map((row, i) => (
                <tr key={row.model ?? `none-${i}`}>
                  <td>{row.model ?? <span className="muted">none (no model answered)</span>}</td>
                  <td className="num" data-label="Calls">
                    {count(row.calls)}
                  </td>
                  <td className={row.failures > 0 ? 'num danger' : 'num'} data-label="Failures">
                    {count(row.failures)}
                  </td>
                  <td className="num" data-label="Cost">
                    {costText(row.cost_usd, row.cost_unknown ?? 0)}
                  </td>
                  <td className="num" data-label="Avg time">
                    {seconds(row.avg_seconds)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const STATUS_ORDER = ['pending', 'executing', 'executed', 'failed', 'expired', 'cancelled'];

function badgeFor(status: string): string {
  switch (status) {
    case 'pending':
      return 'badge badge-warn';
    case 'executing':
      return 'badge badge-accent';
    case 'executed':
      return 'badge badge-ok';
    case 'failed':
      return 'badge badge-danger';
    default:
      return 'badge badge-muted';
  }
}

function orderedStatuses(actions: Record<string, number>): [string, number][] {
  const rank = (s: string) => {
    const i = STATUS_ORDER.indexOf(s);
    return i === -1 ? STATUS_ORDER.length : i;
  };
  return Object.entries(actions).sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
}

function ActionsList({ data }: { data: OverviewData }) {
  const rows = orderedStatuses(data.actions);
  if (rows.length === 0) return <Empty text="No actions proposed today." />;
  return (
    <ul className="rows">
      {rows.map(([status, n]) => (
        <li key={status}>
          <Link href={`/actions?status=${encodeURIComponent(status)}`} className="row row-link">
            <span className={badgeFor(status)}>{status}</span>
            <span className="num">{count(n)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

const CHANNEL_LABELS: Record<string, string> = { web: 'Web', http: 'HTTP API', telegram: 'Telegram' };
const CHANNEL_ORDER = ['web', 'http', 'telegram'];

function text(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

// What a channel reports, as label and value: the known fields get a plain
// name; anything else is shown as it came.
function channelFacts(channel: ChannelView): [string, string][] {
  const detail = channel.detail ?? {};
  const facts: [string, string][] = [];
  const used = new Set<string>();
  if (channel.name === 'web') {
    facts.push(['Speech to text', text(detail.stt) ?? 'none']);
    facts.push(['Voice', text(detail.tts) ?? 'browser voice']);
    used.add('stt').add('tts');
  } else if (channel.name === 'http') {
    const host = text(detail.host);
    const port = text(detail.port);
    if (host || port) facts.push(['Address', [host, port].filter(Boolean).join(':')]);
    used.add('host').add('port');
  } else if (channel.name === 'telegram') {
    const paired = detail.paired_chats;
    if (typeof paired === 'number') facts.push(['Paired chats', count(paired)]);
    used.add('paired_chats');
  }
  for (const [key, value] of Object.entries(detail)) {
    if (used.has(key)) continue;
    const shown = text(value);
    if (shown !== null) {
      const label = humanize(key);
      facts.push([label.charAt(0).toUpperCase() + label.slice(1), shown]);
    }
  }
  return facts;
}

function ChannelRow({ channel }: { channel: ChannelView }) {
  const facts = channelFacts(channel);
  return (
    <li className="row row-stack">
      <div className="row-main">
        <span className="row-title">{CHANNEL_LABELS[channel.name] ?? channel.name}</span>
        <span className={channel.enabled ? 'badge badge-ok' : 'badge badge-muted'}>
          {channel.enabled ? 'on' : 'off'}
        </span>
      </div>
      {facts.length > 0 && (
        <dl className="kv kv-small">
          {facts.map(([label, value]) => (
            <div key={label} className="kv-pair">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}

function ChannelsList({ data }: { data: ChannelView[] }) {
  const rank = (name: string) => {
    const i = CHANNEL_ORDER.indexOf(name);
    return i === -1 ? CHANNEL_ORDER.length : i;
  };
  const rows = [...data].sort((a, b) => rank(a.name) - rank(b.name));
  if (rows.length === 0) return <Empty text="No channels reported." />;
  return (
    <ul className="rows">
      {rows.map((channel) => (
        <ChannelRow key={channel.name} channel={channel} />
      ))}
    </ul>
  );
}

export default function Overview() {
  const overview = useApi((signal) => admin.overview(signal), []);
  const channels = useApi((signal) => admin.channels(signal), []);
  const since = overview.data?.since;

  function reload() {
    overview.reload();
    channels.reload();
  }

  return (
    <Page
      title="Today"
      subtitle={
        since !== undefined
          ? `${dayDate(since)}, since 00:00${overview.data?.timezone ? ` (${overview.data.timezone})` : ''}`
          : undefined
      }
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <Body state={overview} needs="admin.read">
        {(data) => (
          <>
            <Stats data={data} />
            <ByModel data={data} />
          </>
        )}
      </Body>
      <div className="columns">
        <section className="section">
          <h2 className="section-title">Actions today</h2>
          <Body state={overview} needs="admin.read" retry={false}>
            {(data) => <ActionsList data={data} />}
          </Body>
        </section>
        <section className="section">
          <h2 className="section-title">Channels</h2>
          <Body state={channels} needs="admin.read">
            {(data) => <ChannelsList data={data} />}
          </Body>
        </section>
      </div>
    </Page>
  );
}
