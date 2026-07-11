import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { api } from '../../api/network';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { EventTimeline, TimelineHeading } from './EventTimeline';

export function ActivityPage() {
  const events = useQuery({
    queryKey: ['events', { scope: 'all' }],
    queryFn: () => api.events(undefined, 100),
    retry: false,
  });
  return (
    <main className="activity-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">LOCAL AUDIT TRAIL</span>
          <h1>Workspace activity</h1>
          <p>Sanitized events from setup, inventory, connection tests, refreshes, and snapshots.</p>
        </div>
        <Button onClick={() => void events.refetch()} busy={events.isFetching}>
          <RefreshCw size={16} /> Refresh
        </Button>
      </header>
      <section className="activity-panel">
        {events.isPending ? (
          <AppState kind="loading" title="Loading workspace events" message="Reading the sanitized audit trail…" />
        ) : events.isError ? (
          <QueryErrorState error={events.error} onRetry={() => void events.refetch()} />
        ) : (
          <>
            <TimelineHeading count={events.data.length} />
            <EventTimeline events={events.data} />
          </>
        )}
      </section>
    </main>
  );
}
