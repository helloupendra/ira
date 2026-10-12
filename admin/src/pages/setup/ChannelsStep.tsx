import { admin, type ChannelView } from '../../api/endpoints';
import { Empty } from '../../ui/states';
import { useApi } from '../../ui/useApi';
import { Body } from './Body';
import { CHANNEL_BLURBS, CHANNEL_LABELS, channelLine, sortChannels, telegramTokenEnv } from './channels';
import { StepNav } from './StepNav';

function ChannelList({ channels }: { channels: ChannelView[] }) {
  const rows = sortChannels(channels);
  if (rows.length === 0) return <Empty text="No channels reported. They are configured under channels in ira.yaml." />;
  return (
    <ul className="rows">
      {rows.map((channel) => {
        const line = channelLine(channel);
        return (
          <li key={channel.name} className="row row-stack">
            <div className="row-main">
              <span className="row-title">{CHANNEL_LABELS[channel.name] ?? channel.name}</span>
              <span className={channel.enabled ? 'badge badge-ok' : 'badge badge-muted'}>
                {channel.enabled ? 'on' : 'off'}
              </span>
            </div>
            {CHANNEL_BLURBS[channel.name] && <span className="row-detail">{CHANNEL_BLURBS[channel.name]}</span>}
            {line && <span className="row-detail">{line}</span>}
          </li>
        );
      })}
    </ul>
  );
}

// Step 5: the three channels in short, with how to pair Telegram and how to
// put the app on a phone.
export function ChannelsStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const channels = useApi((signal) => admin.channels(signal), []);
  const tokenEnv = telegramTokenEnv(channels.data ?? []);
  return (
    <div className="setup-step">
      <div className="setup-intro">
        <h2>Channels</h2>
        <p className="muted">Where people reach Ira. Channels are switched on in ira.yaml; this is how each is used.</p>
      </div>
      <Body state={channels} needs="admin.read">
        {(data) => <ChannelList channels={data} />}
      </Body>
      <div className="setup-howto">
        <h3>Pair Telegram</h3>
        <ol>
          <li>
            Create a bot with @BotFather, put its token in the server's environment as{' '}
            <span className="mono">{tokenEnv}</span>, enable the channel in ira.yaml and restart ira serve.
          </li>
          <li>
            Where the server runs, type <span className="mono">ira telegram pair</span> (add{' '}
            <span className="mono">--user someone@example.com</span> to pair a chat for someone else).
          </li>
          <li>
            Send the printed <span className="mono">/pair CODE</span> to the bot within 10 minutes. That chat then
            acts as that person.
          </li>
        </ol>
      </div>
      <div className="setup-howto">
        <h3>Install the app on a phone</h3>
        <ol>
          <li>Open this server's address on the phone; the Ira app is at /.</li>
          <li>iPhone: Share, then Add to Home Screen. Android: the browser menu, then Install app.</li>
        </ol>
      </div>
      <StepNav onBack={onBack} onNext={onNext} />
    </div>
  );
}
