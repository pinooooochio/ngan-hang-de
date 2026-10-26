import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import BankPage from "./pages/BankPage";
import EditorPage from "./pages/EditorPage";
import ExamDetailPage from "./pages/ExamDetailPage";
import ExamListPage from "./pages/ExamListPage";
import ExamNewPage from "./pages/ExamNewPage";
import AttemptPage from "./pages/AttemptPage";
import ImportPage from "./pages/ImportPage";
import PracticeHomePage from "./pages/PracticeHomePage";
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
          <NavLink to="/de" end>
            Kho đề
          </NavLink>
          <NavLink to="/de/moi">Ghép đề</NavLink>
          <NavLink to="/luyen">Luyện đề</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<BankPage />} />
          <Route path="/cau/moi" element={<EditorPage />} />
          <Route path="/cau/:code" element={<EditorPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/de" element={<ExamListPage />} />
          <Route path="/de/moi" element={<ExamNewPage />} />
          <Route path="/de/:id" element={<ExamDetailPage />} />
          <Route path="/luyen" element={<PracticeHomePage />} />
          <Route path="/luyen/:id" element={<AttemptPage />} />
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
