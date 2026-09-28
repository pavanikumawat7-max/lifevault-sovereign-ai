// Run with: npm test   (from ui/)
import test from "node:test";
import assert from "node:assert/strict";

import {
  assistantMessageFromResponse,
  citationDisplay,
  fileNameFromPath,
  toRequestHistory,
} from "../src/utils/citations.js";

// Shaped exactly like api/schemas.py::Citation.
const FULL = {
  document_hash: "abc123",
  chunk_id: 7,
  quote: "  The access code is MAPLE-7394.  ",
  path: "C:\\Users\\me\\Documents\\notes\\code.pdf",
  page: 2,
  also_found_at: ["D:\\backup\\code.pdf"],
  label: "C1",
};

test("fileNameFromPath handles POSIX, Windows and empty paths", () => {
  assert.equal(fileNameFromPath("/vault/folder_A/dell_warranty.pdf"), "dell_warranty.pdf");
  assert.equal(fileNameFromPath("C:\\Users\\me\\code.pdf"), "code.pdf");
  assert.equal(fileNameFromPath("/vault/folder/"), "folder");
  assert.equal(fileNameFromPath(""), "");
  assert.equal(fileNameFromPath(null), "");
  assert.equal(fileNameFromPath(undefined), "");
});

test("citationDisplay surfaces filename, page, quote, label and other locations", () => {
  const d = citationDisplay(FULL, 0);
  assert.equal(d.fileName, "code.pdf");
  assert.equal(d.path, FULL.path);
  assert.equal(d.page, 2);
  assert.equal(d.quote, "The access code is MAPLE-7394."); // trimmed
  assert.equal(d.label, "C1");
  assert.deepEqual(d.alsoFoundAt, ["D:\\backup\\code.pdf"]);
});

test("citationDisplay does not invent fields the backend omitted", () => {
  // Only the guaranteed fields (document_hash, quote) are present.
  const d = citationDisplay({ document_hash: "abc123", quote: "" }, 3);
  assert.equal(d.page, null);
  assert.equal(d.path, null);
  assert.equal(d.label, null);
  assert.equal(d.quote, "");
  assert.deepEqual(d.alsoFoundAt, []);
  assert.equal(d.fileName, "Unknown file");
});

test("citationDisplay rejects a non-positive or non-integer page", () => {
  for (const bad of [0, -1, 1.5, "2", null, undefined]) {
    assert.equal(citationDisplay({ ...FULL, page: bad }).page, null, `page=${String(bad)}`);
  }
});

test("citationDisplay keys are unique for repeated citations of one chunk", () => {
  const a = citationDisplay(FULL, 0);
  const b = citationDisplay(FULL, 1);
  assert.notEqual(a.key, b.key);
});

test("assistantMessageFromResponse keeps answer, citations and grounding info", () => {
  const msg = assistantMessageFromResponse({
    conversation_id: "conv-1",
    answer: "The code is MAPLE-7394 [C1].",
    citations: [FULL],
    grounded: true,
    verification_reason: null,
    model: "fixture",
  });
  assert.equal(msg.role, "assistant");
  assert.equal(msg.content, "The code is MAPLE-7394 [C1].");
  assert.deepEqual(msg.citations, [FULL]);
  assert.equal(msg.grounded, true);
  assert.equal(msg.verificationReason, null);
  assert.equal(msg.model, "fixture");
});

test("assistantMessageFromResponse tolerates a response with no citations", () => {
  const msg = assistantMessageFromResponse({
    answer: "I could not verify an answer.",
    grounded: false,
    verification_reason: "no documents were retrieved for this question",
  });
  assert.deepEqual(msg.citations, []);
  assert.equal(msg.grounded, false);
  assert.equal(msg.verificationReason, "no documents were retrieved for this question");
});

test("assistantMessageFromResponse drops malformed citation entries", () => {
  const msg = assistantMessageFromResponse({
    answer: "x",
    citations: [FULL, null, "oops", 42],
  });
  assert.deepEqual(msg.citations, [FULL]);
});

test("toRequestHistory sends only role and content", () => {
  const assistant = assistantMessageFromResponse({ answer: "hi", citations: [FULL], grounded: true });
  const out = toRequestHistory([{ role: "user", content: "hello" }, assistant]);
  assert.deepEqual(out, [
    { role: "user", content: "hello" },
    { role: "assistant", content: "hi" },
  ]);
});
