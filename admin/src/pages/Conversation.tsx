import { Link } from 'wouter';
import { admin } from '../api/endpoints';
import { clock, dayDate, humanize, when } from '../lib/format';
import { Icon } from '../ui/icons';
import { Json } from '../ui/Json';
import { Page } from '../ui/Page';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useApi } from '../ui/useApi';
import {
  buildTurns,
  countTurns,
  idFromParam,
  titleOf,
  turnsLabel,
  whoLabel,
  type CallTurn,
  type ResultTurn,
  type SaidTurn,
} from './conversations/turns';
import './Conversation.css';

function Time({ at }: { at: number }) {
  const exact = Number.isFinite(at) ? new Date(at * 1000) : null;
  return (
    <time
      className="turn-time"
      dateTime={exact?.toISOString()}
      title={exact ? `${dayDate(at)}, ${clock(at)}` : undefined}
    >
      {clock(at)}
    </time>
  );
}

function Said({ turn }: { turn: SaidTurn }) {
  return (
    <li className={turn.role === 'user' ? 'turn turn-user' : 'turn'}>
      <div className="conv-turn-head">
        <span className="turn-who">{whoLabel(turn.role)}</span>
        <Time at={turn.at} />
      </div>
      {turn.text ? <p className="turn-text">{turn.text}</p> : <p className="turn-text muted">No text.</p>}
    </li>
  );
}

// A tool call and, when one came back, the result it got.
function Call({ turn }: { turn: CallTurn }) {
  return (
    <li className="turn turn-tool">
      <div className="conv-turn-head">
        <span className="turn-who">Called {humanize(turn.name)}</span>
        <Time at={turn.at} />
      </div>
      <Json value={turn.args} compact />
      <span className="turn-who">Returned</span>
      {turn.result ? (
        <Json value={turn.result.content ?? undefined} compact />
      ) : (
        <p className="inline-note">No result was recorded.</p>
      )}
    </li>
  );
}

// A tool result with no call of its own in this conversation.
function Result({ turn }: { turn: ResultTurn }) {
  return (
    <li className="turn turn-tool">
      <div className="conv-turn-head">
        <span className="turn-who">{turn.name ? `${humanize(turn.name)} returned` : 'A tool returned'}</span>
        <Time at={turn.at} />
      </div>
      <Json value={turn.content ?? undefined} compact />
    </li>
  );
}

// A new id starts from a clean state, so an old transcript never lingers
// under a new title while the next one loads.
export default function Conversation({ id }: { id: string }) {
  const decoded = idFromParam(id);
  return <Transcript key={decoded} id={decoded} />;
}

function Transcript({ id }: { id: string }) {
  const state = useApi((signal) => admin.conversation(id, signal), [id]);
  const messages = state.data;
  const first = messages?.[0];
  const last = messages?.[messages.length - 1];

  const title = messages ? titleOf(messages, id) : 'Conversation';
  const subtitle =
    messages && first && last ? (
      `${turnsLabel(countTurns(messages))}, started ${when(first.at)}, last ${when(last.at)}`
    ) : (
      <span className="mono">{id}</span>
    );

  function body() {
    if (messages === undefined) {
      if (!state.error) return <Loading />;
      if (state.error.status === 404) {
        return (
          <div className="error-state" role="alert">
            <p>No such conversation.</p>
            <Link href="/conversations" className="btn btn-small">
              Back to conversations
            </Link>
          </div>
        );
      }
      return <ErrorState error={state.error} onRetry={state.reload} needs="admin.read" />;
    }
    const turns = buildTurns(messages);
    return (
      <>
        {state.error && (
          <p className="error-line" role="alert">
            Couldn't refresh. {sentenceFor(state.error)}
          </p>
        )}
        {turns.length === 0 ? (
          <Empty text="This conversation has no messages." />
        ) : (
          <ol className="transcript conv-transcript">
            {turns.map((turn) =>
              turn.kind === 'said' ? (
                <Said key={turn.key} turn={turn} />
              ) : turn.kind === 'call' ? (
                <Call key={turn.key} turn={turn} />
              ) : (
                <Result key={turn.key} turn={turn} />
              ),
            )}
          </ol>
        )}
      </>
    );
  }

  return (
    <>
      <p className="conv-back">
        <Link href="/conversations">
          <Icon name="chevronRight" size={16} />
          Back to conversations
        </Link>
      </p>
      <Page
        title={title}
        subtitle={subtitle}
        actions={
          <button type="button" className="btn btn-ghost btn-small" onClick={state.reload}>
            <Icon name="refresh" />
            Refresh
          </button>
        }
      >
        <section className="section">{body()}</section>
      </Page>
    </>
  );
}
