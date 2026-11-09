import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '');
  const mockRunsEnabled = (env.MOCK_RUNS_ENABLED || 'true').toLowerCase() === 'true';
  return {
    plugins: [react()],
    envDir: '..',
    define: {
      'import.meta.env.VITE_API_MODE': JSON.stringify(mockRunsEnabled ? 'demo' : 'api'),
    },
    server: { port: 5173, strictPort: true },
  };
});
