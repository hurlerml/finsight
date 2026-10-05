import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { api, type VaultSetupResult, type VaultStatus } from "@/api/client";

const TOKEN_KEY = "finsight.vaultToken";

type VaultContextValue = {
  status: VaultStatus | null;
  token: string | null;
  loading: boolean;
  error: string | null;
  refreshStatus: () => Promise<void>;
  setup: (password: string) => Promise<VaultSetupResult>;
  confirmSetupRecovery: (recoveryPhrase: string, token: string) => Promise<void>;
  unlock: (password: string) => Promise<void>;
  recover: (recoveryPhrase: string, newPassword: string) => Promise<void>;
  lock: () => Promise<void>;
};

const VaultContext = createContext<VaultContextValue | null>(null);

export function VaultProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [token, setToken] = useState<string | null>(() =>
    sessionStorage.getItem(TOKEN_KEY)
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    const s = await api.vaultStatus();
    setStatus(s);
    setError(null);
    if (!s.unlocked) {
      sessionStorage.removeItem(TOKEN_KEY);
      setToken(null);
      api.setAuthToken(null);
    }
  }, []);

  useEffect(() => {
    api.setAuthToken(token);
    let cancelled = false;
    setLoading(true);
    refreshStatus()
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
        // Allow Unlock page to render instead of hanging on "…"
        setStatus((prev) => prev ?? {
          initialized: true,
          unlocked: false,
          recovery_configured: false,
          recovery_confirmed: false,
        });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshStatus, token]);

  const setup = useCallback(async (password: string) => {
    const result = await api.vaultSetup(password);
    setError(null);
    return result;
  }, []);

  const activateToken = useCallback(async (newToken: string) => {
    sessionStorage.setItem(TOKEN_KEY, newToken);
    api.setAuthToken(newToken);
    setToken(newToken);
    setError(null);
    const nextStatus = await api.vaultStatus();
    setStatus(nextStatus);
  }, []);

  const confirmSetupRecovery = useCallback(async (
    recoveryPhrase: string,
    setupToken: string,
  ) => {
    await api.vaultConfirmRecovery(recoveryPhrase, setupToken);
    await activateToken(setupToken);
  }, [activateToken]);

  const unlock = useCallback(async (password: string) => {
    const res = await api.vaultUnlock(password);
    await activateToken(res.token);
  }, [activateToken]);

  const recover = useCallback(async (recoveryPhrase: string, newPassword: string) => {
    const res = await api.vaultRecover(recoveryPhrase, newPassword);
    await activateToken(res.token);
  }, [activateToken]);

  const lock = useCallback(async () => {
    await api.vaultLock();
    sessionStorage.removeItem(TOKEN_KEY);
    api.setAuthToken(null);
    setToken(null);
    await refreshStatus();
  }, [refreshStatus]);

  const value = useMemo(
    () => ({
      status,
      token,
      loading,
      error,
      refreshStatus,
      setup,
      confirmSetupRecovery,
      unlock,
      recover,
      lock,
    }),
    [
      status,
      token,
      loading,
      error,
      refreshStatus,
      setup,
      confirmSetupRecovery,
      unlock,
      recover,
      lock,
    ]
  );

  return <VaultContext.Provider value={value}>{children}</VaultContext.Provider>;
}

export function useVault() {
  const ctx = useContext(VaultContext);
  if (!ctx) throw new Error("useVault must be used within VaultProvider");
  return ctx;
}
