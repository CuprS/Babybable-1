// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    // public/vendor is copied from node_modules by scripts/copy-leaflet.js.
    ignores: ['dist/*', 'public/vendor/*'],
  },
  {
    // The standalone web map page runs as a plain browser script with Leaflet loaded globally.
    files: ['public/map.js'],
    languageOptions: { sourceType: 'script', globals: { L: 'readonly', window: 'readonly', document: 'readonly' } },
  },
  {
    // Node build helpers.
    files: ['scripts/**/*.js'],
    languageOptions: { sourceType: 'commonjs', globals: { __dirname: 'readonly', require: 'readonly', process: 'readonly', console: 'readonly' } },
  },
]);
