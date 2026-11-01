import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Icon } from './icons';

export interface MenuItem {
  label: string;
  onSelect: () => void;
  // Why it can't be chosen now; shown under its label, and it stays in the list.
  reason?: string | null;
  danger?: boolean;
}

// A row's less frequent actions behind one "⋯" button. The list opens under the
// button, takes focus, moves with the arrow keys and closes on Escape, on a
// choice or on a click anywhere else.
export function Menu({ label, items }: { label: string; items: readonly MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    enabled(root.current)[0]?.focus();
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
      button.current?.focus();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    const list = enabled(root.current);
    if (list.length === 0) return;
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? list.length - 1
          : (at + (event.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length;
    list[next]?.focus();
  }

  return (
    <div className="menu" ref={root} onKeyDown={open ? onKeyDown : undefined}>
      <button
        ref={button}
        type="button"
        className="icon-btn menu-button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((was) => !was)}
      >
        <Icon name="more" />
      </button>
      {open && (
        <div id={id} className="menu-list" role="menu" aria-label={label}>
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              className={item.danger ? 'menu-item is-danger' : 'menu-item'}
              disabled={Boolean(item.reason)}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              <span>{item.label}</span>
              {item.reason && <span className="menu-hint">{item.reason}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function enabled(root: HTMLElement | null): HTMLButtonElement[] {
  return root ? [...root.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')] : [];
}
