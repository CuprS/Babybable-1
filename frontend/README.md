# Babybabel — mobile & web app

Expo (React Native + expo-router) client for Babybabel. See the root `README.md` for the full setup.

```bash
yarn install
EXPO_PUBLIC_BACKEND_URL=http://localhost:8001 npx expo start
```

- Screens live in `app/` (file-based routing); shared code in `src/`.
- `src/api.ts` wraps every backend call (`apiFetch`) and holds the shared TypeScript types.
- `yarn lint` runs ESLint.
