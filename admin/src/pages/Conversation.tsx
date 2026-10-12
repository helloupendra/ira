import { Page } from '../ui/Page';

export default function Conversation({ id }: { id: string }) {
  return (
    <Page title="Conversation" subtitle={<span className="mono">{id}</span>}>
      <p className="muted">Coming in this release.</p>
    </Page>
  );
}
