import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <div className="card state">
      <h1>Page not found</h1>
      <p>The page you asked for does not exist or has moved.</p>
      <Link to="/" className="btn btn-primary">
        Go to portfolio
      </Link>
    </div>
  );
}
