import { useEffect } from 'react';

// Cards that carry the pointer spotlight (see "Cards & the pointer spotlight"
// in styles.css). Nested cards are all updated so the outer glow stays aligned.
const GLOW_TARGETS = '.panel, .score-card, .editor-card, .assessment-entry, .feature-card';

/**
 * Pointer-following light: sets --mx/--my on the cards under the pointer and
 * moves the page-level `.ambient-spot`. Purely visual; it reads no content,
 * runs at most once per animation frame, and ignores touch input.
 */
export function usePointerGlow() {
  useEffect(() => {
    if (!window.matchMedia?.('(pointer: fine)').matches) return;
    let frame = 0;
    let last: PointerEvent | undefined;
    const paint = () => {
      frame = 0;
      const event = last;
      if (!event) return;
      const spot = document.querySelector<HTMLElement>('.ambient-spot');
      if (spot) {
        spot.style.transform = `translate3d(${event.clientX}px, ${event.clientY}px, 0)`;
        spot.style.opacity = '1';
      }
      let card =
        event.target instanceof Element ? event.target.closest<HTMLElement>(GLOW_TARGETS) : null;
      while (card) {
        const rect = card.getBoundingClientRect();
        card.style.setProperty('--mx', `${Math.round(event.clientX - rect.left)}px`);
        card.style.setProperty('--my', `${Math.round(event.clientY - rect.top)}px`);
        card = card.parentElement?.closest<HTMLElement>(GLOW_TARGETS) ?? null;
      }
    };
    const onMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      last = event;
      if (!frame) frame = requestAnimationFrame(paint);
    };
    const onOut = (event: PointerEvent) => {
      if (event.relatedTarget) return;
      const spot = document.querySelector<HTMLElement>('.ambient-spot');
      if (spot) spot.style.opacity = '0';
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerout', onOut, { passive: true });
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerout', onOut);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
}
