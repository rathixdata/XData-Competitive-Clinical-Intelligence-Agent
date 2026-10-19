import { defineConfig, mergeConfig } from 'vite';
import base from '../vite.config';

// Static, single-chunk build for the hosted demo (see demo/README.md).
export default mergeConfig(
  base,
  defineConfig({
    base: './',
    define: { 'import.meta.env.VITE_DEMO': JSON.stringify('1') },
    build: { outDir: 'dist-demo', emptyOutDir: true, assetsInlineLimit: 100_000_000, rollupOptions: { output: { inlineDynamicImports: true } } },
  }),
);
