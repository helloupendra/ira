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

// A wrong answer is a warning; one that harmed, offended or showed too much is serious.
const REASON_BADGES: Record<ReportRow['reason'], string> = {
  wrong: 'badge badge-warn',
  harmful: 'badge badge-danger',
  offensive: 'badge badge-danger',
  private: 'badge badge-danger',
  other: 'badge badge-muted',
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
        <button type="button" className="btn btn-ghost btn-small" onClick={reports.reload}>
          <Icon name="refresh" />
          Refresh
        </button>
      }
    >
      <section className="section">
        <div className="filters" role="group" aria-label="Which reports">
          <button type="button" className="filter" aria-pressed={!showAll} onClick={() => setShowAll(false)}>
            Open
          </button>
          <button type="button" className="filter" aria-pressed={showAll} onClick={() => setShowAll(true)}>
            All, closed too
          </button>
        </div>
        {reports.data === undefined ? (
          reports.error ? (
            <ErrorState error={reports.error} onRetry={reports.reload} needs="admin.read" />
          ) : (
            <Loading />
          )
        ) : reports.data.length === 0 ? (
          <Empty
            title={showAll ? 'Nothing reported' : 'No open reports'}
            text={
              showAll
                ? 'No answer has been reported. People report one from the Ira app, the Mac app or the phone.'
                : 'Every report has been dealt with.'
            }
          />
        ) : (
          <ul className="reports">
            {reports.data.map((row) => (
              <li key={row.id} className="report">
                <div className="report-head">
                  <span className={REASON_BADGES[row.reason]}>{REASONS[row.reason]}</span>
                  <span className="report-meta">
                    {row.email ?? 'someone'}, {when(row.created_at)}
                    {row.model ? `, answered by ${row.model}` : ''}
                  </span>
                  <span className={row.status === 'open' ? 'badge badge-warn report-status' : 'badge badge-muted report-status'}>
                    {row.status}
                  </span>
                </div>
                {row.note && <p className="report-note">“{row.note}”</p>}
                <figure className="report-answer">
                  <figcaption>Ira's answer</figcaption>
                  <blockquote className="quote">{row.answer}</blockquote>
                </figure>
                {(row.conversation_id || (row.status === 'open' && canClose)) && (
                  <div className="report-actions">
                    {row.conversation_id && (
                      <Link
                        href={`/conversations/${encodeURIComponent(row.conversation_id)}`}
                        className="btn btn-ghost btn-small"
                      >
                        Open the conversation
                      </Link>
                    )}
                    {row.status === 'open' && canClose && (
                      <button type="button" className="btn btn-small" onClick={() => void close(row)}>
                        Mark as dealt with
                      </button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </Page>
  );
}
