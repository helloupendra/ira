import { Link, useLocation } from 'wouter';
import { Page } from '../ui/Page';

export default function NotFound() {
  const [location] = useLocation();
  return (
    <Page title="Not found">
      <section className="section stack">
        <p className="muted">
          There is nothing at <span className="mono">{location}</span>.
        </p>
        <p className="actions-row">
          <Link href="/" className="btn btn-small">
            Go to Today
          </Link>
        </p>
      </section>
    </Page>
  );
}
