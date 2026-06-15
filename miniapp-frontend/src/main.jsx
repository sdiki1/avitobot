import React, { Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const App = lazy(() => import('./App'))

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Suspense fallback={<div className="app-root"><div className="mobile-shell"><main className="main-content"><div className="empty-card">Загрузка...</div></main></div></div>}>
      <App />
    </Suspense>
  </React.StrictMode>,
)
