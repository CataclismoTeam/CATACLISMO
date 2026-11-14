import { Component, type ReactNode } from 'react';
import { Button } from '../ui/Button.tsx';

interface Props {
  /** Qué parte ha fallado, en palabras del usuario ("el mapa", "el calendario") */
  what: string;
  children: ReactNode;
}

/** Ningún fallo técnico llega a la pantalla en crudo: se explica y se ofrece reintentar. */
export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 p-6">
        <p className="m-0 max-w-md text-center">
          No se pudo mostrar {this.props.what}. El resto de la aplicación sigue funcionando.
        </p>
        <Button onClick={() => this.setState({ failed: false })}>Reintentar</Button>
      </div>
    );
  }
}
