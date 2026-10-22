import { useState } from 'react';
import { Link } from 'wouter';
import { admin, type ReportRow } from '../api/endpoints';
import { when } from '../lib/format';
import { Icon } from '../ui/icons';
import { Page } from '../ui/Page';
import { useSession } from '../ui/Session';
import { Empty, ErrorState, Loading } from '../ui/states';
import { useToast } from '../ui/toast';
import { useApi } from '../ui/useApi';
import './Reports.css';

const REASONS: Record<ReportRow['reason'], string> = {
  wrong: 'Wrong',
  harmful: 'Harmful or dangerous',
  offensive: 'Offensive',
  private: 'Showed something private',
  other: 'Something else',
};

/** Answers people reported from the Ira app, the Mac app or the phone. */
export default function Reports() {
  const session = useSession();
  const toast = useToast();
  const canClose = session.can('admin.write');
  const [showAll, setShowAll] = useState(false);
  const reports = useApi((signal) => admin.reports(showAll ? {} : { status: 'open' }, signal), [showAll]);

  async function close(row: ReportRow) {
    try {
      await admin.closeReport(row.id);
      toast('Marked as dealt with');
      reports.reload();
    } catch {
      toast('Could not close it. Try again.');
    }
  }

  return (
    <Page
      title="Reported answers"
      subtitle="Answers people flagged as wrong, harmful, offensive or private"
      actions={
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setShowAll((all) => !all)}>
          {showAll ? 'Only open ones' : 'Show closed too'}
        </button>
      }
    >
      {reports.data === undefined ? (
        reports.error ? (
          <ErrorState error={reports.error} onRetry={reports.reload} needs="admin.read" />
        ) : (
          <Loading />
        )
      ) : reports.data.length === 0 ? (
        <Empty text={showAll ? 'No answer has been reported.' : 'No open reports.'} />
      ) : (
        <ul className="cards">
          {reports.data.map((row) => (
            <li key={row.id} className="card">
              <div className="card-head">
                <span className="card-title">
                  <Icon name="alert" /> {REASONS[row.reason]}
                </span>
                <span className={row.status === 'open' ? 'badge badge-warn' : 'badge badge-muted'}>{row.status}</span>
              </div>
              <div className="card-meta">
                <span>
                  {row.email ?? 'someone'}, {when(row.created_at)}
                  {row.model ? `, answered by ${row.model}` : ''}
                </span>
              </div>
              {row.note && <p>“{row.note}”</p>}
              <blockquote className="quote">{row.answer}</blockquote>
              <div className="card-actions">
                {row.conversation_id && (
                  <Link href={`/conversations/${encodeURIComponent(row.conversation_id)}`}>Open the conversation</Link>
                )}
                {row.status === 'open' && canClose && (
                  <button type="button" className="btn btn-small" onClick={() => void close(row)}>
                    Mark as dealt with
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}
