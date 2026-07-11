import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { CircleAlert, Network } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  failed: boolean;
}

export class AppErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Keep the browser fallback generic so device data never appears in the UI error surface.
    console.error('The Terraformer interface stopped unexpectedly.', error.name, errorInfo.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="centered-page">
        <div className="centered-page__brand">
          <Network size={22} /> Terraformer
        </div>
        <div className="app-state app-state--error">
          <div className="app-state__icon">
            <CircleAlert size={24} />
          </div>
          <div className="app-state__copy">
            <h3>The interface needs to restart</h3>
            <p>No device operation was started. Reload this local page to continue.</p>
          </div>
          <button className="button button--secondary button--small" type="button" onClick={() => window.location.reload()}>
            Reload interface
          </button>
        </div>
      </main>
    );
  }
}
