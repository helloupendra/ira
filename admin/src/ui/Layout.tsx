import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'wouter';
import { roleLabel, whoCan } from '../lib/roles';
import { getTheme, setTheme, THEMES, type Theme } from '../lib/theme';
import type { User } from '../api/endpoints';
import { Icon, Mark } from './icons';
import { currentNav, MORE_NAV, NAV, PRIMARY_NAV, type NavItem } from './nav';
import { useSession } from './Session';
import { useToast } from './toast';

const THEME_LABELS: Record<Theme, string> = { system: 'System', light: 'Light', dark: 'Dark' };

function NavLink({ item, active, allowed }: { item: NavItem; active: boolean; allowed: boolean }) {
  const hint = item.needs === 'users' ? 'Owner only' : `Only ${whoCan(item.needs)}`;
  return (
    <Link
      href={item.href}
      className={`nav-link${allowed ? '' : ' is-disabled'}`}
      aria-current={active ? 'page' : undefined}
      aria-disabled={allowed ? undefined : true}
      title={allowed ? undefined : hint}
    >
      <Icon name={item.icon} />
      <span className="nav-text">
        <span className="nav-label">{item.label}</span>
        {!allowed && <span className="nav-hint">{hint}</span>}
      </span>
    </Link>
  );
}

function UserBlock({ user }: { user: User | undefined }) {
  if (!user) return null;
  return (
    <div className="user">
      <span className="user-email" title={user.email}>
        {user.email}
      </span>
      <span className="badge badge-muted">{roleLabel(user.role)}</span>
    </div>
  );
}

function ThemeControl({ theme, name, onChange }: { theme: Theme; name: string; onChange: (t: Theme) => void }) {
  return (
    <fieldset className="segmented">
      <legend>Theme</legend>
      <div className="segments">
        {THEMES.map((t) => (
          <label key={t} className="segment">
            <input type="radio" name={name} value={t} checked={theme === t} onChange={() => onChange(t)} />
            <span>{THEME_LABELS[t]}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { me, can, signOut } = useSession();
  const [location] = useLocation();
  const toast = useToast();
  const sheet = useRef<HTMLDialogElement>(null);
  const [theme, setThemeState] = useState<Theme>(() => getTheme());

  const current = currentNav(location);
  const user = me?.user;

  // Navigating from the sheet closes it.
  useEffect(() => {
    if (sheet.current?.open) sheet.current.close();
  }, [location]);

  function chooseTheme(t: Theme) {
    setTheme(t);
    setThemeState(t);
  }

  async function onSignOut() {
    try {
      await signOut();
    } catch {
      toast("Couldn't sign out. Check the connection and try again.");
    }
  }

  const navList = (items: readonly NavItem[]) => (
    <ul>
      {items.map((item) => (
        <li key={item.href}>
          <NavLink item={item} active={current?.href === item.href} allowed={can(item.needs)} />
        </li>
      ))}
    </ul>
  );

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <aside className="rail">
        <div className="brand">
          <Mark />
          <span className="brand-name">IRA</span>
        </div>
        <nav className="rail-nav" aria-label="Console">
          {navList(NAV)}
        </nav>
        <div className="rail-foot">
          <UserBlock user={user} />
          <ThemeControl theme={theme} name="theme-rail" onChange={chooseTheme} />
          <button type="button" className="btn btn-ghost btn-small" onClick={onSignOut}>
            <Icon name="signOut" />
            Sign out
          </button>
        </div>
      </aside>

      <header className="topbar">
        <Mark />
        <span className="brand-name">IRA</span>
      </header>

      <main id="main" className="main" tabIndex={-1}>
        {children}
      </main>

      <nav className="tabbar" aria-label="Console">
        {PRIMARY_NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="tab"
            aria-current={current?.href === item.href ? 'page' : undefined}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </Link>
        ))}
        <button
          type="button"
          className={`tab${current && MORE_NAV.includes(current) ? ' is-active' : ''}`}
          aria-haspopup="dialog"
          onClick={() => sheet.current?.showModal()}
        >
          <Icon name="more" />
          <span>More</span>
        </button>
      </nav>

      <dialog ref={sheet} className="sheet" aria-labelledby="sheet-title">
        <div className="sheet-body">
          <div className="sheet-head">
            <h2 id="sheet-title">More</h2>
            <button type="button" className="icon-btn" aria-label="Close" onClick={() => sheet.current?.close()}>
              <Icon name="close" />
            </button>
          </div>
          <nav className="sheet-nav" aria-label="More pages">
            {navList(MORE_NAV)}
          </nav>
          <div className="sheet-foot">
            <UserBlock user={user} />
            <ThemeControl theme={theme} name="theme-sheet" onChange={chooseTheme} />
            <button type="button" className="btn btn-ghost" onClick={onSignOut}>
              <Icon name="signOut" />
              Sign out
            </button>
          </div>
        </div>
      </dialog>
    </div>
  );
}
