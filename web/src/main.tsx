import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, homeOf, useAuth } from "./auth";
import Nav, { allowed } from "./components/Nav";
import AccountPage from "./pages/AccountPage";
import AttemptPage from "./pages/AttemptPage";
import BackupPage from "./pages/BackupPage";
import BankPage from "./pages/BankPage";
import EditorPage from "./pages/EditorPage";
import ExamDetailPage from "./pages/ExamDetailPage";
import ExamListPage from "./pages/ExamListPage";
import ExamNewPage from "./pages/ExamNewPage";
import GenBatchPage from "./pages/GenBatchPage";
import GeneratePage from "./pages/GeneratePage";
import ImportPage from "./pages/ImportPage";
import LoginPage from "./pages/LoginPage";
import LogPage from "./pages/LogPage";
import PracticeHomePage, { PracticeResultsPage } from "./pages/PracticeHomePage";
import RequestsPage from "./pages/RequestsPage";
import SettingsPage from "./pages/SettingsPage";
import TagsPage from "./pages/TagsPage";
import UsersPage from "./pages/UsersPage";
import "./styles.css";

/** Trang không thuộc quyền của vai trò hiện tại thì chuyển về trang đầu của vai trò đó. */
function Guarded() {
  const { me } = useAuth();
  const { pathname } = useLocation();
  if (!allowed(me.role, pathname)) return <Navigate to={homeOf(me.role)} replace />;
  return (
    <Routes>
      <Route path="/" element={<BankPage />} />
      <Route path="/cau/moi" element={<EditorPage />} />
      <Route path="/cau/:code" element={<EditorPage />} />
      <Route path="/import" element={<ImportPage />} />
      <Route path="/the" element={<TagsPage />} />
      <Route path="/de" element={<ExamListPage />} />
      <Route path="/de/moi" element={<ExamNewPage />} />
      <Route path="/de/:id" element={<ExamDetailPage />} />
      <Route path="/sinh" element={<GeneratePage />} />
      <Route path="/sinh/:id" element={<GenBatchPage />} />
      <Route path="/luyen" element={<PracticeHomePage />} />
      <Route path="/luyen/ket-qua" element={<PracticeResultsPage />} />
      <Route path="/luyen/:id" element={<AttemptPage />} />
      <Route path="/tai-khoan" element={<AccountPage />} />
      <Route path="/cai-dat" element={<SettingsPage />} />
      <Route path="/cai-dat/nguoi-dung" element={<UsersPage />} />
      <Route path="/cai-dat/yeu-cau" element={<RequestsPage />} />
      <Route path="/cai-dat/nhat-ky" element={<LogPage />} />
      <Route path="/sao-luu" element={<BackupPage />} />
      <Route path="*" element={<Navigate to={homeOf(me.role)} replace />} />
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider login={(setup, done) => <LoginPage setup={setup} onDone={done} />}>
        <Nav />
        <main>
          <Guarded />
        </main>
      </AuthProvider>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
