# Deploying the LSMS Agent to Hugging Face Spaces

Estimated time: **10–15 minutes**. You do this once. After that, updates are `git push`.

## Prerequisites you set up once

1. **A Hugging Face account** — sign up at <https://huggingface.co/join>.
2. **An Anthropic API key** — from <https://console.anthropic.com/settings/keys>.
3. **`git-lfs` installed locally** — for pushing the parquet catalog. Mac: `brew install git-lfs && git lfs install`.
4. **The catalog built locally** — run `make all-ingest` in this repo first. This produces `catalog/parquet/` (~417 MB) and `catalog/variables.parquet`. The Space needs these files.

## Step 1 — Create the Space

1. Go to <https://huggingface.co/new-space>.
2. **Space name**: `lsms-agent` (or whatever you like).
3. **License**: choose what you want (`mit` is fine).
4. **SDK**: select **Docker** → **Blank** template.
5. **Visibility**: pick **Public** (you said you want this) or **Private** if you'd rather start gated.
6. **Hardware**: free CPU tier (`cpu-basic`, 2 vCPU / 16 GB) is plenty for v0.
7. Click **Create Space**.

You'll land on the Space's page. Note the URL — it's `https://huggingface.co/spaces/<your-username>/lsms-agent` and the live app will be `https://<your-username>-lsms-agent.hf.space`.

## Step 2 — Clone the Space locally and copy the code in

```bash
# Replace <your-hf-username> with your actual HF handle
git clone https://huggingface.co/spaces/<your-hf-username>/lsms-agent hf-lsms
cd hf-lsms

# Copy everything from this repo EXCEPT raw data + .git
rsync -av --exclude='.git' --exclude='Country Data/' --exclude='.venv/' \
    "/Users/xiongcaizhen/Desktop/LSMS Automation/" ./

# Tell git-lfs to track the parquet files (HF gives you LFS for free)
git lfs install
git lfs track "catalog/parquet/**/*.parquet"
git lfs track "catalog/variables.parquet"
git add .gitattributes

# At the top of README.md you need an HF YAML header.  Prepend this manually:
#
#   ---
#   title: LSMS Agent
#   emoji: 📊
#   colorFrom: blue
#   colorTo: indigo
#   sdk: docker
#   app_port: 7860
#   pinned: false
#   ---
#
# (everything below the second --- stays as the existing README)

git add .
git commit -m "Initial deploy"
git push
```

The push takes 5–10 minutes because of LFS uploads. HF then automatically builds the Docker image and starts the Space.

## Step 3 — Set secrets in the HF UI

The app needs three secrets. Go to your Space → **Settings** → **Variables and secrets** → **New secret**:

| Name | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Your real key. Secret. |
| `GROUP_PASSWORD` | `pick-something-strong` | The shared password your group uses to log in. Secret. |
| `CHAINLIT_AUTH_SECRET` | run `openssl rand -hex 32` and paste output | Required by Chainlit for session signing. Secret. |

Click **Save** for each. HF will restart the Space.

## Step 4 — Verify

- Watch the **Logs** tab on your Space. The build should finish in 3–5 min. Look for `Your app is available at http://0.0.0.0:7860`.
- Open `https://<your-hf-username>-lsms-agent.hf.space` in a new tab.
- You should see Chainlit's login screen. Username = anything; password = your `GROUP_PASSWORD`.
- Try: *"list all countries and rounds"*.

## Step 5 — Point the GitHub Pages landing page at the live URL

The repo has a `docs/index.html` landing page. Edit it once you know the Space URL:

```bash
# In /Users/xiongcaizhen/Desktop/LSMS Automation/
# Open docs/index.html and replace OPEN-APP-PLACEHOLDER-URL with your real HF URL.
# Then:
git add docs/index.html
git commit -m "Set live app URL in landing page"
git push
```

GitHub Pages auto-rebuilds. Landing page is at `https://caizhen-x.github.io/lsms-agent/`.

## Updating later

| What changed | What to do |
|---|---|
| Code only (no new data) | `git push` to the HF Space. HF rebuilds in ~3 min. |
| Data changed (new round, re-download) | Re-run `make all-ingest` locally, then `git add catalog/ && git commit && git push` to the HF Space (LFS handles the large files). |
| GitHub Pages landing | Edit `docs/index.html`, push to GitHub. |

## Troubleshooting

- **Build fails on `pyreadstat`**: HF's base image is fine, but if the wheel can't compile, switch to `pyreadstat==1.2.7` in the Dockerfile pin.
- **App boots but anyone can chat without password**: `GROUP_PASSWORD` secret wasn't set or didn't propagate — restart the Space from the Settings page.
- **"Session expired" loops**: `CHAINLIT_AUTH_SECRET` is missing. Set it (see Step 3).
- **Space goes to sleep**: HF Spaces on the free tier sleep after inactivity (cold start ~30s). Upgrade to a paid tier, or accept the cold start.

## Costs

- HF Space hosting: **free** on `cpu-basic`.
- Anthropic API: pay-as-you-go on your key. Sonnet 4.6 with the system prompt cached costs roughly **$0.20–$0.50 per analysis session**. Set a usage cap at <https://console.anthropic.com/settings/limits> as a safety net.
