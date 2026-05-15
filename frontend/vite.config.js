import { copyFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';

const browserBabelAssets = [
  'app.css',
  'data.jsx',
  'icons.jsx',
  'inbox.jsx',
  'tweaks-panel.jsx',
];

export default defineConfig({
  root: '.',
  server: {
    host: '0.0.0.0',
    port: 5173,
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  plugins: [
    {
      name: 'copy-browser-babel-assets',
      closeBundle() {
        mkdirSync('dist', { recursive: true });
        for (const asset of browserBabelAssets) {
          copyFileSync(asset, resolve('dist', asset));
        }
      },
    },
  ],
});
