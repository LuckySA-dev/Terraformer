import { Info } from 'lucide-react';
import type { AnalysisCompleteness } from '../../types/api';

const REASON_TEXT: Record<string, (count: number) => string> = {
  no_snapshot: (count) => `${String(count)} have no configuration snapshot`,
  unsupported_vendor: (count) => `${String(count)} run a vendor that is not supported`,
};

/**
 * Rendered with every analysis result, without exception.
 *
 * Batfish answers only from the configurations it was given. Given three of ten
 * switches it still reports "A cannot reach B" with full confidence, so the
 * scope of the answer has to travel with the answer.
 */
export function CompletenessBanner({ completeness }: { completeness: AnalysisCompleteness }) {
  const { registered_device_count, analysed_device_count, observed_link_count } = completeness;
  const oldest = completeness.oldest_config_at;

  return (
    <div className="completeness-banner" role="note">
      <Info size={15} aria-hidden />
      <div>
        <strong>
          Analysed {analysed_device_count} of {registered_device_count} registered devices
        </strong>
        <ul>
          {completeness.exclusions.map((exclusion) => (
            <li key={exclusion.reason}>
              {REASON_TEXT[exclusion.reason]?.(exclusion.count) ??
                `${String(exclusion.count)} excluded (${exclusion.reason})`}
            </li>
          ))}
          <li>{observed_link_count} observed links supplied as layer-1 topology</li>
          {oldest === null ? null : (
            <li>Oldest configuration captured {new Date(oldest).toLocaleDateString()}</li>
          )}
        </ul>
      </div>
    </div>
  );
}
