# demo-data/

Reserved for later sessions to drop sample documents (PDFs, DOCX, etc.)
that the worker can scan/parse/index once that logic is implemented.

S1 does not read anything from this directory -- every S1 API response is
either a fixture defined in `api/fixtures.py` or comes from the (empty,
freshly-initialized) SQLite database. Real files placed here are ignored
by git (see `.gitignore`) since they may be personal documents.
