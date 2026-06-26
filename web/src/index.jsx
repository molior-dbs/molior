/**
 * Entry point.
 * Bootstrap CSS + Bootstrap Icons are imported here so every component gets them.
 * The old Angular app loaded Material Design globally via styles.scss;
 * here Bootstrap plays the same role.
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap/dist/js/bootstrap.bundle.min.js';
import 'bootstrap-icons/font/bootstrap-icons.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
