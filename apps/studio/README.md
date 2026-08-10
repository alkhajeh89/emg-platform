# EMG Studio pilot

The first runnable Studio surface. The browser uses only the same-origin `/bff` path, which Next.js
rewrites to the existing Studio BFF. Authentication and delegated credentials remain server-side.

## Local development

```bash
cp apps/studio/.env.example apps/studio/.env.local
npm run dev --workspace @emg/studio
```

Open <http://localhost:3000>. The Studio BFF and its dependencies must already be running.
