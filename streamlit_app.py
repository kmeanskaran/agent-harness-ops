import hashlib
import json
import os
import time
from typing import Optional

import requests
import streamlit as st

st.set_page_config(
    page_title="DevVoice - Content Creator",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE_URL = os.getenv("API_URL", "http://api:8000")
POLL_INTERVAL = 2

PLATFORM_LABELS = {
    "x": "X Thread",
    "linkedin": "LinkedIn Post",
    "devto": "dev.to Article",
}

# ── session state init ────────────────────────────────────────────────────────

for key, default in {
    # {fingerprint: {"x": [...], "linkedin": "...", "devto": "...", "review_notes": "..."}}
    "result_cache": {},
    # [{job_id, platforms: list[str], fingerprint: str}]
    "active_jobs": [],
    # fingerprint of the current input form state
    "current_fingerprint": None,
    # platforms the user has ever requested for the current fingerprint
    "requested_platforms": [],
    # which platform tab to show in the result view
    "active_tab": "x",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ── helpers ───────────────────────────────────────────────────────────────────

def make_fingerprint(payload: dict) -> str:
    key = {k: payload[k] for k in ["readme", "learnings", "hard_parts", "tone", "audience"]}
    return hashlib.md5(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]


def create_payload(readme, learnings, hard_parts, tone, audience):
    return {
        "readme": readme,
        "learnings": learnings,
        "hard_parts": hard_parts,
        "tone": tone,
        "audience": audience,
    }


def submit_job(platforms: list[str], payload: dict) -> Optional[str]:
    body = {**payload, "platforms": platforms}
    try:
        r = requests.post(f"{API_BASE_URL}/generate", json=body, timeout=10)
        if r.status_code == 200:
            return r.json()["job_id"]
        st.error(f"API error {r.status_code}: {r.text}")
    except requests.exceptions.RequestException as e:
        st.error(f"Connection error: {e}")
    return None


def check_job_status(job_id: str) -> dict:
    try:
        r = requests.get(f"{API_BASE_URL}/result/{job_id}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException:
        pass
    return {}


def parse_bullet_list(text: str) -> list:
    lines = []
    for line in text.splitlines():
        line = line.strip().lstrip("- ").strip()
        if line:
            lines.append(line)
    return lines


def cached_result(fingerprint: str) -> dict:
    return st.session_state.result_cache.get(fingerprint, {})


def merge_into_cache(fingerprint: str, result: dict) -> None:
    existing = st.session_state.result_cache.get(fingerprint, {})
    if result.get("x_thread"):
        existing["x_thread"] = result["x_thread"]
    if result.get("linkedin_post"):
        existing["linkedin_post"] = result["linkedin_post"]
    if result.get("devto_article"):
        existing["devto_article"] = result["devto_article"]
    st.session_state.result_cache[fingerprint] = existing


def platform_in_cache(fingerprint: str, platform: str) -> bool:
    cache = cached_result(fingerprint)
    if platform == "x":
        return bool(cache.get("x_thread"))
    if platform == "linkedin":
        return bool(cache.get("linkedin_post"))
    if platform == "devto":
        return bool(cache.get("devto_article"))
    return False


def jobs_for_fingerprint(fingerprint: str) -> list[dict]:
    return [j for j in st.session_state.active_jobs if j["fingerprint"] == fingerprint]


def any_active_jobs(fingerprint: str) -> bool:
    return len(jobs_for_fingerprint(fingerprint)) > 0


def platform_is_pending(fingerprint: str, platform: str) -> bool:
    for job in jobs_for_fingerprint(fingerprint):
        if platform in job["platforms"]:
            return True
    return False


# ── result display ────────────────────────────────────────────────────────────

def display_platform_content(fingerprint: str, platform: str):
    cache = cached_result(fingerprint)
    pending = platform_is_pending(fingerprint, platform)
    content = None

    if platform == "x":
        content = cache.get("x_thread")
        if content:
            for i, tweet in enumerate(content, 1):
                char_count = len(tweet)
                color = "green" if char_count >= 200 else "orange"
                with st.container(border=True):
                    st.markdown(f"**Tweet {i}** — :{color}[{char_count} chars]")
                    st.text(tweet)
        elif pending:
            st.info("Generating X thread… you can switch to other tabs while waiting.")
        else:
            st.caption("Not generated yet.")

    elif platform == "linkedin":
        content = cache.get("linkedin_post")
        if content:
            with st.container(border=True):
                st.markdown(content)
        elif pending:
            st.info("Generating LinkedIn post… you can switch to other tabs while waiting.")
        else:
            st.caption("Not generated yet.")

    elif platform == "devto":
        content = cache.get("devto_article")
        if content:
            with st.container(border=True):
                st.markdown(content)
        elif pending:
            st.info("Generating dev.to article… you can switch to other tabs while waiting.")
        else:
            st.caption("Not generated yet.")



def display_results(fingerprint: str):
    requested = st.session_state.requested_platforms

    st.subheader("Generated Content")

    tab_labels = [PLATFORM_LABELS[p] for p in ["x", "linkedin", "devto"] if p in requested]
    tab_keys = [p for p in ["x", "linkedin", "devto"] if p in requested]

    if not tab_keys:
        return

    tabs = st.tabs(tab_labels)
    for tab, platform in zip(tabs, tab_keys):
        with tab:
            display_platform_content(fingerprint, platform)

    # "Also generate" section for platforms not yet requested
    unrequested = [p for p in ["x", "linkedin", "devto"] if p not in requested]
    if unrequested:
        st.divider()
        st.caption("Want more from the same README?")
        extra_cols = st.columns(len(unrequested))
        for col, platform in zip(extra_cols, unrequested):
            with col:
                if st.button(
                    f"Also generate {PLATFORM_LABELS[platform]}",
                    key=f"add_{platform}",
                    use_container_width=True,
                ):
                    payload = st.session_state.get("last_payload", {})
                    if payload:
                        job_id = submit_job([platform], payload)
                        if job_id:
                            st.session_state.active_jobs.append(
                                {"job_id": job_id, "platforms": [platform], "fingerprint": fingerprint}
                            )
                            if platform not in st.session_state.requested_platforms:
                                st.session_state.requested_platforms.append(platform)
                            st.rerun()


# ── sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.header("Configuration")
input_method = st.sidebar.radio("README input method", ["Upload file", "Paste text"])

# ── title ─────────────────────────────────────────────────────────────────────

st.title("DevVoice — Content Creation Agent")
st.caption("Turn a GitHub README into a reviewed X thread, LinkedIn post, or dev.to article.")

# ── active jobs banner + polling ──────────────────────────────────────────────

fingerprint = st.session_state.current_fingerprint

if st.session_state.active_jobs:
    step_labels = {
        "queued": "Waiting in queue…",
        "running": "Starting up…",
        "extracting": "Extracting insights from README…",
        "writing": "Writing content…",
        "reviewing": "Reviewing and verifying claims…",
        "completed": "Done!",
    }

    still_active = []
    any_changed = False

    for job in st.session_state.active_jobs:
        data = check_job_status(job["job_id"])
        status = data.get("status", "queued")
        label = step_labels.get(status, status)
        platform_names = " + ".join(PLATFORM_LABELS[p] for p in job["platforms"])

        if status == "completed":
            merge_into_cache(job["fingerprint"], data)
            any_changed = True
        elif status == "failed":
            st.error(f"Job failed ({platform_names}): {data.get('error', 'unknown error')}")
            any_changed = True
        else:
            still_active.append(job)
            with st.status(f"Generating {platform_names} — {label}", state="running", expanded=False):
                st.write(f"**Job ID:** `{job['job_id']}`")
                if data.get("current_step"):
                    st.write(f"**Step:** {data['current_step']}")

    st.session_state.active_jobs = still_active

    if any_changed:
        st.rerun()
    elif still_active:
        time.sleep(POLL_INTERVAL)
        st.rerun()

# ── show cached results (if any for current input) ────────────────────────────

if fingerprint and (cached_result(fingerprint) or any_active_jobs(fingerprint)):
    display_results(fingerprint)
    st.divider()
    if st.button("Start over with new README"):
        st.session_state.current_fingerprint = None
        st.session_state.requested_platforms = []
        st.rerun()
    st.stop()

# ── input form ────────────────────────────────────────────────────────────────

st.header("Step 1: README")

readme_content = ""

if input_method == "Upload file":
    uploaded = st.file_uploader(
        "Upload your README (.md or .txt)",
        type=["md", "txt"],
        help="Drag and drop your README.md here",
    )
    if uploaded:
        readme_content = uploaded.read().decode("utf-8")
        st.success(f"Loaded **{uploaded.name}** ({len(readme_content):,} chars)")
        with st.expander("Preview"):
            st.markdown(readme_content[:800] + ("…" if len(readme_content) > 800 else ""))
else:
    readme_content = st.text_area(
        "Paste README content",
        height=260,
        placeholder="# Your Project\n\nPaste your full README markdown here…",
    )
    if readme_content:
        st.caption(f"{len(readme_content):,} characters")

st.header("Step 2: Optional Context")

col_l, col_r = st.columns(2)
with col_l:
    learnings_raw = st.text_area(
        "Key Learnings",
        height=120,
        placeholder="One per line:\n- Redis pub/sub is faster than polling\n- Celery needs state tracking",
    )
with col_r:
    hard_parts_raw = st.text_area(
        "Hard Parts / Challenges",
        height=120,
        placeholder="One per line:\n- Managing distributed task state\n- Debugging connection timeouts",
    )

col_t, col_a = st.columns(2)
with col_t:
    tone = st.selectbox("Tone", ["honest and practical", "technical", "casual", "professional", "storytelling"])
with col_a:
    audience = st.selectbox(
        "Target Audience",
        ["intermediate developers", "junior developers", "senior engineers",
         "CTOs / Tech leads", "DevOps engineers", "full-stack developers", "general tech community"],
    )

learnings = parse_bullet_list(learnings_raw)
hard_parts = parse_bullet_list(hard_parts_raw)

st.header("Step 3: Choose Platforms & Generate")

if not readme_content.strip():
    st.warning("Provide a README above to continue.")
    st.stop()

payload = create_payload(readme_content, learnings, hard_parts, tone, audience)
fp = make_fingerprint(payload)

col_x, col_li, col_dt = st.columns(3)
with col_x:
    want_x = st.checkbox("X Thread", value=True, key="want_x")
with col_li:
    want_li = st.checkbox("LinkedIn Post", value=False, key="want_li")
with col_dt:
    want_dt = st.checkbox("dev.to Article", value=False, key="want_dt")

selected = []
if want_x:
    selected.append("x")
if want_li:
    selected.append("linkedin")
if want_dt:
    selected.append("devto")

if not selected:
    st.warning("Select at least one platform.")
    st.stop()

platform_names = " + ".join(PLATFORM_LABELS[p] for p in selected)

if st.button(f"Generate {platform_names}", type="primary", use_container_width=True):
    # Only submit platforms not already cached for this exact input
    to_generate = [p for p in selected if not platform_in_cache(fp, p)]
    if not to_generate:
        st.session_state.current_fingerprint = fp
        st.session_state.last_payload = payload
        for p in selected:
            if p not in st.session_state.requested_platforms:
                st.session_state.requested_platforms.append(p)
        st.rerun()
    else:
        job_id = submit_job(to_generate, payload)
        if job_id:
            st.session_state.active_jobs.append(
                {"job_id": job_id, "platforms": to_generate, "fingerprint": fp}
            )
            st.session_state.current_fingerprint = fp
            st.session_state.last_payload = payload
            for p in selected:
                if p not in st.session_state.requested_platforms:
                    st.session_state.requested_platforms.append(p)
            st.rerun()

# ── footer ────────────────────────────────────────────────────────────────────

st.divider()
if st.button("Check API status"):
    try:
        r = requests.get(f"{API_BASE_URL}/health", timeout=5)
        d = r.json()
        st.success(f"API ok — Redis: {'up' if d.get('redis') else 'down'}")
    except Exception as e:
        st.error(f"Cannot reach API at {API_BASE_URL}: {e}")
