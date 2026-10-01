import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import sitemap from '@astrojs/sitemap';
import tailwindcss from '@tailwindcss/vite';

const siteUrl = process.env.PUBLIC_SITE_URL?.trim();
const backendProxy = {
  '/_gianna': 'http://127.0.0.1:5173',
  '/assets': 'http://127.0.0.1:5173',
  '/src': 'http://127.0.0.1:5173',
  '/@': 'http://127.0.0.1:5173',
  '/node_modules': 'http://127.0.0.1:5173',
  '/portal-theme.js': 'http://127.0.0.1:5173',
  '/api': 'http://127.0.0.1:8010',
  '/admin': 'http://127.0.0.1:5173',
};

export default defineConfig({
  site: siteUrl || undefined,
  integrations: [react(), ...(siteUrl ? [sitemap()] : [])],
  prefetch: {
    defaultStrategy: 'hover',
  },
  vite: {
    plugins: [tailwindcss()],
    server: { proxy: backendProxy },
    preview: { proxy: backendProxy },
  },
  markdown: {
    shikiConfig: {
      themes: {
        light: 'github-dark',
        dark: 'github-dark',
      },
    },
  },
});
