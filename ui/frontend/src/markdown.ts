import { marked, type Tokens } from "marked";

// Chat content comes from the LLM, which may repeat text from files in the
// workspace (prompt injection). Raw HTML is therefore escaped and only safe
// URL schemes are rendered as links/images, so model output cannot run script
// in the page, which has access to the terminal WebSocket.

marked.setOptions({
  gfm: true,
  breaks: true,
});

const SAFE_URL = /^(https?:|mailto:|#|\/|\.{0,2}\/|[^:]*$)/i;

function isSafeUrl(href: string | null | undefined): boolean {
  if (!href) return false;
  // Strip control characters and whitespace browsers ignore inside schemes.
  const normalized = href.replace(/[\x00-\x20\x7f]/g, "");
  return SAFE_URL.test(normalized);
}

marked.use({
  renderer: {
    code({ text, lang }: Tokens.Code) {
      const safeLang = (lang ?? "").match(/^[\w+#.-]+/)?.[0];
      const language = safeLang ? ` class="language-${escapeHtml(safeLang)}"` : "";
      return `<pre class="code-block"><code${language}>${escapeHtml(text)}</code></pre>`;
    },
    html({ text }: Tokens.HTML | Tokens.Tag) {
      return escapeHtml(text);
    },
    link(token: Tokens.Link) {
      if (!isSafeUrl(token.href)) {
        return this.parser.parseInline(token.tokens);
      }
      return false; // fall back to the default renderer
    },
    image(token: Tokens.Image) {
      if (!isSafeUrl(token.href)) {
        return escapeHtml(token.text);
      }
      return false;
    },
  },
});

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderMarkdown(content: string): string {
  if (!content) return "";
  return marked.parse(content, { async: false }) as string;
}
