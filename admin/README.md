# IRA admin console

The console served at `/admin`: React 18, TypeScript and Vite, no UI kit. It
talks to the server's `/v1` API with the session cookie and shares
`src/ira/web/static/tokens.css` with the Ira app, so both surfaces have one
palette, type scale and spacing. Use Node 22 (`nvm use`), then `npm ci`.

- `npm run dev` starts Vite at http://127.0.0.1:5173/admin/ and proxies `/v1`
  to a server on port 8790 (`ira serve --port 8790`).
- `npm run typecheck` and `npm test -- --run` check the code and the lib tests.
- `npm run build` writes the bundle to `src/ira/web/admin/`, which is committed
  so that `pip install` works without Node. The server serves `index.html` for
  any `/admin` route without a file extension, so deep links need no 404 page.
- `npm run api:types` regenerates `src/api/schema.d.ts` from `openapi.json`;
  refresh that snapshot from a running server's `/v1/openapi.json` first.
