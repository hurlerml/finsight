import type { LucideIcon } from "lucide-react";
import {
  Car,
  CircleDollarSign,
  CircleEllipsis,
  Clapperboard,
  CreditCard,
  GraduationCap,
  HeartPulse,
  House,
  Landmark,
  PiggyBank,
  Plane,
  Repeat2,
  ShoppingBag,
  ShoppingBasket,
  Users,
  Utensils,
  Wallet,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { bankInitials, resolveBankBrand } from "@/lib/bankBrands";

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  housing: House,
  groceries: ShoppingBasket,
  dining: Utensils,
  mobility: Car,
  health: HeartPulse,
  subscriptions: Repeat2,
  shopping: ShoppingBag,
  leisure: Clapperboard,
  travel: Plane,
  family: Users,
  education: GraduationCap,
  savings: PiggyBank,
  finance: Landmark,
  income: CircleDollarSign,
  other: CircleEllipsis,
  house: House,
  basket: ShoppingBasket,
  utensils: Utensils,
  car: Car,
  heart: HeartPulse,
  repeat: Repeat2,
  bag: ShoppingBag,
  culture: Clapperboard,
  plane: Plane,
  users: Users,
};

export function categoryIconForSlug(slug: string): LucideIcon {
  return CATEGORY_ICONS[slug] || CircleEllipsis;
}

export function CategoryIcon({ slug, icon, className }: { slug: string; icon?: string; className?: string }) {
  const Icon = categoryIconForSlug(icon || slug);
  return <Icon className={cn("h-3.5 w-3.5 shrink-0", className)} aria-hidden />;
}

// Trade Republic's standalone mark. Official-source logo geometry is documented at
// https://commons.wikimedia.org/wiki/File:Trade_Republic_logo_2021.svg (trademark applies).
function TradeRepublicIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 512 512"
      className={cn("h-4 w-4 shrink-0", className)}
      fill="currentColor"
      aria-hidden
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M168.7 71.3 0 126v156.7L168.7 228c13.3-4 27.3-4 40.7.7l62 21.3c13.3 4.7 27.3 4.7 40.7.7L511.3 196V39.3L312 94c-13.3 4-27.3 4-40.7-.7l-62-21.3c-12.6-4-27.3-4.7-40.6-.7m0 190L0 316v156.7L168.7 418c13.3-4 27.3-4 40.7.7l62 21.3c13.3 4.7 27.3 4.7 40.7.7L512 386V229.3L312.7 284c-13.3 4-27.3 4-40.7-.7L210 262c-13.3-4-28-4.7-41.3-.7"
      />
    </svg>
  );
}

function VolksbankIcon({ className }: { className?: string }) {
  return (
    <img
      src="/brands/volksbank.svg"
      className={cn("h-5 w-5 shrink-0 object-contain", className)}
      alt=""
      aria-hidden
    />
  );
}

function BinanceIcon({ className }: { className?: string }) {
  // Path from Simple Icons (CC0 1.0); the Binance name/mark remains a trademark.
  // It is used here only as a factual connected-provider indicator.
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("h-5 w-5 shrink-0", className)}
      fill="#F0B90B"
      aria-hidden
    >
      <path d="m16.624 13.92 2.717 2.716-7.353 7.353-7.352-7.352 2.717-2.717 4.636 4.66 4.635-4.66Zm4.637-4.636L24 12l-2.715 2.716L18.568 12l2.693-2.716Zm-9.272 0 2.716 2.692-2.717 2.717L9.272 12l2.716-2.715Zm-9.273 0L5.41 12l-2.692 2.692L0 12l2.716-2.716ZM11.99.01l7.352 7.33-2.717 2.715-4.636-4.636-4.635 4.66-2.717-2.716L11.989.011Z" />
    </svg>
  );
}

function CoinbaseIcon({ className }: { className?: string }) {
  return (
    <img
      src="/brands/coinbase.svg"
      className={cn("h-5 w-5 shrink-0 object-contain", className)}
      alt=""
      aria-hidden
    />
  );
}

function Trading212Icon({ className }: { className?: string }) {
  return (
    <img
      src="/brands/trading212.svg"
      className={cn("h-5 w-5 shrink-0 object-contain", className)}
      alt=""
      aria-hidden
    />
  );
}

export function AccountIcon({
  source,
  provider,
  accountType,
  bankBrand,
  bankName,
  bic,
  className,
}: {
  source?: string;
  provider?: string;
  accountType?: string;
  bankBrand?: string;
  bankName?: string;
  bic?: string;
  className?: string;
}) {
  if (source === "trade_republic") {
    return <TradeRepublicIcon className={className} />;
  }
  if (source === "binance") return <BinanceIcon className={className} />;
  if (source === "trading_212") return <Trading212Icon className={className} />;
  if (source === "coinbase") return <CoinbaseIcon className={className} />;
  if (source === "volksbank") {
    const brand = resolveBankBrand({
      brand: bankBrand || (provider !== "generic_fints" ? "volksbank" : undefined),
      name: bankName,
      bic,
    });
    if (brand?.asset) {
      return (
        <img
          src={brand.asset}
          className={cn("h-5 w-5 shrink-0 object-contain", className)}
          alt=""
          aria-hidden
        />
      );
    }
    if (brand || bankName) {
      return (
        <span
          className={cn("inline-flex h-5 min-w-5 shrink-0 items-center justify-center text-[0.52rem] font-bold leading-none", className)}
          aria-hidden
        >
          {brand?.fallback || bankInitials(bankName)}
        </span>
      );
    }
    if (provider !== "generic_fints") return <VolksbankIcon className={className} />;
  }
  let Icon: LucideIcon = Landmark;
  if (accountType === "broker_cash") Icon = PiggyBank;
  else if (accountType === "card") Icon = CreditCard;
  else if (accountType === "wallet") Icon = Wallet;
  return <Icon className={cn("h-4 w-4 shrink-0", className)} aria-hidden />;
}
