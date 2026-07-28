# Deploy on Railway (with MySQL)

## 1) Create project from GitHub

1. Open Railway dashboard.
2. Click New Project -> Deploy from GitHub repo.
3. Select your repo: `millenialglobetrotter/fleet_analysis_vld_da`.
4. Railway will detect Python and build from `requirements.txt`.

## 2) Add MySQL service

1. In the same Railway project, click New -> Database -> MySQL.
2. Railway will create a MySQL service and inject connection variables.

## 3) Environment variables for app service

Set these in your app service Variables tab:

- `PORT`: Railway provides this automatically.
- `DATABASE_URL`: optional, preferred if present.

If `DATABASE_URL` is not available, set these (Railway style):

- `MYSQLHOST`
- `MYSQLPORT`
- `MYSQLUSER`
- `MYSQLPASSWORD`
- `MYSQLDATABASE`

App-level secret:

- `SESSION_SECRET`: long random string (32+ chars).

## 4) Run deploy

- Push to `main` branch.
- Railway auto-deploys on push.

## 5) Open app

- In Railway app service, click Generate Domain.
- Open the generated URL.

## Notes

- This app now binds to `PORT` from environment.
- DB connection prefers `DATABASE_URL`, then falls back to `MYSQL*` variables.
- If DB connection fails, verify app and MySQL are in the same Railway project and variables are present in the app service.
