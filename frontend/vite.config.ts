import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The frontend is a thin client over the M2 backend run API. The API base URL is
// configurable via VITE_API_BASE (default http://localhost:8000); the backend
// enables permissive CORS for local development.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  preview: { port: 5173 },
});
