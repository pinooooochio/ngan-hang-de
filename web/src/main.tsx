import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import BankPage from "./pages/BankPage";
import EditorPage from "./pages/EditorPage";
import ImportPage from "./pages/ImportPage";
import "./styles.css";

function App() {
  return (
    <BrowserRouter>
      <header className="topbar">
        <span className="brand">Ngân hàng đề</span>
        <nav>
          <NavLink to="/" end>
            Ngân hàng câu hỏi
          </NavLink>
          <NavLink to="/cau/moi">Soạn câu mới</NavLink>
          <NavLink to="/import">Import</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<BankPage />} />
          <Route path="/cau/moi" element={<EditorPage />} />
          <Route path="/cau/:code" element={<EditorPage />} />
          <Route path="/import" element={<ImportPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
