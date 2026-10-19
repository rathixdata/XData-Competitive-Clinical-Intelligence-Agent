import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, HashRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import { createQueryClient } from './lib/queryClient';
import './styles/global.css';

// Hosted static demo (npm run build:demo): replay recorded API responses and use hash routing.
const DEMO = import.meta.env.VITE_DEMO === '1';
if (DEMO) (await import('../demo/mockApi')).installDemoApi();
const Router = DEMO ? HashRouter : BrowserRouter;

const queryClient = createQueryClient();

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </Router>
    </QueryClientProvider>
  </StrictMode>,
);
