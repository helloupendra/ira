import { admin, type ChannelView, type TelegramView } from '../../api/endpoints';
import { Empty } from '../../ui/states';
import { useApi } from '../../ui/useApi';
import { Body } from './Body';
import { CHANNEL_BLURBS, CHANNEL_LABELS, channelLine, httpAddress, localOnly, sortChannels, telegramLine } from './channels';
import { StepNav } from './StepNav';
import { TelegramPair } from './TelegramPair';

function ChannelList({ channels, telegram }: { channels: ChannelView[]; telegram: TelegramView | undefined }) {
  const rows = sortChannels(channels);
  if (rows.length === 0) return <Empty text="No channels reported. They are configured under channels in ira.yaml." />;
  return (
    <ul className="rows">
      {rows.map((channel) => {
        // Telegram's facts come from its own view; the others carry theirs.
        const line = channel.name === 'telegram' ? (telegram ? telegramLine(telegram) : null) : channelLine(channel);
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

// The address the server reports is the one to open; a loopback one gets a
// word on public_url, since a phone cannot reach it.
function InstallHowto({ channels }: { channels: readonly ChannelView[] }) {
  const address = httpAddress(channels);
  return (
    <div className="setup-howto">
      <h3>Install the app on a phone</h3>
      <ol>
        <li>
          {address ? (
            <>
              Open <span className="mono">{address.url}</span> on the phone.
            </>
          ) : (
            "Open this server's address on the phone; the Ira app is at /."
          )}
        </li>
        <li>iPhone: Share, then Add to Home Screen. Android: the browser menu, then Install app.</li>
      </ol>
      {address && localOnly(address) && (
        <p className="inline-note">
          That address only works on this computer. For phones, set channels.http.public_url in ira.yaml (or
          IRA_PUBLIC_URL) to the address they can reach, then restart ira serve.
        </p>
      )}
    </div>
  );
}

// Step 5: the three channels in short, how to pair Telegram (with a code
// for your own chat right here) and how to put the app on a phone.
export function ChannelsStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const channels = useApi((signal) => admin.channels(signal), []);
  const telegram = useApi((signal) => admin.telegram(signal), []);
  return (
    <div className="setup-step">
      <div className="setup-intro">
        <h2>Channels</h2>
        <p className="muted">Where people reach Ira. Channels are switched on in ira.yaml; this is how each is used.</p>
      </div>
      <Body state={channels} needs="admin.read">
        {(data) => <ChannelList channels={data} telegram={telegram.data} />}
      </Body>
      <div className="setup-howto">
        <h3>Pair Telegram</h3>
        <Body state={telegram} needs="admin.read">
          {(view) => <TelegramPair view={view} onRefresh={telegram.reload} />}
        </Body>
      </div>
      <InstallHowto channels={channels.data ?? []} />
      <StepNav onBack={onBack} onNext={onNext} />
    </div>
  );
}
