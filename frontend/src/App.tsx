import { Navigate, Route, Routes } from "react-router-dom";

import { AppSetupProvider, useAppSetup } from "@/auth/AppSetupContext";
import { useVault } from "@/auth/VaultContext";
import { Layout } from "@/components/Layout";
import { AccountsPage } from "@/pages/Accounts";
import { AssetsPage } from "@/pages/Assets";
import { CategoriesPage } from "@/pages/Categories";
import { ChatPage } from "@/pages/Chat";
import { DashboardPage } from "@/pages/Dashboard";
import { DataSettingsPage } from "@/pages/DataSettings";
import { OnboardingPage } from "@/pages/Onboarding";
import { ProfilePage } from "@/pages/Profile";
import { TransactionsPage } from "@/pages/Transactions";
import { UnlockPage } from "@/pages/Unlock";

function UnlockedApp() {
  const { onboardingCompleted, loading, error } = useAppSetup();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        …
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4 text-center text-danger">
        {error}
      </div>
    );
  }
  if (!onboardingCompleted) {
    return (
      <Routes>
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="*" element={<Navigate to="/onboarding" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/onboarding" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="assets" element={<AssetsPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="connections" element={<Navigate to="/accounts" replace />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="profile/data" element={<DataSettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

function ProtectedApp() {
  const { status, loading } = useVault();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        …
      </div>
    );
  }

  if (!status || !status.initialized || !status.unlocked) {
    return <UnlockPage />;
  }

  return (
    <AppSetupProvider>
      <UnlockedApp />
    </AppSetupProvider>
  );
}

export default function App() {
  return <ProtectedApp />;
}
