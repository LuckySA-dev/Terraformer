import { useCallback, useEffect, useRef, useState } from 'react';

export interface WindowPosition {
  x: number;
  y: number;
}

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max);

/**
 * Drag behaviour for the floating config window.
 *
 * Pointer events rather than mouse events so a trackpad, pen or touch drag all
 * work, and pointer capture so a fast drag that outruns the title bar does not
 * drop the window mid-move. The position is clamped on every move and again on
 * resize, because a window dragged to the far edge and then shrunk with the
 * viewport would otherwise be stranded off-screen with no way to grab it back.
 */
export function useDraggableWindow(initial: WindowPosition) {
  const [position, setPosition] = useState(initial);
  const frame = useRef<HTMLElement | null>(null);
  const origin = useRef<{ pointerX: number; pointerY: number; x: number; y: number } | null>(null);

  const bounds = useCallback((next: WindowPosition): WindowPosition => {
    // Keep a strip of the title bar reachable rather than the whole window, so
    // a large window can still be pushed mostly off-screen deliberately.
    const width = frame.current?.offsetWidth ?? 0;
    const margin = 56;
    return {
      x: clamp(next.x, margin - width, Math.max(margin, window.innerWidth - margin)),
      y: clamp(next.y, 0, Math.max(0, window.innerHeight - margin)),
    };
  }, []);

  const onPointerDown = (event: React.PointerEvent<HTMLElement>) => {
    // Left button / primary contact only: a right-click drag is a context
    // menu, not a move.
    if (event.button !== 0) return;
    // The title bar is the drag handle, but it also holds the close button.
    // Capturing the pointer here would retarget the rest of the gesture to the
    // bar, so the button never received its click and the window could not be
    // closed. Controls inside the handle keep their own events.
    if (event.target instanceof Element && event.target.closest('button, a, input, select')) {
      return;
    }
    origin.current = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      x: position.x,
      y: position.y,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLElement>) => {
    const start = origin.current;
    if (start === null) return;
    setPosition(
      bounds({
        x: start.x + (event.clientX - start.pointerX),
        y: start.y + (event.clientY - start.pointerY),
      }),
    );
  };

  const endDrag = (event: React.PointerEvent<HTMLElement>) => {
    if (origin.current === null) return;
    origin.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  useEffect(() => {
    const onResize = () => setPosition((current) => bounds(current));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [bounds]);

  return {
    position,
    frameRef: frame,
    dragHandlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
    },
  };
}
