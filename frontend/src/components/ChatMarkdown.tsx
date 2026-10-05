import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const REMARK_PLUGINS = [remarkGfm];

function stableMarkdownPrefix(text: string): string {
  let stableEnd = 0;
  let offset = 0;
  let fence: { character: "`" | "~"; length: number } | null = null;

  for (const segment of text.matchAll(/.*(?:\n|$)/g)) {
    const line = segment[0];
    if (!line) continue;
    const content = line.endsWith("\n") ? line.slice(0, -1) : line;
    const marker = content.match(/^ {0,3}(`{3,}|~{3,})/);
    if (marker) {
      const character = marker[1][0] as "`" | "~";
      if (fence === null) fence = { character, length: marker[1].length };
      else if (fence.character === character && marker[1].length >= fence.length) fence = null;
    }
    offset += line.length;
    if (fence === null && content.trim() === "") stableEnd = offset;
  }

  return text.slice(0, stableEnd);
}

function ChatMarkdown({
  text,
  streaming = false,
}: {
  text: string;
  streaming?: boolean;
}) {
  const renderedText = useMemo(
    () => (streaming ? stableMarkdownPrefix(text) : text),
    [streaming, text]
  );

  return (
    <>
      {renderedText && (
        <ReactMarkdown
          skipHtml
          disallowedElements={["img"]}
          remarkPlugins={REMARK_PLUGINS}
          components={{
            h1: ({ children }) => <h1 className="mb-2 mt-3 text-base font-semibold first:mt-0">{children}</h1>,
            h2: ({ children }) => <h2 className="mb-1.5 mt-3 text-[0.95rem] font-semibold first:mt-0">{children}</h2>,
            h3: ({ children }) => <h3 className="mb-1 mt-2.5 text-sm font-semibold first:mt-0">{children}</h3>,
            p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
            ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
            ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
            li: ({ children }) => <li className="pl-0.5">{children}</li>,
            strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
            blockquote: ({ children }) => (
              <blockquote className="my-2 border-l-2 border-current/25 pl-3 opacity-80">
                {children}
              </blockquote>
            ),
            a: ({ href, children }) => (
              <a
                href={href}
                target="_blank"
                rel="noreferrer noopener"
                className="font-medium underline decoration-current/35 underline-offset-2 hover:decoration-current"
              >
                {children}
              </a>
            ),
            code: ({ className, children }) => {
              const block = Boolean(className) || String(children).includes("\n");
              return (
                <code className={block ? "font-mono text-xs" : "rounded bg-foreground/10 px-1 py-0.5 font-mono text-[0.82em]"}>
                  {children}
                </code>
              );
            },
            pre: ({ children }) => (
              <pre className="my-2 max-w-full overflow-x-auto rounded-xl bg-slate-950/90 p-3 text-slate-100">
                {children}
              </pre>
            ),
            table: ({ children }) => (
              <div className="my-2 max-w-full overflow-x-auto rounded-xl border border-border/45">
                <table className="w-full min-w-max border-collapse text-xs">{children}</table>
              </div>
            ),
            th: ({ children }) => (
              <th className="border-b border-border/55 bg-foreground/5 px-2.5 py-2 text-left font-semibold">
                {children}
              </th>
            ),
            td: ({ children }) => <td className="border-b border-border/30 px-2.5 py-2">{children}</td>,
            hr: () => <hr className="my-3 border-current/15" />,
          }}
        >
          {renderedText}
        </ReactMarkdown>
      )}
      {streaming && (
        <span
          aria-hidden="true"
          className="ml-1 inline-block h-3.5 w-1 animate-pulse rounded-full bg-current/45 align-middle"
        />
      )}
    </>
  );
}

export default memo(ChatMarkdown);
