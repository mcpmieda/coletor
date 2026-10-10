import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { paintTheme, readTheme } from './theme';
import './index.css';
paintTheme(readTheme());
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
