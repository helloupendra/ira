import { Link } from 'wouter';
import { admin } from '../api/endpoints';
import { clock, dayDate, humanize } from '../lib/format';
import { actionBadge } from '../ui/badges';
import { Icon } from '../ui/icons';
import { Json } from '../ui/Json';
import { Page } from '../ui/Page';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useApi } from '../ui/useApi';
import {
  actionsHref,
  buildTurns,
  detailsOf,
  expiresLabel,
  idFromParam,
  titleOf,
  whoLabel,
  type CallTurn,
  type MessageAction,
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

// The action a turn proposed, as it stands now; it opens the Actions screen
// on the proposals in that state.
function Proposed({ action }: { action: MessageAction }) {
  const expires = expiresLabel(action);
  return (
    <Link href={actionsHref(action.status)} className="conv-proposed">
      <span className="conv-proposed-text">
        <span className="conv-proposed-label">Proposed:</span> {action.summary}
      </span>
      <span className={actionBadge(action.status)}>{action.status}</span>
      {expires && <span className="turn-time">{expires}</span>}
    </Link>
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
      {turn.action && <Proposed action={turn.action} />}
      {turn.model && (
        <span className="turn-time" title="The model that wrote this answer">
          {turn.model}
        </span>
      )}
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
      {turn.action && <Proposed action={turn.action} />}
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
      {turn.action && <Proposed action={turn.action} />}
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
  const info = useApi((signal) => admin.conversationInfo(id, signal), [id]);
  const state = useApi((signal) => admin.conversation(id, signal), [id]);
  const row = info.data;
  const messages = state.data;
  const gone = info.error?.status === 404 || state.error?.status === 404;

  function reload() {
    info.reload();
    state.reload();
  }

  const title = row && !gone ? titleOf(row) : 'Conversation';
  const subtitle =
    row && !gone ? (
      <span className="conv-head">
        <span className="badge badge-muted">{row.channel}</span>
        <span>{detailsOf(row)}</span>
      </span>
    ) : (
      <span className="mono">{id}</span>
    );

  function body() {
    if (gone) {
      return (
        <div className="error-state" role="alert">
          <p>No such conversation.</p>
          <Link href="/conversations" className="btn btn-small">
            Back to conversations
          </Link>
        </div>
      );
    }
    if (messages === undefined) {
      if (!state.error) return <Loading />;
      return <ErrorState error={state.error} onRetry={reload} needs="admin.read" />;
    }
    const turns = buildTurns(messages);
    return (
      <>
        {state.error && (
          <p className="error-line" role="alert">
            Couldn't refresh. {sentenceFor(state.error)}
          </p>
        )}
        {info.error && (
          <p className="error-line" role="alert">
            Couldn't load the details. {info.error.detail}
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
          <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
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
