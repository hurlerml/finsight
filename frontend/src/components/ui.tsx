import { cn } from "@/lib/utils";

export function Card({
  className,
  children,
  onClick,
}: {
  className?: string;
  children: React.ReactNode;
  onClick?: React.MouseEventHandler<HTMLDivElement>;
}) {
  return (
    <div
      className={cn(
        "glass-surface rounded-[1.65rem] p-5",
        className,
      )}
      onClick={onClick}
    >
      {children}
    </div>
  );
}

export function Button({
  className,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "outline";
}) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-xl px-4 py-2 text-sm font-medium transition duration-200 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-sm disabled:active:scale-100",
        variant === "primary" && "bg-primary text-primary-foreground shadow-sm shadow-black/10 hover:-translate-y-px hover:shadow-md",
        variant === "ghost" && "hover:bg-muted/60 text-foreground",
        variant === "outline" &&
          "border border-white/50 bg-card/35 text-card-foreground shadow-[inset_0_1px_0_hsl(var(--glass-highlight))] backdrop-blur-xl hover:bg-card/60",
        className
      )}
      {...props}
    />
  );
}

export function Select({
  className,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "form-control h-10 w-full px-3 py-2 text-sm",
        className
      )}
      {...props}
    />
  );
}

export function Input({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "form-control h-10 w-full px-3 py-2 text-sm",
        className
      )}
      {...props}
    />
  );
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "form-control min-h-24 w-full resize-y px-3 py-2 text-sm",
        className
      )}
      {...props}
    />
  );
}

export function Badge({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full bg-muted/70 px-2.5 py-0.5 text-xs font-medium text-muted-foreground backdrop-blur-sm",
        className
      )}
    >
      {children}
    </span>
  );
}
