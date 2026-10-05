import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, CircleHelp, Loader2, Search } from "lucide-react";

import {
  api,
  type BankDirectoryEntry,
  type Connection,
} from "@/api/client";
import { Button, Input, Select, Textarea } from "@/components/ui";
import { resolveBankBrand } from "@/lib/bankBrands";
import { AccountIcon } from "@/lib/icons";

export type Source =
  | "volksbank"
  | "trade_republic"
  | "binance"
  | "trading_212"
  | "coinbase";
export type Provider = Source | "generic_fints";

const EMPTY: Record<Provider, Record<string, string>> = {
  volksbank: { iban: "", user: "", pin: "" },
  generic_fints: {
    iban: "",
    user: "",
    pin: "",
    blz: "",
    endpoint: "",
    bank_name: "",
    bank_bic: "",
    bank_brand: "",
    customer_id: "",
    tan_medium: "",
  },
  trade_republic: { phone: "", pin: "" },
  binance: { api_key: "", api_secret: "" },
  trading_212: { api_key: "", api_secret: "" },
  coinbase: { api_key: "", api_secret: "" },
};

export function sourceForProvider(provider: Provider): Source {
  return provider === "generic_fints" ? "volksbank" : provider;
}

export function secretFields(
  provider: Provider,
  t: (key: string) => string,
): [string, string, boolean][] {
  if (provider === "volksbank") {
    return [
      ["iban", t("connections.fints.iban"), false],
      ["user", t("connections.fints.userGeneric"), false],
      ["pin", t("connections.fints.pin"), true],
    ];
  }
  if (provider === "generic_fints") {
    return [
      ["iban", t("connections.fints.iban"), false],
      ["user", t("connections.fints.userGeneric"), false],
      ["pin", t("connections.fints.pin"), true],
      ["customer_id", `${t("connections.fints.customerId")} (${t("common.optional")})`, false],
      ["tan_medium", `${t("connections.fints.tanMedium")} (${t("common.optional")})`, false],
    ];
  }
  if (provider === "binance") {
    return [
      ["api_key", t("connections.binance.apiKey"), true],
      ["api_secret", t("connections.binance.apiSecret"), true],
    ];
  }
  if (provider === "trading_212") {
    return [
      ["api_key", t("connections.trading212.apiKey"), true],
      ["api_secret", t("connections.trading212.apiSecret"), true],
    ];
  }
  if (provider === "coinbase") {
    return [
      ["api_key", t("connections.coinbase.apiKey"), true],
      ["api_secret", t("connections.coinbase.apiSecret"), true],
    ];
  }
  return [
    ["phone", t("connections.tr.phone"), false],
    ["pin", t("connections.tr.pin"), true],
  ];
}

export function fieldLabel(key: string, t: (key: string) => string): string {
  const labels: Record<string, string> = {
    blz: t("connections.fints.blz"),
    iban: t("connections.fints.iban"),
    user: t("connections.fints.userGeneric"),
    endpoint: t("connections.fints.endpoint"),
    bank_name: t("connections.fints.bank"),
    bank_bic: "BIC",
    tan_medium: t("connections.fints.tanMedium"),
    customer_id: t("connections.fints.customerId"),
    phone: t("connections.tr.phone"),
    api_key: t("connections.binance.apiKey"),
  };
  return labels[key] || key;
}

export function fieldHint(key: string, t: (key: string) => string): string | null {
  if (key === "user") return t("connections.fints.userHint");
  if (key === "customer_id") return t("connections.fints.customerIdHint");
  if (key === "tan_medium") return t("connections.fints.tanMediumHint");
  return null;
}

export function FieldHint({ children }: { children: string }) {
  return (
    <div className="flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground">
      <CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <p>{children}</p>
    </div>
  );
}

type ConnectionFormProps = {
  onCreated: (connection: Connection, syncQueued: boolean) => void | Promise<void>;
};

export function ConnectionForm({ onCreated }: ConnectionFormProps) {
  const { t } = useTranslation();
  const [provider, setProvider] = useState<Provider>("generic_fints");
  const [name, setName] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({
    ...EMPTY.generic_fints,
  });
  const [historyFrom, setHistoryFrom] = useState("");
  const [bankQuery, setBankQuery] = useState("");
  const [bankResults, setBankResults] = useState<BankDirectoryEntry[]>([]);
  const [selectedBank, setSelectedBank] = useState<BankDirectoryEntry | null>(null);
  const [bankLoading, setBankLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const query = bankQuery.trim();
    if (provider !== "generic_fints" || query.length < 3) {
      setBankResults([]);
      setBankLoading(false);
      return;
    }
    if (selectedBank && query === selectedBank.name) {
      setBankLoading(false);
      return;
    }
    let active = true;
    const timeout = window.setTimeout(() => {
      setBankLoading(true);
      api.searchBanks(query)
        .then((result) => {
          if (active) setBankResults(result.items);
        })
        .catch((err: Error) => {
          if (active) setError(err.message);
        })
        .finally(() => {
          if (active) setBankLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [bankQuery, provider, selectedBank]);

  const changeProvider = (value: Provider) => {
    setProvider(value);
    setSecrets({ ...EMPTY[value] });
    setSelectedBank(null);
    setBankQuery("");
    setBankResults([]);
    setError(null);
    setName(
      value === "trade_republic"
        ? "Trade Republic"
        : value === "binance"
          ? "Binance"
          : value === "trading_212"
            ? "Trading 212"
            : value === "coinbase"
              ? "Coinbase"
              : "",
    );
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (provider === "generic_fints" && !selectedBank) {
      setError(t("connections.fints.bankRequired"));
      return;
    }
    setSaving(true);
    try {
      const connection = await api.createConnection({
        source: sourceForProvider(provider),
        provider,
        name,
        secrets,
      });
      let syncQueued = false;
      try {
        await api.triggerSync({
          connection_id: connection.id,
          mode: "backfill",
          history_from: historyFrom || "1970-01-01",
        });
        syncQueued = true;
      } catch {
        // The connection is still usable when its first sync cannot be queued.
      }
      await onCreated(connection, syncQueued);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("connections.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const fields = secretFields(provider, t);
  const formReady = provider !== "generic_fints" || selectedBank !== null;

  return (
    <form className="space-y-5" onSubmit={submit}>
      <section className="space-y-4 rounded-2xl bg-muted/20 p-4">
        <div className="space-y-1">
          <h4 className="text-sm font-semibold">{t("connections.providerSection")}</h4>
          <p className="text-xs text-muted-foreground">{t("connections.providerHint")}</p>
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium">{t("connections.bankProvider")}</label>
          <Select
            value={provider}
            onChange={(event) => changeProvider(event.target.value as Provider)}
          >
            <option value="generic_fints">{t("connections.providers.generic_fints")}</option>
            <option value="trade_republic">{t("connections.providers.trade_republic")}</option>
            <option value="binance">{t("connections.providers.binance")}</option>
            <option value="trading_212">{t("connections.providers.trading_212")}</option>
            <option value="coinbase">{t("connections.providers.coinbase")}</option>
          </Select>
          <p className="text-xs text-muted-foreground">
            {t(`connections.sourceHint.${provider}`)}
          </p>
        </div>

        {provider === "generic_fints" && (
          <div className="space-y-2">
            <label className="text-sm font-medium">{t("connections.fints.bank")}</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                className="pl-9 pr-9"
                value={bankQuery}
                placeholder={t("connections.fints.bankSearch")}
                onChange={(event) => {
                  setBankQuery(event.target.value);
                  setSelectedBank(null);
                }}
                autoComplete="off"
              />
              {bankLoading && (
                <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" aria-hidden />
              )}
            </div>
            {selectedBank && (
              <div className="flex items-center gap-2 rounded-xl border border-border/55 bg-background/30 px-3 py-2 text-sm">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-muted/60">
                  <AccountIcon
                    source="volksbank"
                    provider="generic_fints"
                    bankBrand={secrets.bank_brand}
                    bankName={selectedBank.name}
                    bic={selectedBank.bic || undefined}
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{selectedBank.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {selectedBank.location || selectedBank.blz} · {selectedBank.blz}
                  </span>
                </span>
                <Check className="h-4 w-4 shrink-0 text-accent" aria-hidden />
              </div>
            )}
            {!selectedBank && bankResults.length > 0 && (
              <div className="max-h-56 overflow-y-auto rounded-xl border border-border/55 bg-card/95 p-1 shadow-lg">
                {bankResults.map((bank) => (
                  <button
                    key={`${bank.blz}-${bank.name}`}
                    type="button"
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-muted/70"
                    onClick={() => {
                      const brand = resolveBankBrand({ name: bank.name, bic: bank.bic });
                      setSelectedBank(bank);
                      setBankQuery(bank.name);
                      setName(bank.name);
                      setBankResults([]);
                      setSecrets((current) => ({
                        ...current,
                        blz: bank.blz,
                        endpoint: bank.pinTanAddress || "",
                        bank_name: bank.name,
                        bank_bic: bank.bic || "",
                        bank_brand: brand?.id || "",
                      }));
                    }}
                  >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-muted/60">
                      <AccountIcon
                        source="volksbank"
                        provider="generic_fints"
                        bankName={bank.name}
                        bic={bank.bic || undefined}
                      />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{bank.name}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {bank.location || t("connections.fints.locationUnknown")} · {bank.blz}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            )}
            <FieldHint>{t("connections.fints.bankHint")}</FieldHint>
          </div>
        )}

        {formReady && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium">{t("connections.name")}</label>
            <Input value={name} onChange={(event) => setName(event.target.value)} required />
          </div>
        )}
      </section>

      {formReady && (
        <section className="space-y-4 rounded-2xl bg-muted/20 p-4">
          <div className="space-y-1">
            <h4 className="text-sm font-semibold">
              {provider === "generic_fints" || provider === "volksbank"
                ? t("connections.onlineBankingCredentials")
                : t("connections.credentials")}
            </h4>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {t("connections.credentialsHint")}
            </p>
          </div>
          <div className="grid gap-4">
            {fields.map(([key, label, secret]) => (
              <div key={key} className="space-y-2">
                <label className="block text-sm font-medium">{label}</label>
                {provider === "coinbase" && key === "api_secret" ? (
                  <Textarea
                    className="min-h-32 font-mono text-xs"
                    autoComplete="off"
                    value={secrets[key] || ""}
                    onChange={(event) =>
                      setSecrets((current) => ({ ...current, [key]: event.target.value }))
                    }
                    required
                  />
                ) : (
                  <Input
                    type={secret ? "password" : "text"}
                    autoComplete="off"
                    value={secrets[key] || ""}
                    onChange={(event) =>
                      setSecrets((current) => ({ ...current, [key]: event.target.value }))
                    }
                    required={key !== "customer_id" && key !== "tan_medium"}
                  />
                )}
                {fieldHint(key, t) && (
                  <FieldHint>{fieldHint(key, t) as string}</FieldHint>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {formReady && provider !== "binance" && provider !== "coinbase" && (
        <section className="space-y-3 rounded-2xl bg-muted/20 p-4">
          <div className="space-y-1">
            <h4 className="text-sm font-semibold">{t("connections.syncSection")}</h4>
            <p className="text-xs text-muted-foreground">{t("accounts.historyFromHint")}</p>
          </div>
          <label className="block space-y-2 text-sm font-medium">
            <span>{t("accounts.historyFrom")} ({t("common.optional")})</span>
            <Input
              type="date"
              value={historyFrom}
              onChange={(event) => setHistoryFrom(event.target.value)}
            />
          </label>
        </section>
      )}

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex justify-end border-t border-border/40 pt-4">
        <Button
          type="submit"
          className="min-h-11 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!formReady || saving}
        >
          {saving ? t("common.loading") : t("connections.save")}
        </Button>
      </div>
    </form>
  );
}
