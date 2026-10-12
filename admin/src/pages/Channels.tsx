import { Fragment, type ReactNode } from 'react';
import { Link } from 'wouter';
import { admin, auth, type ChannelView } from '../api/endpoints';
import { ago, count, humanize, when } from '../lib/format';
import type { Permission } from '../lib/roles';
import { onOffBadge } from '../ui/badges';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { Empty, ErrorState, Loading, sentenceFor } from '../ui/states';
import { useApi, type ApiState } from '../ui/useApi';
import {
  address,
  extraLines,
  flag,
  pairedChats,
  sortChannels,
  speechToText,
  spokenReplies,
  text,
  tokenEnv,
  tokenState,
  voiceReplies,
  type Detail,
} from './channels/helpers';
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

function Http({ channel }: { channel: ChannelView }) {
  const detail = channel.detail ?? {};
  const at = address(detail);
  return (
    <section className="section">
      <Title label="HTTP API" enabled={channel.enabled} />
      <div className="channel-body stack">
        <dl className="kv">
          <dt>Address</dt>
          <dd>
            {at ? <code className="mono">{at}</code> : <span className="muted">not reported</span>}
            <div className="muted">
              This is the address in ira.yaml; behind a reverse proxy, people use the proxy's address instead.
            </div>
          </dd>
          <Extras detail={detail} used={['host', 'port']} />
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

const TELEGRAM_KNOWN = ['paired_chats', 'token_env', 'token_present', 'voice_replies', 'running', 'error', 'last_error', 'last_poll_at', 'updates'];

function Telegram({ channel }: { channel: ChannelView }) {
  const detail = channel.detail ?? {};
  const paired = pairedChats(detail);
  const token = tokenState(detail);
  const voice = voiceReplies(detail);
  const running = flag(detail.running);
  const error = text(detail.error) ?? text(detail.last_error);
  const polledAt = typeof detail.last_poll_at === 'number' ? detail.last_poll_at : null;
  const updates = typeof detail.updates === 'number' ? detail.updates : null;
  const env = tokenEnv(detail);
  return (
    <section className="section">
      <Title label="Telegram" enabled={channel.enabled} />
      <div className="channel-body stack">
        <dl className="kv">
          {paired !== null && (
            <>
              <dt>Paired chats</dt>
              <dd>{paired}</dd>
            </>
          )}
          {token && (
            <>
              <dt>Bot token</dt>
              <dd>
                {token.present ? (
                  'set'
                ) : (
                  <span className={channel.enabled ? 'warn-text' : undefined}>missing</span>
                )}
                {token.env && (
                  <span className="muted">
                    {' '}
                    ({token.present ? 'from' : 'set'} <code className="mono">{token.env}</code>
                    {token.present ? '' : ' in the environment'})
                  </span>
                )}
              </dd>
            </>
          )}
          {voice && (
            <>
              <dt>Voice replies</dt>
              <dd>{voice}</dd>
            </>
          )}
          {running !== null && (
            <>
              <dt>Bot</dt>
              <dd>
                {running ? 'running' : 'not running'}
                {polledAt !== null && (
                  <span className="muted" title={when(polledAt)}>
                    , last checked for messages {ago(polledAt)}
                  </span>
                )}
              </dd>
            </>
          )}
          {updates !== null && (
            <>
              <dt>Messages received</dt>
              <dd>{count(updates)}</dd>
            </>
          )}
          {error && (
            <>
              <dt>Error</dt>
              <dd className="danger-text">{error}</dd>
            </>
          )}
          <Extras detail={detail} used={TELEGRAM_KNOWN} />
        </dl>
        <div className="channel-how">
          <h3 className="channel-h">How to pair a chat</h3>
          <ol className="channel-steps">
            <li>
              Create a bot with BotFather and put its token in the environment as{' '}
              <code className="mono">{env}</code>.
            </li>
            <li>
              Set <code className="mono">channels.telegram.enabled: true</code> in ira.yaml and restart{' '}
              <code className="mono">ira serve</code>.
            </li>
            <li>
              Run <code className="mono">ira telegram pair</code> on the server (or{' '}
              <code className="mono">ira telegram pair --user someone@example.com</code> to pair a chat for someone
              else) and send the printed <code className="mono">/pair CODE</code> to the bot within 10 minutes.
            </li>
          </ol>
        </div>
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

function Channel({ channel, name }: { channel: ChannelView; name: string }) {
  switch (channel.name) {
    case 'web':
      return <Web channel={channel} name={name} />;
    case 'http':
      return <Http channel={channel} />;
    case 'telegram':
      return <Telegram channel={channel} />;
    default:
      return <Other channel={channel} />;
  }
}

function Phone({ name, origin }: { name: string; origin: string }) {
  return (
    <section className="section">
      <h2 className="section-title">On a phone</h2>
      <div className="channel-body stack">
        <p>
          Open <code className="mono">{origin}</code> on the phone and sign in, then add the {name} app to the home
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
  const status = useApi((signal) => auth.status(signal), []);
  const name = status.data?.name || 'Ira';
  const origin = typeof window === 'undefined' ? '' : window.location.origin;

  return (
    <Page
      title="Channels"
      subtitle={`Where people talk to ${name}, and how to connect each one`}
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={channels.reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <p className="muted channels-note">Nothing here is editable: channels are set in ira.yaml on the server.</p>
      <Body state={channels} needs="admin.read">
        {(list) =>
          list.length === 0 ? (
            <Empty text="No channels reported." />
          ) : (
            sortChannels(list).map((channel) => <Channel key={channel.name} channel={channel} name={name} />)
          )
        }
      </Body>
      <Phone name={name} origin={origin} />
    </Page>
  );
}
