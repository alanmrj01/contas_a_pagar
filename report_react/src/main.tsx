import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

function App(){
  return <main className="shell"><p className="eyebrow">CONTAS A PAGAR • RELATÓRIO REACT</p><h1>Previsto x Realizado</h1><p>Template React/Vite/TypeScript incluído para evolução do frontend. A distribuição desktop usa o relatório autocontido em HTML para funcionar offline.</p></main>
}
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>)
