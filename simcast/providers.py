"""SimCast's AI providers: OpenAI, Google Gemini and DeepSeek through one client (their APIs all speak the OpenAI
chat format), with fallback to another provider that has a key, and the best model picked automatically.

The provider code comes from SimCoach (same author, MIT licence); SimCast doesn't need SimCoach installed.
Automatic models: when a key is added, SimCast asks the provider which models the key can use (in the
background) and picks the best one for live commentary from PREFERRED. Until that answer is in, or if it can't
be asked, the first model in PREFERRED is used. A model picked by hand in Settings always wins.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict

AUTO = "auto"

OPENAI_MODELS = ["gpt-6-luna", "gpt-6.1-terra", "gpt-5.6-luna"]


GEMINI_MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-flash-latest"]


DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-flash", "deepseek-v4-pro", "deepseek-reasoner"]


RETIRED_OPENAI_MODELS = ("gpt-4o", "gpt-4.1", "gpt-4-", "gpt-3.5")


AI_PROVIDERS = OrderedDict((
    ("openai", {"name": "OpenAI", "label": "OpenAI (GPT)", "base_url": None, "env": "OPENAI_API_KEY",
                "models": OPENAI_MODELS, "key_url": "https://platform.openai.com/api-keys",
                "tokens": "max_completion_tokens", "extra": {}}),
    ("gemini", {"name": "Gemini", "label": "Google Gemini", "env": "GEMINI_API_KEY",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "models": GEMINI_MODELS, "key_url": "https://aistudio.google.com/apikey",
                # Short radio replies: keep thinking light so answers come back fast.
                "tokens": "max_tokens", "extra": {"reasoning_effort": "low"}}),
    ("deepseek", {"name": "DeepSeek", "label": "DeepSeek", "base_url": "https://api.deepseek.com",
                  "env": "DEEPSEEK_API_KEY", "models": DEEPSEEK_MODELS,
                  "key_url": "https://platform.deepseek.com/api_keys", "tokens": "max_tokens", "extra": {}}),
))


_OPENAI_CLIENTS = {}


_OPENAI_LOCK = threading.Lock()


class OpenAIReplyError(RuntimeError):
    """The AI answered, but with nothing usable (empty, cut off, refused or filtered). The message is speakable."""


def ai_provider(cfg):
    p = (cfg or {}).get("ai_provider") or "openai"
    return p if p in AI_PROVIDERS else "openai"


def ai_key(cfg, provider=None):
    p = provider or ai_provider(cfg)
    return ((cfg or {}).get(f"{p}_api_key") or os.environ.get(AI_PROVIDERS[p]["env"])
            or "").strip()


def ai_model(cfg, provider=None):
    """The model to use: the one picked in Settings, or (the default) the best one this key can use."""
    p = provider or ai_provider(cfg)
    chosen = ((cfg or {}).get(f"{p}_model") or "").strip()
    return chosen if chosen and chosen != AUTO else best_model(cfg, p)


def ai_label(cfg, provider=None):
    """'Gemini gemini-3.5-flash': who answers, for the radio screen and setup sheets."""
    p = provider or ai_provider(cfg)
    return f"{AI_PROVIDERS[p]['name']} {ai_model(cfg, p)}"


def openai_client(key, base_url=None):
    """One client per (API key, endpoint), reused (each new client opens its own connection pool)."""
    import openai
    key = (key or "").strip()
    if not key:
        raise ValueError("no API key")
    with _OPENAI_LOCK:
        c = _OPENAI_CLIENTS.get((key, base_url))
        if c is None:
            c = _OPENAI_CLIENTS[(key, base_url)] = openai.OpenAI(api_key=key, base_url=base_url, timeout=20.0,
                                                                 max_retries=1)
        return c


_RE_UNSUPPORTED_MCT = re.compile(
    r"(?:unsupported|unknown|unrecognized)\s+(?:parameter|request argument)[^:]*:\s*['\"]?max_completion_tokens\b"
    r"|['\"]?max_completion_tokens['\"]?\s+(?:is\s+)?not\s+supported", re.IGNORECASE)


def _mct_unsupported(exc):
    """True only when the model rejects the max_completion_tokens parameter itself (older models want max_tokens),
    not for any other bad request that merely mentions it (a bad value, a context-length error...)."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        if err.get("param") == "max_completion_tokens" and err.get("code") in ("unsupported_parameter", "unknown_parameter"):
            return True
        text = str(err.get("message") or exc)
    else:
        text = str(exc)
    return bool(_RE_UNSUPPORTED_MCT.search(text))


def openai_chat(key, model, messages, max_tokens=300, timeout=20.0, provider="openai"):
    """Chat completion text from any provider in AI_PROVIDERS. max_completion_tokens counts a reasoning model's
    thinking too, so a small budget can come back empty or cut off: that is retried once with a bigger budget,
    then raised as OpenAIReplyError (never returned as '' or as half a sentence to be spoken)."""
    import openai
    spec = AI_PROVIDERS.get(provider) or AI_PROVIDERS["openai"]
    name = spec["name"]
    client = openai_client(key, spec["base_url"]).with_options(timeout=timeout)
    kw = {"model": model, "messages": messages}
    extra = dict(spec["extra"])
    param = [spec["tokens"]]

    def request(budget):
        while True:
            try:
                # Provider-specific options go in the JSON body, so an older openai package never rejects them.
                return client.chat.completions.create(**kw, **{param[0]: budget}, **({"extra_body": extra} if extra else {}))
            except openai.BadRequestError as e:
                if param[0] == "max_completion_tokens" and _mct_unsupported(e):
                    param[0] = "max_tokens"
                    continue
                # An optional tuning parameter this model doesn't take: drop it and ask again.
                bad = next((k for k in extra if re.search(rf"\b{re.escape(k)}\b", str(e))), None)
                if bad is None:
                    raise
                extra.pop(bad)

    budgets = (max_tokens, max(1024, max_tokens * 4))
    for attempt, budget in enumerate(budgets):
        r = request(budget)
        if not r.choices:
            raise OpenAIReplyError(f"{name} sent back nothing. Try again.")
        choice = r.choices[0]
        msg = choice.message
        if getattr(msg, "refusal", None):
            raise OpenAIReplyError(f"{name} declined to answer that one.")
        if choice.finish_reason == "content_filter":
            raise OpenAIReplyError(f"{name} filtered that answer. Try asking it another way.")
        text = (msg.content or "").strip()
        cut = choice.finish_reason == "length"
        if text and not cut:
            return text
        if attempt == 0:
            continue
        raise OpenAIReplyError(f"{name} ran out of room for an answer. Try a shorter question or another model."
                               if cut else f"{name} sent an empty answer. Try again.")


def _ai_transient(e):
    """A failure worth retrying on another provider: network, timeout, rate limit or a server-side error."""
    try:
        import openai
    except Exception:
        return False
    return isinstance(e, (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError))


def ai_chat_ex(cfg, messages, max_tokens=300, timeout=20.0):
    """(reply, 'Provider model') from the chosen provider. With 'ai_fallback' on, a network, rate-limit or
    server failure moves on to the other providers that have a key, so the radio keeps working. A failure
    carries .ai_provider (the provider that failed last) so the spoken explanation names the right one."""
    primary = ai_provider(cfg)
    order = [primary]
    if cfg.get("ai_fallback", True):
        order += [p for p in AI_PROVIDERS if p != primary and ai_key(cfg, p)]
    for i, p in enumerate(order):
        try:
            return openai_chat(ai_key(cfg, p), ai_model(cfg, p), messages, max_tokens=max_tokens,
                               timeout=timeout, provider=p), ai_label(cfg, p)
        except Exception as e:
            try:
                e.ai_provider = p
            except Exception:
                pass
            if i == len(order) - 1 or not _ai_transient(e):
                raise


def ai_chat(cfg, messages, max_tokens=300, timeout=20.0):
    return ai_chat_ex(cfg, messages, max_tokens, timeout)[0]


def openai_problem(e, provider="openai"):
    """A short spoken explanation of an AI failure (the key test strips ' Check it in SimCast's Settings.')."""
    if isinstance(e, OpenAIReplyError):
        return str(e)
    provider = getattr(e, "ai_provider", None) or provider
    name = (AI_PROVIDERS.get(provider) or AI_PROVIDERS["openai"])["name"]
    msg = str(e).lower()
    if isinstance(e, ValueError) and "api key" in msg:
        return f"There's no {name} API key. Check it in SimCast's Settings."
    try:
        import openai
    except Exception:
        return "The OpenAI package isn't installed. Run the setup again."
    if isinstance(e, openai.AuthenticationError):
        return f"{name} didn't accept the API key. Check it in SimCast's Settings."
    if isinstance(e, openai.PermissionDeniedError):
        return f"{name} refused access for this key. Check the key and model in Settings."
    if isinstance(e, openai.NotFoundError):
        return f"{name} couldn't find that model. Check it in SimCast's Settings."
    if isinstance(e, openai.RateLimitError):
        if "quota" in msg or "billing" in msg or "balance" in msg:
            return f"The {name} account is out of credit. Top it up, then try again."
        return f"{name} is rate limiting us. Give it a few seconds."
    if isinstance(e, openai.APIStatusError) and getattr(e, "status_code", None) == 402:
        return f"The {name} account is out of credit. Top it up, then try again."
    if isinstance(e, openai.APIConnectionError):
        return f"Can't reach {name} right now. Check the internet connection."
    if isinstance(e, openai.BadRequestError):
        if provider == "gemini" and "api key" in msg:
            return f"{name} didn't accept the API key. Check it in SimCast's Settings."
        return f"{name} rejected the request. Check the model in Settings."
    return f"The radio link to {name} dropped. Try again in a moment."


def _json_reply(raw):
    """A JSON object from a model reply: the whole reply, a fenced block, or the {...} inside some prose."""
    if not raw:
        return None
    j = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    for cand in (j, j[j.find("{"):j.rfind("}") + 1] if "{" in j else ""):
        if cand.startswith("{") and cand.endswith("}"):
            try:
                d = json.loads(cand)
            except Exception:
                continue
            if isinstance(d, dict):
                return d
    return None


# ---------------------------------------------------------------------------------------------------------------
# Automatic model choice

PREFERRED = {
    # Best first. Live commentary wants a fast reply (a reaction is only worth saying within seconds) that still
    # writes naturally, so quick models lead and slow reasoning models come last.
    "openai": OPENAI_MODELS,
    "gemini": ["gemini-3.5-flash", "gemini-3.1-pro-preview", "gemini-3.5-flash-lite", "gemini-flash-latest"],
    "deepseek": ["deepseek-chat", "deepseek-flash", "deepseek-v4-pro", "deepseek-reasoner"],
}
TTS_FALLBACK = "gpt-4o-mini-tts"
_NOT_CHAT = ("tts", "audio", "realtime", "transcribe", "whisper", "image", "dall-e", "embedding", "moderation",
             "search", "computer-use", "codex", "instruct", "davinci", "babbage", "sora")
_DETECTED: dict = {}          # (provider, key fingerprint) -> {"chat": [...], "tts": [...], "t": time}
_DETECT_LOCK = threading.Lock()
_DETECTING: set = set()


def _fp(key):
    return hashlib.sha256((key or "").encode()).hexdigest()[:16]


def _usable_chat(provider, ids_created):
    """Chat models in the provider's list, best first: the PREFERRED ones in their order, then (for a model newer
    than this list) other chat models of the same family, newest first."""
    ids = {i for i, _ in ids_created}
    pref = [m for m in PREFERRED.get(provider, []) if m in ids]
    fam = {"openai": "gpt-", "gemini": "gemini-", "deepseek": "deepseek-"}.get(provider, "")
    others = sorted(((c or 0, i) for i, c in ids_created
                     if i.startswith(fam) and i not in pref and not any(x in i for x in _NOT_CHAT)
                     and not any(i.startswith(r) for r in RETIRED_OPENAI_MODELS)), reverse=True)
    return pref + [i for _, i in others]


def detect_models(cfg, provider=None, timeout=10.0, log=None):
    """Ask the provider which models this key can use (blocking: call it from a background thread)."""
    p = provider or ai_provider(cfg)
    key = ai_key(cfg, p)
    if not key:
        return None
    try:
        spec = AI_PROVIDERS[p]
        client = openai_client(key, spec["base_url"]).with_options(timeout=timeout)
        items = list(client.models.list())
        ids_created = [((getattr(m, "id", "") or "").split("/")[-1], getattr(m, "created", 0)) for m in items]
        tts = [i for _, i in sorted(((c or 0, i) for i, c in ids_created if "tts" in i), reverse=True)]
        found = {"chat": _usable_chat(p, ids_created), "tts": tts, "t": time.time()}
        with _DETECT_LOCK:
            _DETECTED[(p, _fp(key))] = found
        if log:
            log(f"{AI_PROVIDERS[p]['name']}: best model {found['chat'][0] if found['chat'] else '(none found)'}")
        return found
    except Exception as e:
        if log:
            log(f"{AI_PROVIDERS[p]['name']}: couldn't list the models ({type(e).__name__}); using {PREFERRED[p][0]}")
        return None


def detect_in_background(cfg, log=None):
    """detect_models() for every provider with a key, once per key, without blocking the caller."""
    for p in AI_PROVIDERS:
        key = ai_key(cfg, p)
        if not key:
            continue
        k = (p, _fp(key))
        with _DETECT_LOCK:
            if k in _DETECTED or k in _DETECTING:
                continue
            _DETECTING.add(k)

        def run(p=p, k=k):
            try:
                detect_models(cfg, p, log=log)
            finally:
                with _DETECT_LOCK:
                    _DETECTING.discard(k)
        threading.Thread(target=run, daemon=True, name=f"models-{p}").start()


def detected(cfg, provider):
    with _DETECT_LOCK:
        return _DETECTED.get((provider, _fp(ai_key(cfg, provider))))


def best_model(cfg, provider):
    d = detected(cfg, provider)
    if d and d["chat"]:
        return d["chat"][0]
    return PREFERRED.get(provider, OPENAI_MODELS)[0]


def model_choices(cfg, provider):
    """What Settings offers: the models this key can use (when known), else the PREFERRED list."""
    d = detected(cfg, provider)
    return (d["chat"] if d and d["chat"] else list(PREFERRED.get(provider, [])))[:12]


def tts_model(cfg):
    """OpenAI speech model: picked in Settings, else the newest one the key can use."""
    chosen = ((cfg or {}).get("openai_tts_model") or "").strip()
    if chosen and chosen != AUTO:
        return chosen
    d = detected(cfg, "openai")
    return d["tts"][0] if d and d["tts"] else TTS_FALLBACK


def import_simcoach_keys():
    """AI keys and provider from SimCoach's settings, if SimCoach is on this PC (only when the user asks)."""
    path = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SimCoach", "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return {}
    out = {k: d[k] for k in ("openai_api_key", "gemini_api_key", "deepseek_api_key") if (d.get(k) or "").strip()}
    if d.get("ai_provider") in AI_PROVIDERS:
        out["ai_provider"] = d["ai_provider"]
    return out
