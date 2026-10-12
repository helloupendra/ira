import '../../src/ira/web/static/tokens.css';
import './styles/console.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { applyTheme, getTheme } from './lib/theme';

// Apply the stored theme before the first paint so nothing flashes.
applyTheme(getTheme());

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
