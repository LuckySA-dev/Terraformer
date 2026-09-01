import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/network';
import { AppState, QueryErrorState } from '../../components/ui/AppState';

/**
 * What the device is routing with right now.
 *
 * Read-only, and live: unlike interfaces there is no table behind static
 * routes or `router` blocks, so this opens the device each time it is shown.
 * It exists because the routing forms below it ask the operator to name a
 * process or a prefix that they previously had to go find in a terminal.
 */
export function RoutingInventory({ deviceId }: { deviceId: string }) {
  const routing = useQuery({
    queryKey: ['devices', deviceId, 'routing'],
    queryFn: () => api.routing(deviceId),
    retry: false,
  });

  if (routing.isPending) {
    return (
      <AppState
        kind="loading"
        title="Reading the device"
        message="Routing is not stored, so this is read from the device now…"
        compact
      />
    );
  }
  if (routing.isError) {
    return <QueryErrorState error={routing.error} onRetry={() => void routing.refetch()} compact />;
  }

  const { static_routes: routes, processes } = routing.data;
  if (routes.length === 0 && processes.length === 0) {
    return (
      <AppState
        kind="empty"
        title="No routing configured"
        message="This device has no static routes and no routing process. The forms below add them."
        compact
      />
    );
  }

  return (
    <div className="routing-inventory">
      <section>
        <h4>Static routes</h4>
        {routes.length === 0 ? (
          <p className="interface-table__empty">None.</p>
        ) : (
          <div className="interface-table-wrap">
            <table className="interface-table">
              <thead>
                <tr>
                  <th scope="col">Destination</th>
                  <th scope="col">Next hop</th>
                  <th scope="col">Configured line</th>
                </tr>
              </thead>
              <tbody>
                {routes.map((route) => (
                  <tr key={route.command}>
                    <td className="mono">{route.destination} {route.mask}</td>
                    <td className="mono">{route.next_hop}</td>
                    {/* The device's own line, options and all -- that is what
                        a rollback would restore. */}
                    <td className="mono routing-inventory__raw">{route.command}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h4>Routing processes</h4>
        {processes.length === 0 ? (
          <p className="interface-table__empty">None.</p>
        ) : (
          processes.map((process) => (
            <div key={process.name} className="routing-inventory__process">
              <strong className="mono">router {process.name}</strong>
              <pre className="config-window__command-list">
                {process.statements.join('\n') || '(no statements)'}
              </pre>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
