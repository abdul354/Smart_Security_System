# Deploy Smart Security System Live

This guide walks you through making your app live on the web in ~10 minutes using **Render** (recommended), **Railway**, or **Fly.io**.

---

## TL;DR – Render (fastest)

1. Push this repo to GitHub (if not already)
2. Go to https://render.com → **New +** → **Blueprint**
3. Select your GitHub repo → **Apply**
4. In Render dashboard, go to **Environment** → add these as **Secrets**:
   - `BASIC_AUTH_USER` = your username
   - `BASIC_AUTH_PASSWORD` = your password
   - (Optional) `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GROQ_API_KEY`
   - (Optional) `CAMERA_SRC` = `rtsp://your-ip-camera-url` (or leave as `disabled`)
5. Deploy completes in ~2–3 min. Visit your app URL.

---

## Pre-Deploy Checklist

### 1. GitHub
- [ ] Repo is on GitHub (public or private)
- [ ] No `.env` file is committed (it's in `.gitignore`)

### 2. Secrets you'll need in your hosting dashboard
Pick which ones apply to your setup:

| Env Var | What It Is | Example | Required? |
|---------|-----------|---------|-----------|
| `BASIC_AUTH_USER` | Username for web login | `admin` | **Highly recommended** |
| `BASIC_AUTH_PASSWORD` | Password for web login | `mysecurepass123` | **Highly recommended** |
| `SUPABASE_URL` | Your Supabase project URL | `https://xyz.supabase.co` | If using Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key | `eyJ...` | If using Supabase |
| `GROQ_API_KEY` | Groq API key for chatbot | `gsk_...` | If using chatbot |
| `CAMERA_SRC` | Camera/stream source | `0`, `rtsp://...`, or `disabled` | Optional (default: `disabled`) |

**Important:** If you deployed to cloud without setting `CAMERA_SRC`, video won't work until you set it. That's OK—other endpoints work fine.

### 3. Camera: Local vs. Cloud
- **Local dev:** `CAMERA_SRC=0` (your laptop webcam, default in `.env.example`)
- **Cloud deploy:** Use an **IP camera / NVR / RTSP stream** (cloud servers don't have webcams)
  - Example: `CAMERA_SRC=rtsp://admin:pass@192.168.1.100:554/stream`
  - Or disable video: `CAMERA_SRC=disabled`

---

## Detailed Steps by Platform

### **Render (Recommended)**

#### Step 1: Prepare GitHub
```bash
# Make sure you have Git and your repo is on GitHub
git status
git add .
git commit -m "Deploy: add Docker + env template"
git push origin main
```

#### Step 2: Connect Render
1. Go to https://render.com (sign up if needed)
2. Click **New +** → **Blueprint**
3. Authorize GitHub
4. Select your repo
5. Confirm the settings (should auto-read `render.yaml`)
6. Click **Apply**

#### Step 3: Add Secrets
1. Render dashboard → Your service → **Environment**
2. Add these as **Secret** (not Regular):
   ```
   BASIC_AUTH_USER=admin
   BASIC_AUTH_PASSWORD=your_secure_password
   ```
   (Add others if you use Supabase/Groq/camera)
3. Save

#### Step 4: Monitor Deploy
- Render builds your Docker image automatically
- Check **Logs** tab to see progress
- Once "Build successful", your app is live at the provided URL

#### Step 5: Use Your App
- Open your app's public URL
- Log in with your `BASIC_AUTH_USER` + `BASIC_AUTH_PASSWORD`
- Video feed will show "Camera disabled" until you set `CAMERA_SRC`

---

### **Railway**

#### Step 1: Push to GitHub (same as Render)

#### Step 2: Connect Railway
1. Go to https://railway.app (sign up if needed)
2. **New Project** → **Deploy from GitHub**
3. Authorize GitHub, select your repo
4. Railway auto-detects the Docker setup

#### Step 3: Set Environment Variables
1. Project dashboard → **Variables**
2. Add your secrets:
   ```
   BASIC_AUTH_USER=admin
   BASIC_AUTH_PASSWORD=your_secure_password
   TRUST_PROXY=1
   CAMERA_SRC=disabled
   ```

#### Step 4: Deploy
- Railway builds and deploys automatically
- Check **Deployments** tab for logs
- Your app URL appears in the top-right

---

### **Fly.io**

#### Step 1: Install Fly CLI
```bash
# Windows PowerShell
choco install flyctl
```

#### Step 2: Create Fly App
```bash
fly auth login
fly launch --image {{DOCKER_REGISTRY}}/smart-security --no-deploy
```
Follow the prompts.

#### Step 3: Set Secrets
```bash
fly secrets set BASIC_AUTH_USER=admin
fly secrets set BASIC_AUTH_PASSWORD=your_secure_password
fly secrets set TRUST_PROXY=1
fly secrets set CAMERA_SRC=disabled
```

#### Step 4: Deploy
```bash
fly deploy
```

---

## After Deploy: Verify It Works

### Health Check
Open your app URL + `/health`:
```
https://your-app.render.com/health
```
Should return:
```json
{"status": "ok"}
```

### Video Feed (will fail if camera disabled)
```
https://your-app.render.com/video_feed
```
- If `CAMERA_SRC=disabled`: Returns HTTP 503 with clear message.
- If `CAMERA_SRC=0` in cloud: Will fail (no webcam on server).
- If `CAMERA_SRC=rtsp://...`: Should stream video.

### Login
```
https://your-app.render.com/
```
Should prompt for your `BASIC_AUTH_USER` + `BASIC_AUTH_PASSWORD`.

---

## Common Issues & Fixes

### "Camera disabled" on video feed
**Problem:** You set `CAMERA_SRC=disabled` or didn't set it.
**Fix:** In your hosting dashboard, set `CAMERA_SRC` to:
- Local: `0` (or `1`, `2`... for multiple webcams)
- Cloud: `rtsp://...` URL or `disabled` if you don't need video

### 503 "Camera unavailable" on video feed
**Problem:** The RTSP URL is wrong or the camera is offline.
**Fix:** Test the RTSP URL locally:
```bash
ffplay "rtsp://admin:pass@192.168.1.100:554/stream"
```

### App won't start (logs show "import failed")
**Problem:** Missing dependency in `requirements.txt`.
**Fix:** Add it, commit, and re-deploy:
```bash
pip install <package>
pip freeze > requirements.txt
git add requirements.txt && git commit -m "Add dependency" && git push
```

### 401 Unauthorized
**Problem:** Wrong username/password.
**Fix:** Check your `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD` in the dashboard.

---

## Optional: Use a Custom Domain

### Render
1. Dashboard → Your service → **Settings**
2. **Custom Domain** → add your domain (e.g., `security.yourdomain.com`)
3. Update your DNS records (Render provides CNAME)

### Railway
1. Dashboard → Your service → **Settings**
2. **Custom Domain** → add your domain
3. Update DNS CNAME

### Fly.io
```bash
fly ips allocate-v4
fly certs create yourdomain.com
# Update DNS CNAME to <app-name>.fly.dev
```

---

## Production Tips

1. **Always use HTTPS** – Your hosting platform handles this automatically.
2. **Rotate credentials regularly** – Update `BASIC_AUTH_PASSWORD` in your dashboard every 90 days.
3. **Monitor logs** – Check your platform's log viewer for errors.
4. **Use Supabase for attendance records** – Local CSVs work but won't sync across multiple deployments.
5. **Set up alerts** – Most platforms offer email alerts for deploy failures.

---

## Next Steps

- [ ] Push to GitHub
- [ ] Pick a platform (Render is fastest)
- [ ] Add secrets to the dashboard
- [ ] Deploy
- [ ] Test `/health` + `/` login page
- [ ] Set `CAMERA_SRC` if you have an IP camera
- [ ] Share the URL!

---

## Support

If your app won't start:
1. Check the platform's **Logs** tab
2. Ensure all required `.env` vars are set
3. Verify your Docker image builds locally: `docker compose up --build`
4. Re-check syntax in `render.yaml` / `railway.json` / etc.

Good luck! 🚀
