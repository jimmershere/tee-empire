"""Pluggable image-generation backends.

The image backend produces the *raw design art* (PNG with transparent
background ideally). The mockup compositor (designs.py) then places it on a
shirt mockup.

Backends:
  - "placeholder"  — uses Pillow to render the design text on a transparent canvas
                      (always works, no network, deterministic).
  - "comfyui"       — POSTs a workflow to a ComfyUI server at $COMFYUI_URL(S).
  - "openai"        — uses the OpenAI Images API (gpt-image-1) if $OPENAI_API_KEY set.
  - "kieai"         — uses Kie.AI (api.kie.ai) FLUX endpoint with $KIEAI_API_KEY.
                      Parallel batch via concurrent HTTP calls (no local GPU needed).

All backends return (png_bytes, source_label).
"""
from __future__ import annotations

import base64
import json
import os
import random
import time
import urllib.request
import urllib.error
import uuid
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIL_AVAILABLE = False


def select_backend() -> str:
    pref = os.getenv("EMPIRE_IMAGE_BACKEND", "").lower()
    if pref:
        return pref
    # Local-first, cheap, high-quality defaults per user request:
    # 1. Kie.ai (FLUX) if KIEAI_API_KEY present
    # 2. OpenRouter (multi-model, including image-capable) if OPENROUTER_API_KEY
    # 3. OpenAI (gpt-image-1)
    # 4. ComfyUI (local)
    # 5. placeholder
    if os.getenv("KIEAI_API_KEY"):
        return "kieai"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("COMFYUI_URL") or os.getenv("COMFYUI_URLS"):
        return "comfyui"
    # Future: if os.getenv("OLLAMA_URL"): return "ollama"
    return "placeholder"


def generate_design_png(design_text: str, design_prompt: str, *, backend: Optional[str] = None,
                        size: Tuple[int, int] = (1200, 1500),
                        text_color: str = "#FFFFFF",
                        shirt_color: str = "#111111",
                        dry_run: bool = False) -> Tuple[bytes, str]:
    """Single-variant convenience wrapper around generate_design_variants."""
    variants, source = generate_design_variants(
        design_text, design_prompt, backend=backend, size=size,
        text_color=text_color, shirt_color=shirt_color, dry_run=dry_run,
    )
    return variants[0], source


def generate_design_variants(design_text: str, design_prompt: str, *,
                             backend: Optional[str] = None,
                             size: Tuple[int, int] = (1200, 1500),
                             text_color: str = "#FFFFFF",
                             shirt_color: str = "#111111",
                             dry_run: bool = False) -> Tuple[List[bytes], str]:
    """Generate one or more variants. ComfyUI honours its workflow's batch_size; other backends return 1."""
    backend = (backend or select_backend()).lower()
    if dry_run or backend == "placeholder":
        return [_pillow_placeholder(design_text, size, text_color, shirt_color)], "placeholder"
    if backend == "openai":
        try:
            return [_openai_image(design_prompt, size)], "openai"
        except Exception:
            return [_pillow_placeholder(design_text, size, text_color, shirt_color)], "placeholder-fallback"
    if backend == "comfyui":
        try:
            imgs = _comfyui_images(design_prompt, size)
            return imgs, "comfyui"
        except Exception:
            return [_pillow_placeholder(design_text, size, text_color, shirt_color)], "placeholder-fallback"
    if backend == "kieai":
        try:
            imgs = _kieai_images(design_prompt, size)
            return imgs, "kieai"
        except Exception:
            return [_pillow_placeholder(design_text, size, text_color, shirt_color)], "placeholder-fallback"
    if backend == "openrouter":
        try:
            imgs = _openrouter_images(design_prompt, size)
            return imgs, "openrouter"
        except Exception:
            return [_pillow_placeholder(design_text, size, text_color, shirt_color)], "placeholder-fallback"
    # ollama stub (local inference later)
    if backend == "ollama":
        try:
            imgs = _ollama_images(design_prompt, size)
            return imgs, "ollama"
        except Exception:
            return [_pillow_placeholder(design_text, size, text_color, shirt_color)], "placeholder-fallback"
    return [_pillow_placeholder(design_text, size, text_color, shirt_color)], "placeholder"


# ---------- Placeholder (Pillow) ----------
def _pillow_placeholder(text: str, size: Tuple[int, int], text_color: str, shirt_color: str) -> bytes:
    if not _PIL_AVAILABLE:
        return _raw_text_png_fallback(text)
    w, h = size
    img = Image.new("RGB", size, _parse_color(shirt_color))
    draw = ImageDraw.Draw(img)
    font = _load_font(int(h * 0.06))
    wrapped = _wrap_text(text, max_chars=20)
    line_h = int(h * 0.075)
    total_h = line_h * len(wrapped)
    y = (h - total_h) // 2
    fill = _parse_color(text_color)
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (w - line_w) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    border = max(8, int(min(w, h) * 0.01))
    draw.rectangle([border, border, w - border, h - border], outline=fill, width=4)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _load_font(px: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, px)
            except OSError:
                continue
    return ImageFont.load_default()


def _parse_color(c: str):
    if not c:
        return (0, 0, 0)
    c = c.strip()
    named = {
        "black": (0, 0, 0), "white": (255, 255, 255), "navy": (10, 25, 75),
        "army": (45, 60, 30), "red": (170, 30, 30), "charcoal": (40, 40, 45),
        "sand": (215, 195, 160), "vintage black": (20, 20, 20),
        "heather dark gray": (60, 60, 65), "heather cardinal": (130, 30, 40),
        "neon green": (60, 230, 80),
    }
    if c.lower() in named:
        return named[c.lower()]
    if c.startswith("#") and len(c) == 7:
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    return (240, 240, 240)


def _wrap_text(text: str, max_chars: int = 20) -> list[str]:
    words, line, lines = text.replace("/", " / ").split(), "", []
    for w in words:
        candidate = (line + " " + w).strip()
        if len(candidate) > max_chars and line:
            lines.append(line)
            line = w
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines or [text]


def _raw_text_png_fallback(text: str) -> bytes:
    # Last-resort 1x1 white PNG when Pillow isn't available.
    one_px_white = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    return one_px_white


# ---------- OpenAI ----------
def _openai_image(prompt: str, size: Tuple[int, int]) -> bytes:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    w, h = size
    # gpt-image-1 supported sizes: 1024x1024, 1024x1536 (portrait), 1536x1024 (landscape).
    closest = "1024x1024"
    if w > h:
        closest = "1536x1024"
    elif h > w:
        closest = "1024x1536"
    # Strongly bias the prompt for transparent-background tee art so the
    # mockup compositor can paste it onto a shirt without a square halo.
    augmented = (
        f"{prompt}\n\n"
        "Output: a single front-of-shirt print-ready graphic on a transparent background. "
        "No mockup, no model, no photography, no shirt, no border, no watermark. "
        "Just the artwork that would be screenprinted on the chest."
    )
    payload = {
        "model": "gpt-image-1",
        "prompt": augmented,
        "size": closest,
        "n": 1,
        "background": "transparent",
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    b64 = body["data"][0]["b64_json"]
    return base64.b64decode(b64)


# ---------- Image editing (instruction-based img2img) ----------
def select_edit_backend() -> Optional[str]:
    """Which backend can EDIT an existing image given a text instruction.

    Distinct from select_backend(): most text-to-image models (flux-schnell)
    cannot take a source image. Returns None when no edit-capable backend is
    configured (caller should then keep the original art).
    """
    pref = os.getenv("EMPIRE_EDIT_BACKEND", "").lower()
    if pref:
        return pref or None
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("KIEAI_API_KEY"):
        return "kieai"
    return None


def edit_design_png(source_png: bytes, instruction: str, *,
                    backend: Optional[str] = None,
                    size: Tuple[int, int] = (1024, 1024),
                    dry_run: bool = False) -> Tuple[Optional[bytes], str]:
    """Edit ``source_png`` per ``instruction``. Returns (png_bytes|None, source).

    None means no edit backend was available; the caller should keep the
    original art (or fall back to a deterministic overlay).
    """
    backend = (backend or select_edit_backend() or "").lower()
    if dry_run:
        return source_png, "edit-dryrun-noop"
    if not backend:
        return None, "no-edit-backend"
    if backend == "openai":
        try:
            return _openai_edit_image(source_png, instruction, size), "openai-edit"
        except Exception as exc:
            return None, f"openai-edit-failed:{exc}"[:160]
    if backend == "kieai":
        try:
            return _kieai_edit_image(source_png, instruction, size), "kieai-edit"
        except Exception as exc:
            return None, f"kieai-edit-failed:{exc}"[:160]
    return None, f"unknown-edit-backend:{backend}"


def _openai_edit_image(source_png: bytes, instruction: str,
                       size: Tuple[int, int]) -> bytes:
    """POST multipart/form-data to OpenAI /v1/images/edits with gpt-image-1."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    w, h = size
    osize = "1024x1024"
    if w > h:
        osize = "1536x1024"
    elif h > w:
        osize = "1024x1536"
    fields = {"model": model, "prompt": instruction, "size": osize}
    bg = os.getenv("OPENAI_IMAGE_BACKGROUND", "").strip()
    if bg:
        fields["background"] = bg
    files = [("image", "source.png", source_png, "image/png")]
    body, content_type = _multipart_encode(fields, files)
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/edits",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenAI edits {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    return base64.b64decode(payload["data"][0]["b64_json"])


def _multipart_encode(fields: dict, files: list) -> Tuple[bytes, str]:
    """Minimal multipart/form-data encoder. files = [(name, filename, bytes, mime)]."""
    boundary = "----teeempire" + uuid.uuid4().hex
    buf = BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        buf.write(f"{value}\r\n".encode())
    for name, filename, content, mime in files:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        buf.write(f"Content-Type: {mime}\r\n\r\n".encode())
        buf.write(content)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def _kieai_edit_image(source_png: bytes, instruction: str,
                      size: Tuple[int, int]) -> bytes:
    """Edit via Kie.ai flux-kontext (instruction + input image). Placeholder for
    future use; raises so callers fall back when KIEAI editing isn't wired."""
    raise RuntimeError("kieai edit path not implemented; use EMPIRE_EDIT_BACKEND=openai")


# ---------- ComfyUI ----------
DEFAULT_COMFY_WORKFLOW = Path(__file__).resolve().parent / "comfyui_workflow.json"


def _build_comfy_workflow(prompt: str, size: Tuple[int, int]) -> dict:
    """Load the workflow template, inject prompt + size + a fresh seed.

    Locates nodes by their class_type rather than ID so the same code handles
    the all-in-one checkpoint workflow and the split UNet/CLIP/VAE workflow.
    The *first* empty-text CLIPTextEncode is treated as the positive prompt.
    """
    template_path = os.getenv("COMFYUI_WORKFLOW_TEMPLATE")
    path = Path(template_path) if template_path else DEFAULT_COMFY_WORKFLOW
    if not path.exists():
        raise RuntimeError(f"ComfyUI workflow template missing: {path}")
    workflow = json.loads(path.read_text())

    # Positive prompt: first CLIPTextEncode whose text is empty.
    for node in workflow.values():
        if node.get("class_type") == "CLIPTextEncode" and not node["inputs"].get("text"):
            node["inputs"]["text"] = prompt
            break
    # Latent dims: any EmptyLatentImage / EmptySD3LatentImage.
    for node in workflow.values():
        ct = node.get("class_type")
        if ct in {"EmptyLatentImage", "EmptySD3LatentImage"}:
            node["inputs"]["width"] = size[0]
            node["inputs"]["height"] = size[1]
    # Fresh seed: any node carrying a "seed" input (KSampler / KSamplerAdvanced).
    for node in workflow.values():
        if "seed" in node.get("inputs", {}):
            node["inputs"]["seed"] = random.randint(1, 2**31 - 1)
    return workflow


def _comfyui_image(prompt: str, size: Tuple[int, int]) -> bytes:
    """Backwards-compatible single-image wrapper."""
    return _comfyui_images(prompt, size)[0]


def _comfyui_endpoints() -> List[str]:
    """Read COMFYUI_URLS (comma-separated) or fall back to single COMFYUI_URL."""
    raw = os.getenv("COMFYUI_URLS", "").strip()
    if raw:
        return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
    single = os.getenv("COMFYUI_URL", "").strip().rstrip("/")
    return [single] if single else []


def _comfyui_probe(endpoint: str, timeout_s: float = 3.0) -> bool:
    """Quick liveness check — used to skip dead nodes before dispatch."""
    try:
        with urllib.request.urlopen(f"{endpoint}/system_stats", timeout=timeout_s) as r:
            r.read()
        return True
    except Exception:
        return False


def _comfyui_images(prompt: str, size: Tuple[int, int]) -> List[bytes]:
    """Generate N variants via ComfyUI, dispatching in parallel across all live
    endpoints (COMFYUI_URLS, comma-separated). N = EMPIRE_COMFY_VARIANTS (default 4).

    With one endpoint: N sequential single-image runs (current behaviour).
    With two endpoints: N runs split round-robin, executed concurrently via threads —
    halves wall-clock for batch=4 once both ComfyUI instances are up.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    n = int(os.getenv("EMPIRE_COMFY_VARIANTS", "4"))
    endpoints = [ep for ep in _comfyui_endpoints() if _comfyui_probe(ep)]
    if not endpoints:
        raise RuntimeError("No live ComfyUI endpoints available")

    # Round-robin assignment of N variants across the live endpoints.
    assignments = [(i, endpoints[i % len(endpoints)]) for i in range(n)]
    results: dict = {}
    errors: List[Exception] = []

    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        futures = {
            pool.submit(_comfyui_single_image, prompt, size, endpoint=ep): variant_idx
            for variant_idx, ep in assignments
        }
        for fut in as_completed(futures):
            variant_idx = futures[fut]
            try:
                results[variant_idx] = fut.result()
            except Exception as e:
                errors.append(e)

    out = [results[i] for i in sorted(results) if i in results]
    if not out:
        raise errors[0] if errors else RuntimeError("ComfyUI returned no images")
    return out


def _comfyui_single_image(prompt: str, size: Tuple[int, int],
                          endpoint: Optional[str] = None) -> bytes:
    if endpoint is None:
        eps = _comfyui_endpoints()
        if not eps:
            raise RuntimeError("COMFYUI_URL/URLS not set")
        endpoint = eps[0]
    base = endpoint.rstrip("/")

    workflow = _build_comfy_workflow(prompt, size)
    client_id = uuid.uuid4().hex

    # 1. Submit the workflow.
    req = urllib.request.Request(
        f"{base}/prompt",
        data=json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ComfyUI /prompt rejected: {e.code} {e.read().decode()[:300]}") from e
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {result}")

    # 2. Poll /history/<id> until the job completes or times out.
    timeout_s = float(os.getenv("COMFYUI_TIMEOUT_S", "420"))
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        with urllib.request.urlopen(f"{base}/history/{prompt_id}", timeout=15) as resp:
            history = json.loads(resp.read().decode("utf-8"))
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            last_status = status
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI job errored: {status.get('messages')}")
            if status.get("completed"):
                outputs = entry.get("outputs", {})
                for node_output in outputs.values():
                    for img in node_output.get("images", []) or []:
                        return _comfy_fetch_image(base, img)
                raise RuntimeError(f"ComfyUI completed but no image outputs: {outputs}")
        time.sleep(1.5)
    raise RuntimeError(f"ComfyUI timed out after {timeout_s}s waiting on {prompt_id} (last={last_status})")


def _comfy_fetch_image(base: str, img_meta: dict) -> bytes:
    """Pull an image from /view?filename=...&subfolder=...&type=..."""
    import urllib.parse
    qs = urllib.parse.urlencode({
        "filename": img_meta["filename"],
        "subfolder": img_meta.get("subfolder", ""),
        "type": img_meta.get("type", "output"),
    })
    with urllib.request.urlopen(f"{base}/view?{qs}", timeout=30) as resp:
        return resp.read()


# ---------- OpenRouter (default fallback after Kie.ai) ----------
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

def _openrouter_images(prompt: str, size: Tuple[int, int]) -> List[bytes]:
    """OpenRouter image generation (OpenAI-compatible /images/generations for supported models).
    Uses OPENROUTER_API_KEY. Model via OPENROUTER_IMAGE_MODEL (default: a fast FLUX or SD3 variant).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    model = os.getenv("OPENROUTER_IMAGE_MODEL", "black-forest-labs/flux-schnell")
    n = int(os.getenv("EMPIRE_OPENROUTER_VARIANTS", os.getenv("EMPIRE_COMFY_VARIANTS", "3")))
    out: List[bytes] = []
    errors: List[Exception] = []
    def one(_: int) -> bytes:
        w, h = size
        closest = "1024x1024"
        if w > h: closest = "1536x1024"
        elif h > w: closest = "1024x1536"
        augmented = (
            f"{prompt}\n\n"
            "Output: clean print-ready graphic on transparent background. "
            "No mockup, no shirt, no watermark, no extra text unless in prompt."
        )
        payload = {
            "model": model,
            "prompt": augmented,
            "size": closest,
            "n": 1,
            "response_format": "b64_json",
        }
        req = urllib.request.Request(
            f"{OPENROUTER_API_BASE}/images/generations",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://tee-empire.local",
                "X-Title": "tee-empire",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        b64 = body["data"][0]["b64_json"]
        return base64.b64decode(b64)
    with ThreadPoolExecutor(max_workers=min(n, 4)) as pool:
        futures = [pool.submit(one, i) for i in range(n)]
        for fut in as_completed(futures):
            try:
                out.append(fut.result())
            except Exception as e:
                errors.append(e)
    if not out:
        raise errors[0] if errors else RuntimeError("OpenRouter returned no images")
    return out


# ---------- Ollama (stub for local inference; wire /api/generate or image endpoints later) ----------
def _ollama_images(prompt: str, size: Tuple[int, int]) -> List[bytes]:
    """Stub. Set OLLAMA_URL=http://localhost:11434 and implement a real caller.
    For now raises to force fallback to placeholder (or another backend).
    """
    base = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    # TODO: call {base}/api/generate or a vision/image model endpoint.
    # Example future: use a model that supports image out, or txt2img via ollama + external.
    raise RuntimeError("ollama image backend not implemented yet (set EMPIRE_IMAGE_BACKEND=kieai or openrouter for now)")


# ---------- Kie.AI ----------
KIEAI_API_BASE = "https://api.kie.ai/api/v1"


def _kieai_via_ssh() -> Optional[List[str]]:
    """If EMPIRE_KIEAI_VIA_SSH is set, return an ssh command prefix to run curl
    on a whitelisted host. Format: user@host (uses ~/.ssh/floor2_mount key)."""
    target = os.getenv("EMPIRE_KIEAI_VIA_SSH", "").strip()
    if not target:
        return None
    key = os.getenv("EMPIRE_KIEAI_SSH_KEY",
                    str(Path.home() / ".ssh" / "floor2_mount"))
    return ["ssh", "-i", key,
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath=/tmp/empire-kie-%r@%h:%p",
            "-o", "ControlPersist=10m",
            target]


def _kieai_http_call(method: str, url: str, body: Optional[bytes] = None,
                     headers: Optional[dict] = None,
                     timeout_s: int = 60) -> bytes:
    """HTTP call to api.kie.ai. Routes via SSH+curl if EMPIRE_KIEAI_VIA_SSH set.
    Returns the response body as bytes. Raises RuntimeError on non-2xx."""
    headers = headers or {}
    ssh_prefix = _kieai_via_ssh()
    if ssh_prefix:
        # Build a curl command that's safe to ssh-execute. Pass body via stdin
        # (so the API key in headers isn't in argv on the remote ps list either).
        import subprocess, shlex
        curl_cmd = ["curl", "-4", "-sS", "-X", method, url, "--max-time", str(timeout_s), "-w", "\\n%{http_code}"]
        for k, v in headers.items():
            curl_cmd += ["-H", f"{k}: {v}"]
        if body is not None:
            curl_cmd += ["--data-binary", "@-"]
        remote = " ".join(shlex.quote(a) for a in curl_cmd)
        proc = subprocess.run(
            ssh_prefix + [remote],
            input=body, capture_output=True, timeout=timeout_s + 30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ssh+curl failed: {proc.stderr.decode()[:300]}")
        out = proc.stdout
        # Trailing line is HTTP status
        sep = out.rfind(b"\n")
        status = int(out[sep+1:].decode().strip())
        body_out = out[:sep] if sep >= 0 else out
        if status >= 400:
            raise RuntimeError(f"HTTP {status}: {body_out.decode(errors='replace')[:300]}")
        return body_out
    # Direct path (no SSH proxy) -- preferred for local hosting
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}") from e
    # Note: EMPIRE_KIEAI_VIA_SSH remains for rare air-gapped cases; not needed for normal local use.


def _kieai_images(prompt: str, size: Tuple[int, int]) -> List[bytes]:
    """Generate N variants via Kie.AI in parallel. N from EMPIRE_COMFY_VARIANTS (default 4)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    n = int(os.getenv("EMPIRE_COMFY_VARIANTS", "4"))
    out: List[bytes] = []
    errors: List[Exception] = []
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(_kieai_single_image, prompt, size) for _ in range(n)]
        for fut in as_completed(futures):
            try:
                out.append(fut.result())
            except Exception as e:
                errors.append(e)
    if not out:
        raise errors[0] if errors else RuntimeError("Kie.AI returned no images")
    return out


def _kieai_single_image(prompt: str, size: Tuple[int, int]) -> bytes:
    api_key = os.getenv("KIEAI_API_KEY")
    if not api_key:
        raise RuntimeError("KIEAI_API_KEY not set")
    model = os.getenv("KIEAI_MODEL", "flux-kontext-pro")
    aspect = os.getenv("KIEAI_ASPECT", "1:1")
    timeout_s = float(os.getenv("KIEAI_TIMEOUT_S", "300"))
    auth_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 1. Submit task
    payload = json.dumps({
        "model": model,
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect,
            "output_format": "png",
        },
    }).encode("utf-8")
    body = _kieai_http_call("POST", f"{KIEAI_API_BASE}/jobs/createTask",
                            body=payload, headers=auth_headers, timeout_s=30)
    parsed = json.loads(body.decode("utf-8"))
    task_id = (parsed.get("data") or {}).get("taskId")
    if not task_id:
        raise RuntimeError(f"Kie.AI did not return taskId: {parsed}")

    # 2. Poll for completion
    deadline = time.time() + timeout_s
    last_status = None
    auth_only = {"Authorization": f"Bearer {api_key}"}
    while time.time() < deadline:
        time.sleep(8)
        info_raw = _kieai_http_call(
            "GET", f"{KIEAI_API_BASE}/jobs/recordInfo?taskId={task_id}",
            headers=auth_only, timeout_s=20,
        )
        info = json.loads(info_raw.decode("utf-8"))
        data = info.get("data") or {}
        status = data.get("state") or data.get("status") or "pending"
        last_status = status
        if status in ("completed", "success"):
            result_json = data.get("resultJson")
            if isinstance(result_json, str):
                try:
                    result_json = json.loads(result_json)
                except json.JSONDecodeError:
                    result_json = {}
            urls = (result_json or {}).get("resultUrls") or []
            if not urls:
                raise RuntimeError(f"Kie.AI completed but no resultUrls: {data}")
            # Download the result image (no auth needed; uses signed URL).
            return _kieai_http_call("GET", urls[0], timeout_s=60)
        if status in ("failed", "error"):
            raise RuntimeError(f"Kie.AI job failed: {data}")
    raise RuntimeError(f"Kie.AI timed out after {timeout_s}s (last={last_status})")
