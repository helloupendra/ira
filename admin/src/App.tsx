import { lazy, Suspense, useEffect, type ReactNode } from 'react';
import { Redirect, Route, Router, Switch, useLocation, useSearch } from 'wouter';
import { roleLabel, whyNot, type Permission } from './lib/roles';
import Invite from './pages/Invite';
import Login from './pages/Login';
import Setup from './pages/Setup';
import { Mark } from './ui/icons';
import { Layout } from './ui/Layout';
import { Page } from './ui/Page';
import { SessionProvider, useSession } from './ui/Session';
import { ErrorState, Forbidden, Loading } from './ui/states';
import { ToastProvider, useToast } from './ui/toast';

// One chunk per screen, so the first screen loads only what it shows.
const Overview = lazy(() => import('./pages/Overview'));
const Conversations = lazy(() => import('./pages/Conversations'));
const Conversation = lazy(() => import('./pages/Conversation'));
const Actions = lazy(() => import('./pages/Actions'));
const Tools = lazy(() => import('./pages/Tools'));
const Models = lazy(() => import('./pages/Models'));
const Channels = lazy(() => import('./pages/Channels'));
const Devices = lazy(() => import('./pages/Devices'));
const Users = lazy(() => import('./pages/Users'));
const Tokens = lazy(() => import('./pages/Tokens'));
const Audit = lazy(() => import('./pages/Audit'));
const NotFound = lazy(() => import('./pages/NotFound'));

export function App() {
  return (
    <Router base="/admin">
      <ToastProvider>
        <SessionProvider>
          <Switch>
            <Route path="/login" component={Login} />
            <Route path="/setup" component={Setup} />
            <Route path="/invite" component={Invite} />
            <Route>
              <Console />
            </Route>
          </Switch>
        </SessionProvider>
      </ToastProvider>
    </Router>
  );
}

// Shows a page only when the role holds the permission; the server checks too.
function Guard({ needs, title, children }: { needs: Permission; title: string; children: ReactNode }) {
  const { me, can } = useSession();
  if (can(needs)) return <>{children}</>;
  return (
    <Page title={title}>
      <Forbidden why={whyNot(me?.user.role ?? 'viewer', needs)} />
    </Page>
  );
}

function NotForYou() {
  const { me, signOut } = useSession();
  const toast = useToast();
  useEffect(() => {
    document.title = 'IRA console';
  }, []);
  async function onSignOut() {
    try {
      await signOut();
    } catch {
      toast("Couldn't sign out. Check the connection and try again.");
    }
  }
  return (
    <main className="gate">
      <div className="gate-card">
        <Mark tile size={40} />
        <h1>The console is for owners, admins and viewers</h1>
        <p className="muted">
          You are signed in as {me?.user.email} with the {roleLabel(me?.user.role ?? '')} role, which uses Ira
          but cannot read the console.
        </p>
        <div className="actions-row">
          <a className="btn btn-primary" href="/">
            Open Ira
          </a>
          <button type="button" className="btn btn-ghost" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </div>
    </main>
  );
}

function Console() {
  const session = useSession();
  const [location] = useLocation();
  const search = useSearch();

  if (session.status === 'loading') {
    return (
      <main className="gate">
        <Loading />
      </main>
    );
  }
  if (session.status === 'error' && session.error) {
    return (
      <main className="gate">
        <div className="gate-card">
          <ErrorState error={session.error} onRetry={() => void session.refresh()} />
        </div>
      </main>
    );
  }
  if (session.status !== 'ready') {
    const next = location + (search ? `?${search}` : '');
    return <Redirect to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  if (!session.can('admin.read')) return <NotForYou />;

  return (
    <Layout>
      <Suspense fallback={<Loading />}>
        <Switch>
          <Route path="/" component={Overview} />
          <Route path="/conversations" component={Conversations} />
          <Route path="/conversations/:id">{(params) => <Conversation id={params.id ?? ''} />}</Route>
          <Route path="/actions" component={Actions} />
          <Route path="/tools" component={Tools} />
          <Route path="/models" component={Models} />
          <Route path="/channels" component={Channels} />
          <Route path="/devices">
            <Guard needs="ask" title="Devices">
              <Devices />
            </Guard>
          </Route>
          <Route path="/users">
            <Guard needs="users" title="Users & roles">
              <Users />
            </Guard>
          </Route>
          <Route path="/tokens" component={Tokens} />
          <Route path="/audit" component={Audit} />
          <Route component={NotFound} />
        </Switch>
      </Suspense>
    </Layout>
  );
}
