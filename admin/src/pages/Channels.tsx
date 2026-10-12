import { Fragment, useState, type ReactNode } from 'react';
import { Link } from 'wouter';
import {
  admin,
  auth,
  type ChannelView,
  type TelegramChat,
  type TelegramPairing,
  type TelegramView,
} from '../api/endpoints';
import { ago, dayDate, humanize, when } from '../lib/format';
import { roleLabel, whyNot, type Permission } from '../lib/roles';
import { onOffBadge } from '../ui/badges';
import { ConfirmDialog } from '../ui/Dialog';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { useSession } from '../ui/Session';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useToast } from '../ui/toast';
import { useApi, type ApiState } from '../ui/useApi';
import {
  botHandle,
  botUnknown,
  chatName,
  describeAddress,
  extraLines,
  failureText,
  httpUrl,
  pairedCount,
  runningBadge,
  setupReason,
  sortChannels,
  speechToText,
  spokenReplies,
  voiceReplies,
  type Detail,
} from './channels/helpers';
import { PairDialog } from './channels/PairDialog';
import './Channels.css';

// Shows the data when there is any, with a quiet line when a refresh failed;
// otherwise the loading or error state.
function Body<T>({
  state,
  needs,
  children,
}: {
  state: ApiState<T>;
  needs: Permission;
  children: (data: T) => ReactNode;
}) {
  if (state.data === undefined) {
    if (state.error) return <ErrorState error={state.error} onRetry={state.reload} needs={needs} />;
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

// The badge sits beside the heading, not inside it, so the heading reads as
// the channel's name alone.
function Title({ label, enabled }: { label: string; enabled: boolean }) {
  return (
    <div className="channel-title">
      <h2 className="section-title">{label}</h2>
      <span className={onOffBadge(enabled)}>{enabled ? 'on' : 'off'}</span>
    </div>
  );
}

// The fields the console has no sentence for, shown as they came.
function Extras({ detail, used }: { detail: Detail; used: readonly string[] }) {
  return (
    <>
      {extraLines(detail, used).map(([label, value]) => (
        <Fragment key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </Fragment>
      ))}
    </>
  );
}

function Web({ channel, name }: { channel: ChannelView; name: string }) {
  const detail = channel.detail ?? {};
  return (
    <section className="section">
      <Title label="Web" enabled={channel.enabled} />
      <div className="channel-body stack">
        <dl className="kv">
          <dt>Speech to text</dt>
          <dd>{speechToText(detail)}</dd>
          <dt>Spoken replies</dt>
          <dd>{spokenReplies(detail)}</dd>
          <Extras detail={detail} used={['stt', 'tts']} />
        </dl>
        <p>Staff sign in there with the same email and password as here.</p>
        <div className="actions-row">
          <a className="btn btn-small" href="/">
            Open the {name} app
            <Icon name="external" size={16} />
          </a>
        </div>
      </div>
    </section>
  );
}

// The typed address covers these; anything else in detail still gets a line.
const HTTP_KNOWN = ['host', 'port', 'public_url'];

function Http({ channel }: { channel: ChannelView }) {
  const detail = channel.detail ?? {};
  const info = channel.address ? describeAddress(channel.address) : null;
  return (
    <section className="section">
      <Title label="HTTP API" enabled={channel.enabled} />
      <div className="channel-body stack">
        <dl className="kv">
          <dt>{info?.label ?? 'Address'}</dt>
          <dd>
            {info ? (
              <>
                <code className="mono channel-url">{info.url}</code>
                <div className="muted">
                  Bound to <code className="mono">{info.bound}</code>
                  {info.configured && (
                    <>
                      ; ira.yaml says <code className="mono">{info.configured}</code>
                    </>
                  )}
                  .
                </div>
              </>
            ) : (
              <span className="muted">not reported</span>
            )}
          </dd>
          <Extras detail={detail} used={HTTP_KNOWN} />
        </dl>
        <div className="channel-how">
          <h3 className="channel-h">How to use it</h3>
          <ol className="channel-steps">
            <li>
              Create a token under <Link href="/tokens">Tokens &amp; security</Link>.
            </li>
            <li>
              Send it with every request as the header <code className="mono">Authorization: Bearer</code> followed
              by the token.
            </li>
            <li>
              <code className="mono">POST /v1/ask</code> with <code className="mono">{'{"text": "..."}'}</code> to ask
              a question.
            </li>
          </ol>
        </div>
        <div className="actions-row">
          <a className="btn btn-small" href="/v1/docs">
            API docs
            <Icon name="external" size={16} />
          </a>
        </div>
      </div>
    </section>
  );
}

// What the Telegram view already says; the rest of detail still gets a line.
const TELEGRAM_KNOWN = [
  'paired_chats',
  'token_env',
  'token_present',
  'voice_replies',
  'running',
  'error',
  'last_error',
  'last_poll_at',
  'updates',
  'bot_username',
  'bot_link',
];

const DONE = <span className="badge badge-ok channel-done">done</span>;

// The bot, its chats, and the two things that can change here: pairing a
// chat and unpairing one.
function TelegramDetails({ view, detail, reload }: { view: TelegramView; detail: Detail; reload: () => void }) {
  const session = useSession();
  const toast = useToast();
  const me = session.me?.user;
  const canWrite = session.can('admin.write');
  const isOwner = session.can('users');
  const reason = canWrite ? undefined : whyNot(me?.role ?? '', 'admin.write');
  const missing = setupReason(view);
  const voice = voiceReplies(detail);

  const [pairing, setPairing] = useState(false);
  const [started, setStarted] = useState<TelegramPairing | null>(null);
  const [unpairing, setUnpairing] = useState<TelegramChat | null>(null);
  const [unpairBusy, setUnpairBusy] = useState(false);
  const [unpairError, setUnpairError] = useState<string | null>(null);

  function closePair() {
    setPairing(false);
    // The chat may have paired while the code was on screen.
    if (started) reload();
    setStarted(null);
  }

  function askUnpair(chat: TelegramChat) {
    setUnpairError(null);
    setUnpairing(chat);
  }

  async function unpair() {
    if (!unpairing) return;
    setUnpairBusy(true);
    setUnpairError(null);
    try {
      await admin.unpairChat(unpairing.chat_id);
      toast(`${chatName(unpairing)} was unpaired.`);
      setUnpairing(null);
      reload();
    } catch (err) {
      setUnpairError(failureText(err));
    } finally {
      setUnpairBusy(false);
    }
  }

  return (
    <>
      <dl className="kv">
        <dt>Bot token</dt>
        <dd>
          {view.token_present ? 'set' : <span className={view.enabled ? 'warn-text' : undefined}>missing</span>}
          <span className="muted">
            {' '}
            ({view.token_present ? 'from' : 'set'} <code className="mono">{view.token_env}</code>
            {view.token_present ? '' : ' in the environment'})
          </span>
        </dd>
        <dt>Bot</dt>
        <dd>
          {view.bot_username ? (
            <span className="channel-bot">
              <code className="mono">{botHandle(view.bot_username)}</code>
              {view.bot_link && (
                <a className="btn btn-small" href={view.bot_link} target="_blank" rel="noreferrer">
                  Open the bot
                  <Icon name="external" size={16} />
                </a>
              )}
            </span>
          ) : (
            <span className="muted">{botUnknown(view)}</span>
          )}
          {view.bot_error && <div className="danger-text">{view.bot_error}</div>}
        </dd>
        <dt>Status</dt>
        <dd>
          <span className={runningBadge(view)}>{view.running ? 'running' : 'not running'}</span>
          {view.last_poll_at != null && (
            <span className="muted" title={when(view.last_poll_at)}>
              {' '}
              last poll {ago(view.last_poll_at)}
            </span>
          )}
          {view.last_error && <div className="danger-text">{view.last_error}</div>}
        </dd>
        {voice && (
          <>
            <dt>Voice replies</dt>
            <dd>{voice}</dd>
          </>
        )}
        <Extras detail={detail} used={TELEGRAM_KNOWN} />
      </dl>

      <div className="channel-chats">
        <div className="toolbar">
          <h3 className="channel-h">{pairedCount(view.chats.length)}</h3>
          <span className="spacer" />
          <button
            type="button"
            className="btn btn-primary btn-small"
            disabled={!canWrite}
            title={reason}
            onClick={() => setPairing(true)}
          >
            <Icon name="plus" />
            Pair a chat
          </button>
        </div>
        {reason && <p className="inline-note">{reason}</p>}
        {view.chats.length === 0 ? (
          <Empty text="No chats are paired. Pair one and the bot answers it as the account you choose." />
        ) : (
          <ul className="cards">
            {view.chats.map((chat) => (
              <li key={chat.chat_id} className="chat">
                <div className="card-head">
                  <span className="card-title">{chatName(chat)}</span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    disabled={!canWrite}
                    title={reason}
                    onClick={() => askUnpair(chat)}
                  >
                    <Icon name="trash" />
                    Unpair
                  </button>
                </div>
                <div className="card-meta">
                  <span>{chat.email}</span>
                  <span className="badge badge-muted">{roleLabel(chat.role)}</span>
                  <span title={dayDate(chat.paired_at)}>paired {when(chat.paired_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="inline-note">
          On the server, <code className="mono">ira telegram pair</code> (or{' '}
          <code className="mono">ira telegram pair --user someone@example.com</code>) prints the same kind of code.
          Pairing and unpairing are recorded in the change log.
        </p>
      </div>

      {missing && (
        <div className="channel-how">
          <h3 className="channel-h">How to connect it</h3>
          <ol className="channel-steps">
            <li>
              Create a bot with BotFather and put its token in the environment as{' '}
              <code className="mono">{view.token_env}</code>.{view.token_present && DONE}
            </li>
            <li>
              Set <code className="mono">channels.telegram.enabled: true</code> in ira.yaml.{view.enabled && DONE}
            </li>
            <li>
              Restart <code className="mono">ira serve</code>, then pair a chat above.
            </li>
          </ol>
        </div>
      )}

      <PairDialog
        open={pairing}
        view={view}
        isOwner={isOwner}
        me={me}
        started={started}
        onStarted={setStarted}
        onClose={closePair}
      />
      <ConfirmDialog
        open={unpairing !== null}
        title="Unpair chat"
        text={unpairing ? `Unpair ${chatName(unpairing)}? It stops acting as ${unpairing.email} until paired again.` : ''}
        confirmLabel="Unpair"
        danger
        busy={unpairBusy}
        error={unpairError}
        onConfirm={() => void unpair()}
        onClose={() => {
          if (!unpairBusy) setUnpairing(null);
        }}
      />
    </>
  );
}

function Telegram({ channel, telegram }: { channel: ChannelView; telegram: ApiState<TelegramView> }) {
  const detail = channel.detail ?? {};
  return (
    <section className="section">
      <Title label="Telegram" enabled={telegram.data?.enabled ?? channel.enabled} />
      <div className="channel-body stack">
        <Body state={telegram} needs="admin.read">
          {(view) => <TelegramDetails view={view} detail={detail} reload={telegram.reload} />}
        </Body>
      </div>
    </section>
  );
}

// A channel this console has no section for yet: its name and whatever the
// server says about it.
function Other({ channel }: { channel: ChannelView }) {
  const detail = channel.detail ?? {};
  const rows = extraLines(detail, []);
  return (
    <section className="section">
      <Title label={humanize(channel.name)} enabled={channel.enabled} />
      <div className="channel-body stack">
        {rows.length === 0 ? (
          <p className="muted">The server reports nothing more about this channel.</p>
        ) : (
          <dl className="kv">
            <Extras detail={detail} used={[]} />
          </dl>
        )}
      </div>
    </section>
  );
}

function Channel({
  channel,
  name,
  telegram,
}: {
  channel: ChannelView;
  name: string;
  telegram: ApiState<TelegramView>;
}) {
  switch (channel.name) {
    case 'web':
      return <Web channel={channel} name={name} />;
    case 'http':
      return <Http channel={channel} />;
    case 'telegram':
      return <Telegram channel={channel} telegram={telegram} />;
    default:
      return <Other channel={channel} />;
  }
}

function Phone({ name, url }: { name: string; url: string }) {
  return (
    <section className="section">
      <h2 className="section-title">On a phone</h2>
      <div className="channel-body stack">
        <p>
          Open <code className="mono">{url}</code> on the phone and sign in, then add the {name} app to the home
          screen:
        </p>
        <dl className="kv">
          <dt>Android</dt>
          <dd>In Chrome, open the menu and choose "Install app" (or "Add to Home screen").</dd>
          <dt>iPhone</dt>
          <dd>In Safari, tap the share button and choose "Add to Home Screen".</dd>
        </dl>
        <p className="inline-note">
          The microphone works only over HTTPS, except on 127.0.0.1; the deployment guide covers putting HTTPS in
          front.
        </p>
      </div>
    </section>
  );
}

export default function Channels() {
  const channels = useApi((signal) => admin.channels(signal), []);
  const telegram = useApi((signal) => admin.telegram(signal), []);
  const status = useApi((signal) => auth.status(signal), []);
  const name = status.data?.name || 'Ira';
  const origin = typeof window === 'undefined' ? '' : window.location.origin;

  function reload() {
    channels.reload();
    telegram.reload();
  }

  return (
    <Page
      title="Channels"
      subtitle={`Where people talk to ${name}, and how to connect each one`}
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <p className="muted channels-note">
        Channels are set in ira.yaml on the server; only Telegram's paired chats can be changed here.
      </p>
      <Body state={channels} needs="admin.read">
        {(list) =>
          list.length === 0 ? (
            <Empty text="No channels reported." />
          ) : (
            sortChannels(list).map((channel) => (
              <Channel key={channel.name} channel={channel} name={name} telegram={telegram} />
            ))
          )
        }
      </Body>
      {channels.data && <Phone name={name} url={httpUrl(channels.data) ?? origin} />}
    </Page>
  );
}
