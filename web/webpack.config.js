/**
 * Webpack config for the molior React web UI.
 *
 * Dev mode:  `npm install && npm run dev`
 *   - Requires webpack-dev-server from node_modules (full npm install).
 *   - webpack-dev-server on :5173
 *   - /api/* and /api2/* proxied to the molior FastAPI server on :9999
 *
 * Production build (local): `npm install && npm run build`
 *
 * Debian package build (debian/rules):
 *   npm ci --legacy-peer-deps   ← installs only babel-loader, mini-css-extract-plugin,
 *                                  react-router-dom, bootstrap-icons and their deps (~22 pkgs).
 *                                  Peer deps (webpack, @babel/*, css-loader, react, bootstrap,
 *                                  ansi_up) are skipped because they are provided by Debian
 *                                  system packages and resolved via NODE_PATH=/usr/share/nodejs.
 *   NODE_PATH=/usr/share/nodejs node_modules/.bin/webpack --mode production
 *
 * The isDebian flag is true whenever react is not in node_modules (Debian build).
 * In that case webpack aliases redirect react, react-dom, bootstrap and ansi_up to
 * their system paths under /usr/share/.
 */
const path = require('path');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const { existsSync } = require('fs');

const MOLIOR_API = process.env.MOLIOR_API_URL || 'http://localhost:9999';

// Debian build: react is not in node_modules; it comes from the system package node-react
// via NODE_PATH=/usr/share/nodejs set in debian/rules.
const isDebian = !existsSync(path.resolve(__dirname, 'node_modules/react'));

// Aliases that point the four system-provided libraries to their Debian paths.
// webpack resolves these before falling back to NODE_PATH, so the explicit mapping
// is needed for the non-standard locations under /usr/share/javascript/.
const debianAliases = {
  'react$':                                     '/usr/share/nodejs/react/index.js',
  'react/jsx-runtime$':                         '/usr/share/nodejs/react/jsx-runtime.js',
  'react/jsx-dev-runtime$':                     '/usr/share/nodejs/react/jsx-dev-runtime.js',
  'react-dom$':                                 '/usr/share/nodejs/react-dom/index.js',
  'react-dom/client$':                          '/usr/share/nodejs/react-dom/client.js',
  'bootstrap/dist/css/bootstrap.min.css$':      '/usr/share/javascript/bootstrap5/css/bootstrap.min.css',
  'bootstrap/dist/js/bootstrap.bundle.min.js$': '/usr/share/javascript/bootstrap5/js/bootstrap.bundle.min.js',
  'ansi_up$':                                   '/usr/share/javascript/ansi_up/ansi_up.js',
};

module.exports = (env, argv) => {
  const isProd = argv.mode === 'production';

  return {
    entry: './src/index.jsx',

    output: {
      path: path.resolve(__dirname, 'dist'),
      filename: 'assets/main.js',
      // 'auto' makes webpack derive the public path from the script's own URL
      // at runtime, so the bundle works under any reverse-proxy prefix.
      publicPath: 'auto',
      clean: true,
    },

    devtool: isProd ? false : 'eval-source-map',

    resolve: {
      extensions: ['.jsx', '.js'],
      alias: isDebian ? debianAliases : {},
    },

    module: {
      rules: [
        // JSX + modern JS via Babel.
        // babel-loader comes from node_modules (npm).
        // @babel/core, @babel/preset-env, @babel/preset-react come from node-babel7 (Debian)
        // via NODE_PATH=/usr/share/nodejs in the Debian build, or from node_modules in dev.
        {
          test: /\.jsx?$/,
          exclude: /node_modules/,
          use: {
            loader: 'babel-loader',
            options: {
              presets: [
                ['@babel/preset-env', { targets: 'defaults' }],
                ['@babel/preset-react', { runtime: 'automatic', development: !isProd }],
              ],
            },
          },
        },

        // CSS — extract to assets/main.css in both dev and prod.
        // css-loader comes from node-css-loader (Debian) via NODE_PATH, or node_modules in dev.
        {
          test: /\.css$/,
          use: [MiniCssExtractPlugin.loader, 'css-loader'],
        },

        // Fonts + images (bootstrap-icons woff2, logo PNGs, etc.)
        {
          test: /\.(woff2?|png|svg|ico)$/,
          type: 'asset/resource',
          generator: { filename: 'assets/[name][ext]' },
        },
      ],
    },

    plugins: [
      // mini-css-extract-plugin comes from node_modules (npm) — no Debian package exists.
      new MiniCssExtractPlugin({ filename: 'assets/main.css' }),
    ],

    // Suppress size warnings — single-bundle is intentional for this app.
    performance: { hints: false },

    // webpack-dev-server config (only used by `npm run dev`; not invoked in Debian build).
    devServer: {
      port: 5173,
      historyApiFallback: true,
      proxy: [
        {
          context: ['/api/websocket'],
          target: MOLIOR_API.replace(/^http/, 'ws'),
          ws: true,
          changeOrigin: true,
        },
        {
          context: ['/api', '/api2', '/internal'],
          target: MOLIOR_API,
          changeOrigin: true,
        },
      ],
    },
  };
};
