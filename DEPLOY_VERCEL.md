# Deploy to Vercel

## 1) Install and login

```powershell
npm i -g vercel
vercel login
```

## 2) Set environment variables in Vercel

You must set these in your Vercel project settings:

- `SESSION_SECRET`: any long random string

If your app must use MySQL features (vehicle filters/registry sync), also set:

- `MYSQL_HOST`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`

## 3) Update config.json for production

The app reads `config.json` at runtime. Make sure production URLs and secrets are correct.

Important: `config.json` currently contains sensitive secrets. Move secrets to Vercel Environment Variables and avoid committing real credentials.

## 4) Deploy

Run from project root:

```powershell
vercel
```

For production deployment:

```powershell
vercel --prod
```

## Notes

- This deployment uses Python serverless runtime via `api/index.py`.
- The app is cookie-authenticated using a signed session token (`SESSION_SECRET`).
- Long-running jobs may hit serverless timeouts if many vehicles are requested at once.
