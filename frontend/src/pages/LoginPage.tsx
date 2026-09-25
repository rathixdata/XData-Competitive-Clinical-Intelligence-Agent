import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { BookOpen, LogIn } from 'lucide-react';
import { useAuth } from '../auth/context';
import { beginSso, ssoAvailable } from '../auth/authProvider';
import { InlineError } from '../components/States';

const TENANT_KEY = 'xdata.lastTenant';

function safeNext(next: string | null): string {
  // Only same-origin absolute paths (no protocol-relative or backslash tricks).
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return '/';
  return next;
}

export function LoginPage() {
  const { login, token } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [tenant, setTenant] = useState(() => {
    try {
      return window.localStorage.getItem(TENANT_KEY) ?? '';
    } catch {
      return '';
    }
  });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const next = safeNext(params.get('next'));

  if (token && !busy) return <Navigate to={next} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login({ tenant, email, password });
      try {
        window.localStorage.setItem(TENANT_KEY, tenant.trim());
      } catch {
        /* ignore */
      }
      navigate(next, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <main className="login-card" aria-labelledby="login-title">
        <div className="row" style={{ marginBottom: 14 }}>
          <BookOpen size={28} color="#1d4ed8" aria-hidden />
          <div>
            <h1 id="login-title" style={{ margin: 0 }}>
              Sign in
            </h1>
            <div className="small muted">XData Competitive &amp; Clinical Intelligence Agent</div>
          </div>
        </div>
        {params.get('expired') ? (
          <div className="banner banner-info" role="status">
            <p>Your session ended. Please sign in again.</p>
          </div>
        ) : null}
        <InlineError error={error} />
        <form className="stack" onSubmit={submit} noValidate={false}>
          <div className="field">
            <label htmlFor="tenant">Tenant</label>
            <input id="tenant" type="text" autoComplete="organization" required value={tenant} onChange={(e) => setTenant(e.target.value)} />
            <span className="hint">Your organisation&apos;s workspace identifier, e.g. demo-oncology</span>
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy} aria-busy={busy}>
            <LogIn size={16} aria-hidden />
            {busy ? 'Signing in...' : 'Sign in'}
          </button>
          {ssoAvailable() ? (
            <button type="button" className="btn" onClick={() => beginSso(tenant)} disabled={!tenant}>
              Sign in with SSO
            </button>
          ) : null}
        </form>
        <p className="small muted" style={{ marginTop: 16 }}>
          Decision-support output. Facts are evidence-linked; interpretations are AI-generated hypotheses.
        </p>
      </main>
    </div>
  );
}
