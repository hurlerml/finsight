import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  api,
  type Account,
  type Connection,
  type ConnectionSyncStatus,
  type SyncStatus,
} from "@/api/client";
import { isAnyAccountSetupInProgress } from "@/lib/accountSetup";

type AppSetupContextValue = {
  accounts: Account[];
  connections: Connection[];
  connectionSyncStatuses: ConnectionSyncStatus[];
  hasAccounts: boolean;
  accountSetupInProgress: boolean;
  onboardingCompleted: boolean;
  loading: boolean;
  error: string | null;
  refreshSetup: () => Promise<void>;
  refreshAccounts: () => Promise<void>;
  updateAccounts: (accounts: Account[]) => void;
  completeOnboarding: () => Promise<void>;
};

const AppSetupContext = createContext<AppSetupContextValue | null>(null);

export function AppSetupProvider({ children }: { children: React.ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [syncStatuses, setSyncStatuses] = useState<SyncStatus[]>([]);
  const [connectionSyncStatuses, setConnectionSyncStatuses] = useState<
    ConnectionSyncStatus[]
  >([]);
  const [onboardingCompleted, setOnboardingCompleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshSetup = useCallback(async () => {
    const [
      loadedAccounts,
      loadedConnections,
      loadedSyncStatuses,
      loadedConnectionSyncStatuses,
    ] = await Promise.all([
      api.accounts(),
      api.connections(),
      api.syncStatus(),
      api.connectionSyncStatus(),
    ]);
    setAccounts(loadedAccounts);
    setConnections(loadedConnections);
    setSyncStatuses(loadedSyncStatuses);
    setConnectionSyncStatuses(loadedConnectionSyncStatuses);
  }, []);

  const refreshAccounts = useCallback(async () => {
    await refreshSetup();
  }, [refreshSetup]);

  const updateAccounts = useCallback((nextAccounts: Account[]) => {
    setAccounts(nextAccounts);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([api.onboardingStatus(), refreshSetup()])
      .then(([onboarding]) => {
        if (cancelled) return;
        setOnboardingCompleted(onboarding.completed);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshSetup]);

  const accountSetupInProgress = useMemo(
    () =>
      isAnyAccountSetupInProgress(
        accounts,
        connections,
        syncStatuses,
        connectionSyncStatuses,
      ),
    [accounts, connections, syncStatuses, connectionSyncStatuses],
  );

  useEffect(() => {
    if (!accountSetupInProgress) {
      return;
    }
    const id = window.setInterval(() => {
      refreshSetup().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(id);
  }, [accountSetupInProgress, refreshSetup]);

  const completeOnboarding = useCallback(async () => {
    const result = await api.setOnboardingCompleted(true);
    setOnboardingCompleted(result.completed);
  }, []);

  const value = useMemo(
    () => ({
      accounts,
      connections,
      connectionSyncStatuses,
      hasAccounts: accounts.length > 0,
      accountSetupInProgress,
      onboardingCompleted,
      loading,
      error,
      refreshSetup,
      refreshAccounts,
      updateAccounts,
      completeOnboarding,
    }),
    [
      accounts,
      connections,
      connectionSyncStatuses,
      accountSetupInProgress,
      onboardingCompleted,
      loading,
      error,
      refreshSetup,
      refreshAccounts,
      updateAccounts,
      completeOnboarding,
    ],
  );

  return (
    <AppSetupContext.Provider value={value}>
      {children}
    </AppSetupContext.Provider>
  );
}

export function useAppSetup() {
  const context = useContext(AppSetupContext);
  if (!context) {
    throw new Error("useAppSetup must be used within AppSetupProvider");
  }
  return context;
}
