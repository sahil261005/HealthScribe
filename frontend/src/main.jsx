import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
// imported after App so tailwind comes after App.css, same order as the old CDN script
// (otherwise App.css .hidden beats md:flex and the navbar disappears)
import './tailwind.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
