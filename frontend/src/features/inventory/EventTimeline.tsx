import { Activity, AlertTriangle, CheckCircle2, Circle, Info, XCircle } from 'lucide-react';
import type { EventRecord } from '../../types/api';
import { AppState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { formatDateTime, titleCase } from '../../lib/format';

const eventIcon = (severity?: string) => {
  if (severity === 'error') return XCircle;
  if (severity === 'warning') return AlertTriangle;
  if (severity === 'success') return CheckCircle2;
  if (severity === 'info') return Info;
  return Circle;
};

const eventTone = (severity?: string): 'danger' | 'warning' | 'success' | 'info' | 'neutral' => {
  if (severity === 'error') return 'danger';
  if (severity === 'warning') return 'warning';
  if (severity === 'success') return 'success';
  if (severity === 'info') return 'info';
  return 'neutral';
};

export function EventTimeline({ events, compact = false }: { events: EventRecord[]; compact?: boolean }) {
  if (events.length === 0) {
    return (
      <AppState
        kind="empty"
        title="No events recorded"
        message="Read-only connection tests, refreshes, and snapshots will appear here."
        compact={compact}
      />
    );
  }

  return (
    <ol className={`timeline ${compact ? 'timeline--compact' : ''}`} aria-label="Event timeline">
      {events.map((event) => {
        const Icon = eventIcon(event.severity);
        return (
          <li key={event.id} className={`timeline__item timeline__item--${eventTone(event.severity)}`}>
            <div className="timeline__icon" aria-hidden="true">
              <Icon size={15} />
            </div>
            <div className="timeline__content">
              <div className="timeline__meta">
                <Badge tone={eventTone(event.severity)}>
                  {titleCase(event.event_type)}
                </Badge>
                <time dateTime={event.created_at}>{formatDateTime(event.created_at)}</time>
              </div>
              <p>{event.message}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function TimelineHeading({ count }: { count: number }) {
  return (
    <div className="section-heading">
      <div>
        <span className="eyebrow">SANITIZED AUDIT</span>
        <h2>Event timeline</h2>
        <p>Append-oriented records from local inventory and device read operations.</p>
      </div>
      <Badge tone="neutral">
        <Activity size={13} /> {count} events
      </Badge>
    </div>
  );
}
