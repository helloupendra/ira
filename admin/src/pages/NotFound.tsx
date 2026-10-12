import { Link, useLocation } from 'wouter';
import { Page } from '../ui/Page';

export default function NotFound() {
  const [location] = useLocation();
  return (
    <Page title="Not found">
      <p className="muted">
        There is nothing at <span className="mono">{location}</span>.
      </p>
      <p className="actions-row">
        <Link href="/" className="btn btn-ghost">
          Go to Today
        </Link>
      </p>
    </Page>
  );
}
