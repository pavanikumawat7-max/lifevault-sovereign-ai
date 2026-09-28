// Run with: npm test   (from ui/)
// Server-render checks: no DOM needed, so no jsdom / testing-library.
import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Vite compiles the app's JSX with React's automatic runtime (no `React`
// import needed). This runner may use the classic transform instead, so
// expose React globally and import the components afterwards.
globalThis.React = React;
const { default: CitationList } = await import("../src/components/CitationList.jsx");
const { default: Chat } = await import("../src/pages/Chat.jsx");

const CITATION = {
  document_hash: "abc123",
  chunk_id: 7,
  quote: "The access code is MAPLE-7394.",
  path: "C:\\Users\\me\\Documents\\code.pdf",
  page: 2,
  also_found_at: ["D:\\backup\\code.pdf"],
  label: "C1",
};

test("CitationList shows filename, page, label, quote and other locations", () => {
  const html = renderToStaticMarkup(<CitationList citations={[CITATION]} />);
  assert.match(html, /Sources/);
  assert.match(html, />code\.pdf</);
  assert.match(html, /Page 2/);
  assert.match(html, />C1</);
  assert.match(html, /The access code is MAPLE-7394\./);
  assert.match(html, /Also found at: D:\\backup\\code\.pdf/);
  // Full path is available on hover.
  assert.match(html, /title="C:\\Users\\me\\Documents\\code\.pdf"/);
});

test("CitationList renders one card per citation", () => {
  const second = { ...CITATION, chunk_id: 8, label: "C2", page: 5, path: "/vault/other.pdf" };
  const html = renderToStaticMarkup(<CitationList citations={[CITATION, second]} />);
  assert.equal((html.match(/class="citation-card"/g) || []).length, 2);
  assert.match(html, />other\.pdf</);
  assert.match(html, /Page 5/);
});

test("CitationList omits page, quote and extra locations when not provided", () => {
  const html = renderToStaticMarkup(
    <CitationList citations={[{ document_hash: "h", quote: "", path: "/vault/a.pdf" }]} />
  );
  assert.match(html, />a\.pdf</);
  assert.doesNotMatch(html, /Page/);
  assert.doesNotMatch(html, /citation-card-quote/);
  assert.doesNotMatch(html, /Also found at/);
});

test("CitationList renders nothing without citations", () => {
  assert.equal(renderToStaticMarkup(<CitationList citations={[]} />), "");
  assert.equal(renderToStaticMarkup(<CitationList citations={undefined} />), "");
});

test("CitationList escapes quote text rather than injecting HTML", () => {
  const html = renderToStaticMarkup(
    <CitationList citations={[{ ...CITATION, quote: "<script>alert(1)</script>" }]} />
  );
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("Chat page no longer shows the stale S1 stub banner", () => {
  const html = renderToStaticMarkup(<Chat />);
  assert.doesNotMatch(html, /S1 stub/);
  assert.doesNotMatch(html, /no retrieval/i);
  assert.doesNotMatch(html, /Coming in S2/);
  assert.match(html, /Sources are listed under each answer/);
});
