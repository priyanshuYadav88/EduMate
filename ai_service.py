"""
EduMate Hybrid AI Service Layer
Architecture:
  - Primary Provider: Google Gemini via the official google-genai SDK
  - Fallback Provider: Local Ollama (e.g. gemma3:1b) via Ollama REST API (http://127.0.0.1:11434)
  - Automatic, disciplined fallback:
      * Triggers ONLY on Gemini provider/availability/quota errors (429, 503, 500, network/timeout, missing key)
      * Never falls back for invalid user inputs, validation errors, or application bugs
  - Complete observability:
      * Returns actual provider name ('gemini', 'ollama', or None)
      * Diagnostic status checks for both providers without leaking credentials
"""

import os
import re
import json
import time
import logging
from datetime import datetime, date, timedelta
import requests
from dotenv import load_dotenv
from typing import Dict, Any, Optional, Tuple, List, Set

load_dotenv()

logger = logging.getLogger(__name__)


class AIServiceException(Exception):
    """Base exception for AI service operations."""
    pass


class InvalidInputException(AIServiceException):
    """Raised when user prompt/input is invalid. Must NOT trigger fallback."""
    pass


class HybridAIService:
    """
    Modular Hybrid AI Service managing Google Gemini and Ollama fallback.
    """

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
        groq_base_url: Optional[str] = None,
        ollama_base_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
        gemini_timeout_sec: float = 12.0,
        groq_timeout_sec: float = 15.0,
        ollama_timeout_sec: float = 20.0,
        max_retries: int = 1
    ):
        # Gemini Defaults
        self.gemini_api_key = gemini_api_key or os.getenv('GEMINI_API_KEY', '').strip()
        self.gemini_model = gemini_model or os.getenv('GEMINI_MODEL', 'gemini-3.5-flash').strip()
        self.gemini_timeout_sec = gemini_timeout_sec
        self.gemini_enabled = True
        self.gemini_priority = 1

        # Groq Defaults
        self.groq_api_key = groq_api_key or os.getenv('GROQ_API_KEY', '').strip()
        self.groq_model = groq_model or os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b').strip()
        self.groq_base_url = (groq_base_url or os.getenv('GROQ_BASE_URL', 'https://api.groq.com/openai/v1')).rstrip('/')
        self.groq_timeout_sec = groq_timeout_sec
        self.groq_enabled = bool(self.groq_api_key)
        self.groq_priority = 2

        # Ollama Defaults
        self.ollama_base_url = (ollama_base_url or os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')
        self.ollama_model = ollama_model or os.getenv('OLLAMA_MODEL', 'gemma3:1b').strip()
        self.ollama_timeout_sec = ollama_timeout_sec
        self.ollama_enabled = True
        self.ollama_priority = 3

        self.max_retries = max_retries

    # --------------------------------------------------------------------------
    # Database Configuration Synchronization
    # --------------------------------------------------------------------------
    def sync_from_db(self):
        """
        Synchronizes in-memory provider parameters from AIProviderConfig database table
        if running within an active Flask application context.
        Ensures admin dashboard changes take immediate effect without server restart.
        """
        try:
            from flask import current_app
            if not current_app:
                return
            from models import AIProviderConfig
            configs = AIProviderConfig.query.all()
            for cfg in configs:
                if cfg.provider_id == 'gemini':
                    self.gemini_enabled = cfg.is_enabled
                    self.gemini_priority = cfg.priority
                    if cfg.model_name:
                        self.gemini_model = cfg.model_name
                    if cfg.timeout_sec:
                        self.gemini_timeout_sec = cfg.timeout_sec
                    decrypted = cfg.get_api_key()
                    if decrypted:
                        self.gemini_api_key = decrypted
                    elif os.getenv('GEMINI_API_KEY'):
                        self.gemini_api_key = os.getenv('GEMINI_API_KEY', '').strip()
                elif cfg.provider_id == 'groq':
                    self.groq_enabled = cfg.is_enabled
                    self.groq_priority = cfg.priority
                    if cfg.model_name:
                        self.groq_model = cfg.model_name
                    if cfg.timeout_sec:
                        self.groq_timeout_sec = cfg.timeout_sec
                    if cfg.api_base_url:
                        self.groq_base_url = cfg.api_base_url.rstrip('/')
                    decrypted = cfg.get_api_key()
                    if decrypted:
                        self.groq_api_key = decrypted
                    elif os.getenv('GROQ_API_KEY'):
                        self.groq_api_key = os.getenv('GROQ_API_KEY', '').strip()
                elif cfg.provider_id == 'ollama':
                    self.ollama_enabled = cfg.is_enabled
                    self.ollama_priority = cfg.priority
                    if cfg.model_name:
                        self.ollama_model = cfg.model_name
                    if cfg.timeout_sec:
                        self.ollama_timeout_sec = cfg.timeout_sec
                    if cfg.api_base_url:
                        self.ollama_base_url = cfg.api_base_url.rstrip('/')
        except Exception as e:
            logger.debug(f"AI provider DB sync notice: {e}")

    # --------------------------------------------------------------------------
    # Helpers: Key Masking and Secret Sanitization
    # --------------------------------------------------------------------------
    def _mask_key(self, key: Optional[str]) -> str:
        if not key:
            return "Not configured"
        key = key.strip()
        if len(key) <= 8:
            return "••••••••"
        return f"{key[:4]}••••••••{key[-4:]}"

    def _sanitize_secrets(self, text: str) -> str:
        """Strips raw API secrets from logs, exception traces, and error returns."""
        cleaned = str(text)
        for k in [self.gemini_api_key, self.groq_api_key]:
            if k and len(k) > 4:
                cleaned = cleaned.replace(k, f"{k[:4]}...[REDACTED]")
        return cleaned

    # --------------------------------------------------------------------------
    # 1. Provider Health & Diagnostics (Safe for Display)
    # --------------------------------------------------------------------------
    def get_provider_status(self) -> Dict[str, Any]:
        """
        Returns connectivity and configuration status for Gemini, Groq, and Ollama.
        Masks all sensitive keys.
        """
        self.sync_from_db()
        has_gemini_key = bool(self.gemini_api_key and len(self.gemini_api_key) > 8)
        has_groq_key = bool(self.groq_api_key and len(self.groq_api_key) > 8)

        # Check Ollama reachability
        ollama_reachable = False
        ollama_installed_models = []
        try:
            resp = requests.get(f"{self.ollama_base_url}/api/tags", timeout=3.0)
            if resp.status_code == 200:
                ollama_reachable = True
                data = resp.json()
                ollama_installed_models = [m.get('name') for m in data.get('models', []) if 'name' in m]
        except Exception:
            ollama_reachable = False

        ollama_model_ready = any(self.ollama_model in m for m in ollama_installed_models) if ollama_reachable else False

        overall_available = (
            (self.gemini_enabled and has_gemini_key) or
            (self.groq_enabled and has_groq_key) or
            (self.ollama_enabled and ollama_reachable and ollama_model_ready)
        )

        return {
            'overall_available': overall_available,
            'primary': {
                'provider': 'gemini',
                'name': 'Google Gemini',
                'enabled': self.gemini_enabled,
                'priority': self.gemini_priority,
                'model': self.gemini_model,
                'configured': has_gemini_key,
                'key_masked': self._mask_key(self.gemini_api_key),
                'status': 'Configured' if has_gemini_key else 'Missing API Key'
            },
            'groq': {
                'provider': 'groq',
                'name': 'Groq API',
                'enabled': self.groq_enabled,
                'priority': self.groq_priority,
                'model': self.groq_model,
                'configured': has_groq_key,
                'key_masked': self._mask_key(self.groq_api_key),
                'status': 'Configured' if has_groq_key else 'Missing API Key'
            },
            'fallback': {
                'provider': 'ollama',
                'name': 'Ollama (Local AI)',
                'enabled': self.ollama_enabled,
                'priority': self.ollama_priority,
                'model': self.ollama_model,
                'base_url': self.ollama_base_url,
                'reachable': ollama_reachable,
                'model_ready': ollama_model_ready,
                'available_models': ollama_installed_models,
                'status': 'Ready' if (ollama_reachable and ollama_model_ready) else (
                    'Server unreachable' if not ollama_reachable else f"Model '{self.ollama_model}' not found"
                )
            }
        }

    # --------------------------------------------------------------------------
    # 2. Provider: Google Gemini
    # --------------------------------------------------------------------------
    def _call_gemini(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Executes text generation using Google Gemini (SDK or REST fallback)."""
        key = api_key or self.gemini_api_key
        if not key:
            raise AIServiceException("Gemini API key is not configured.")
        m = model or self.gemini_model
        timeout = timeout_sec or self.gemini_timeout_sec

        # Attempt google.genai SDK
        has_sdk = False
        try:
            import google.genai
            from google.genai import errors, types
            has_sdk = True
        except ImportError:
            has_sdk = False

        if has_sdk:
            client = google.genai.Client(
                api_key=key,
                http_options={'timeout': int(timeout * 1000)}
            )
            config = types.GenerateContentConfig(system_instruction=system_instruction) if system_instruction else None

            # Build content payload (string if single-turn, dict list if multi-turn)
            if chat_history:
                sdk_contents = []
                for turn in chat_history:
                    role = 'model' if turn.get('role') in ('assistant', 'model') else 'user'
                    sdk_contents.append({"role": role, "parts": [{"text": turn.get('content', '')}]})
                sdk_contents.append({"role": "user", "parts": [{"text": prompt}]})
            else:
                sdk_contents = prompt

            last_error = None
            for attempt in range(1 + self.max_retries):
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=sdk_contents,
                        config=config
                    )
                    if response and hasattr(response, 'text') and response.text:
                        return response.text.strip()
                    raise AIServiceException("Gemini returned an empty response.")
                except errors.ClientError as e:
                    raise AIServiceException(f"Gemini client error (code {getattr(e, 'code', '4xx')}): {getattr(e, 'message', str(e))}")
                except errors.ServerError as e:
                    last_error = e
                    if attempt < self.max_retries:
                        time.sleep(1.0)
                        continue
                    raise AIServiceException(f"Gemini server error (code {getattr(e, 'code', '5xx')}): {str(e)}")
                except Exception as e:
                    last_error = e
                    if attempt < self.max_retries:
                        time.sleep(1.0)
                        continue
                    raise AIServiceException(f"Gemini request failed: {self._sanitize_secrets(str(e))}")
            raise AIServiceException(f"Gemini failed after retries: {self._sanitize_secrets(str(last_error))}")

        # REST API fallback
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
        rest_contents = []
        if chat_history:
            for turn in chat_history:
                role = 'model' if turn.get('role') in ('assistant', 'model') else 'user'
                rest_contents.append({"role": role, "parts": [{"text": turn.get('content', '')}]})
        rest_contents.append({"role": "user", "parts": [{"text": prompt}]})
        payload: Dict[str, Any] = {
            "contents": rest_contents
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        last_error = None
        for attempt in range(1 + self.max_retries):
            try:
                resp = requests.post(
                    endpoint,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=timeout
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get('candidates', [])
                    if candidates and 'content' in candidates[0] and 'parts' in candidates[0]['content']:
                        parts = candidates[0]['content']['parts']
                        if parts and 'text' in parts[0]:
                            return parts[0]['text'].strip()
                    raise AIServiceException("Gemini REST API returned an empty or malformed candidate.")
                elif resp.status_code in (400, 401, 403, 404):
                    err_msg = resp.text
                    try:
                        err_msg = resp.json().get('error', {}).get('message', resp.text)
                    except Exception:
                        pass
                    raise AIServiceException(f"Gemini provider error ({resp.status_code}): {err_msg}")
                elif resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        time.sleep(1.0)
                        continue
                    raise AIServiceException(f"Gemini server error ({resp.status_code}): {resp.text}")
                else:
                    raise AIServiceException(f"Gemini unexpected status ({resp.status_code}): {resp.text}")
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise AIServiceException(f"Gemini request failed: {self._sanitize_secrets(str(e))}")

        raise AIServiceException(f"Gemini REST failed after retries: {self._sanitize_secrets(str(last_error))}")

    # --------------------------------------------------------------------------
    # 3. Provider: Groq API (OpenAI-compatible Chat Completions)
    # --------------------------------------------------------------------------
    def _call_groq(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        Executes text generation using official Groq OpenAI-compatible chat completions endpoint.
        """
        key = api_key or self.groq_api_key
        if not key or not str(key).strip():
            raise AIServiceException("Groq API key is missing or not configured.")
        clean_key = str(key).strip()
        m = model or self.groq_model
        timeout = timeout_sec or self.groq_timeout_sec

        url = f"{self.groq_base_url.rstrip('/')}/chat/completions"
        auth_header = clean_key if clean_key.startswith("Bearer ") else f"Bearer {clean_key}"
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json"
        }
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        if chat_history:
            for turn in chat_history:
                r = turn.get('role', 'user')
                c = turn.get('content', '')
                if r in ('user', 'assistant') and c:
                    messages.append({"role": r, "content": c})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": m,
            "messages": messages,
            "temperature": 0.4
        }

        last_error = None
        max_attempts = 1 + max(2, self.max_retries)
        for attempt in range(max_attempts):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0] and "content" in choices[0]["message"]:
                        return choices[0]["message"]["content"].strip()
                    raise AIServiceException("Groq returned an empty response.")

                # Extract detailed error message from response JSON if present
                err_detail = ""
                try:
                    err_json = resp.json()
                    err_data = err_json.get("error", {})
                    if isinstance(err_data, dict):
                        err_detail = err_data.get("message", "")
                    elif isinstance(err_data, str):
                        err_detail = err_data
                except Exception:
                    err_detail = resp.text

                detail_suffix = f": {err_detail}" if err_detail else ""

                if resp.status_code == 401:
                    raise AIServiceException(f"Groq error (401 Unauthorized): Invalid or incorrectly loaded API key{detail_suffix}")
                elif resp.status_code == 403:
                    raise AIServiceException(f"Groq error (403 Forbidden): Permission or access denied{detail_suffix}")
                elif resp.status_code == 404:
                    raise AIServiceException(f"Groq error (404 Not Found): Invalid endpoint or model '{m}'{detail_suffix}")
                elif resp.status_code == 429:
                    if attempt < max_attempts - 1:
                        match = re.search(r'try again in ([0-9.]+)\s*s', err_detail, re.IGNORECASE)
                        sleep_time = max(3.0, float(match.group(1)) + 1.2) if match else 3.5
                        time.sleep(min(sleep_time, 15.0))
                        continue
                    raise AIServiceException(f"Groq error (429 Rate Limit): API rate limit or quota exceeded{detail_suffix}")
                elif 500 <= resp.status_code < 600:
                    last_error = AIServiceException(f"Groq server error ({resp.status_code}): Upstream service error{detail_suffix}")
                    if attempt < self.max_retries:
                        time.sleep(1.0)
                        continue
                    raise last_error
                else:
                    raise AIServiceException(f"Groq unexpected status ({resp.status_code}){detail_suffix}")

            except requests.exceptions.Timeout as e:
                last_error = AIServiceException(f"Groq connection timeout: Request timed out after {timeout}s (Network issue).")
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise last_error
            except requests.exceptions.ConnectionError as e:
                last_error = AIServiceException(f"Groq connection failure: Unable to reach {self.groq_base_url} (Network issue).")
                if attempt < self.max_retries:
                    time.sleep(1.0)
                    continue
                raise last_error
            except requests.exceptions.RequestException as e:
                raise AIServiceException(f"Groq request failed: {self._sanitize_secrets(str(e))}")

        if last_error:
            raise last_error
        raise AIServiceException("Groq request failed after retries.")

    # --------------------------------------------------------------------------
    # 4. Provider: Local Ollama
    # --------------------------------------------------------------------------
    def _call_ollama(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Executes text generation using local Ollama REST API."""
        m = model or self.ollama_model
        url = (base_url or self.ollama_base_url).rstrip('/')
        timeout = timeout_sec or self.ollama_timeout_sec

        if chat_history:
            endpoint = f"{url}/api/chat"
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            for turn in chat_history:
                r = turn.get('role', 'user')
                c = turn.get('content', '')
                if r in ('user', 'assistant') and c:
                    messages.append({"role": r, "content": c})
            messages.append({"role": "user", "content": prompt})

            payload: Dict[str, Any] = {
                'model': m,
                'messages': messages,
                'stream': False
            }
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get('message', {}).get('content', '').strip()
                    if text:
                        return text
            except Exception:
                pass  # Fall back to generate endpoint

        endpoint = f"{url}/api/generate"
        payload: Dict[str, Any] = {
            'model': m,
            'prompt': prompt,
            'stream': False
        }
        if system_instruction:
            payload['system'] = system_instruction

        try:
            resp = requests.post(endpoint, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get('response', '').strip()
                if text:
                    return text
                raise AIServiceException("Ollama returned an empty response.")
            raise AIServiceException(f"Ollama HTTP status {resp.status_code}: {resp.text}")
        except requests.exceptions.RequestException as e:
            raise AIServiceException(f"Ollama server unavailable at {url}: {str(e)}")

    # --------------------------------------------------------------------------
    # 5. Connection Diagnostics Testing
    # --------------------------------------------------------------------------
    def test_provider_connection(
        self,
        provider_id: str,
        custom_key: Optional[str] = None,
        custom_model: Optional[str] = None,
        custom_url: Optional[str] = None,
        custom_timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Executes a targeted, lightweight diagnostic connection test for a specific provider.
        Returns a dictionary with success status, state, and human-readable message.
        """
        self.sync_from_db()
        p_id = provider_id.strip().lower()

        try:
            if p_id == 'gemini':
                key = custom_key or self.gemini_api_key
                if not key:
                    return {'success': False, 'status': 'error', 'message': 'Gemini API key is missing or not configured.'}
                m = custom_model or self.gemini_model
                out = self._call_gemini("Ping test. Respond with 'PONG'.", model=m, api_key=key, timeout_sec=custom_timeout or 8.0)
                return {'success': True, 'status': 'active', 'message': f"Connected successfully to Gemini model '{m}'. Response received."}

            elif p_id == 'groq':
                key = custom_key or self.groq_api_key
                if not key or not str(key).strip():
                    return {'success': False, 'status': 'error', 'message': 'Groq API key is missing or not configured.'}
                clean_key = str(key).strip()
                m = custom_model or self.groq_model
                url = (custom_url or self.groq_base_url).rstrip('/')
                timeout = custom_timeout or 10.0
                auth_header = clean_key if clean_key.startswith("Bearer ") else f"Bearer {clean_key}"

                # Step 1: Query GET /models to verify API key and model availability
                models_url = f"{url}/models"
                try:
                    m_resp = requests.get(models_url, headers={"Authorization": auth_header}, timeout=timeout)
                except requests.exceptions.Timeout:
                    return {'success': False, 'status': 'error', 'message': f"Groq connection timeout: Request to {models_url} timed out after {timeout}s (Network issue)."}
                except requests.exceptions.ConnectionError:
                    return {'success': False, 'status': 'error', 'message': f"Groq connection failure: Unable to reach {models_url} (Network issue)."}
                except requests.exceptions.RequestException as e:
                    return {'success': False, 'status': 'error', 'message': f"Groq request failed: {self._sanitize_secrets(str(e))}"}

                if m_resp.status_code == 401:
                    return {'success': False, 'status': 'error', 'message': 'Groq error (401 Unauthorized): Invalid or incorrectly loaded API key.'}
                elif m_resp.status_code == 403:
                    return {'success': False, 'status': 'error', 'message': 'Groq error (403 Forbidden): Permission or access denied.'}
                elif m_resp.status_code == 404:
                    return {'success': False, 'status': 'error', 'message': f"Groq error (404 Not Found): Invalid endpoint ({models_url})."}
                elif m_resp.status_code != 200:
                    return {'success': False, 'status': 'error', 'message': f"Groq error ({m_resp.status_code}): {self._sanitize_secrets(m_resp.text)}"}

                try:
                    data = m_resp.json()
                    available_models = [item.get('id') for item in data.get('data', []) if isinstance(item, dict) and item.get('id')]
                except Exception:
                    available_models = []

                if available_models and m not in available_models:
                    chat_models = [mod for mod in available_models if not mod.startswith('whisper') and 'guard' not in mod]
                    return {
                        'success': False,
                        'status': 'error',
                        'message': f"Groq error (404 Not Found): Configured model '{m}' does not exist or is not available. Available chat models: {', '.join(chat_models[:4]) or ', '.join(available_models[:4])}."
                    }

                # Step 2: Minimal POST /chat/completions verification request
                out = self._call_groq(
                    prompt="Reply with: Groq connection successful",
                    model=m,
                    api_key=clean_key,
                    timeout_sec=timeout
                )
                return {
                    'success': True,
                    'status': 'active',
                    'message': f"Connected successfully to Groq model '{m}'. Response: {out}"
                }

            elif p_id == 'ollama':
                url = (custom_url or self.ollama_base_url).rstrip('/')
                m = custom_model or self.ollama_model
                resp = requests.get(f"{url}/api/tags", timeout=custom_timeout or 5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [mod.get('name') for mod in data.get('models', []) if 'name' in mod]
                    if any(m in mod for mod in models):
                        return {'success': True, 'status': 'active', 'message': f"Ollama online at {url}. Target model '{m}' is installed."}
                    return {'success': False, 'status': 'error', 'message': f"Ollama online at {url}, but model '{m}' is not installed ({', '.join(models[:3]) or 'none'})."}
                return {'success': False, 'status': 'error', 'message': f"Ollama returned HTTP status {resp.status_code}."}

            else:
                return {'success': False, 'status': 'error', 'message': f"Unknown AI provider identifier '{provider_id}'."}

        except Exception as e:
            sanitized = self._sanitize_secrets(str(e))
            return {'success': False, 'status': 'error', 'message': sanitized}

    # --------------------------------------------------------------------------
    # 6. Centralized Multi-Provider Dispatcher with Sequential Priority Fallback
    # --------------------------------------------------------------------------
    def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Main text generation dispatcher.
        1. Validates input.
        2. Syncs enabled providers from DB or uses configured defaults.
        3. Executes providers sequentially in strict priority order (1, 2, 3...).
        4. Skips disabled providers completely without issuing requests.
        5. Automatically falls back to next enabled provider if primary fails.
        6. Indicates clearly which provider actually generated the output.
        """
        clean_prompt = (prompt or '').strip()
        if not clean_prompt:
            raise InvalidInputException("Prompt cannot be empty or whitespace only.")

        self.sync_from_db()

        # Build list of active enabled providers
        active_providers = []

        if self.gemini_enabled:
            active_providers.append({
                'id': 'gemini',
                'name': 'Google Gemini',
                'model': self.gemini_model,
                'priority': self.gemini_priority,
                'call': lambda: self._call_gemini(clean_prompt, system_instruction=system_instruction, chat_history=chat_history)
            })

        if self.groq_enabled:
            active_providers.append({
                'id': 'groq',
                'name': 'Groq API',
                'model': self.groq_model,
                'priority': self.groq_priority,
                'call': lambda: self._call_groq(clean_prompt, system_instruction=system_instruction, chat_history=chat_history)
            })

        if self.ollama_enabled:
            active_providers.append({
                'id': 'ollama',
                'name': 'Ollama (Local AI)',
                'model': self.ollama_model,
                'priority': self.ollama_priority,
                'call': lambda: self._call_ollama(clean_prompt, system_instruction=system_instruction, chat_history=chat_history)
            })

        # Sort by priority ascending (1 = Primary, 2 = Fallback 1, 3 = Fallback 2)
        active_providers.sort(key=lambda x: x['priority'])

        if not active_providers:
            return {
                'success': False,
                'provider': None,
                'provider_name': None,
                'model': None,
                'fallback_used': False,
                'error_message': 'No AI providers are currently enabled in the Admin API Management Center.'
            }

        provider_errors: Dict[str, str] = {}

        for attempt_idx, prov in enumerate(active_providers):
            try:
                output = prov['call']()
                return {
                    'success': True,
                    'provider': prov['id'],
                    'provider_name': prov['name'],
                    'model': prov['model'],
                    'fallback_used': (attempt_idx > 0),
                    'gemini_error': provider_errors.get('gemini'),
                    'groq_error': provider_errors.get('groq'),
                    'ollama_error': provider_errors.get('ollama'),
                    'response': output
                }
            except Exception as e:
                sanitized_err = self._sanitize_secrets(str(e))
                logger.warning(f"Provider {prov['name']} failed on attempt {attempt_idx + 1} ({sanitized_err}). Falling back...")
                provider_errors[prov['id']] = sanitized_err

        # All enabled providers failed
        if 'gemini' in provider_errors and 'ollama' in provider_errors:
            error_msg = f"Both AI providers are currently unavailable (offline). Primary (Gemini): {provider_errors.get('gemini')} | Fallback (Ollama): {provider_errors.get('ollama')}"
            if 'groq' in provider_errors:
                error_msg += f" | Fallback (Groq): {provider_errors.get('groq')}"
        else:
            error_msg = f"All enabled AI providers failed: {'; '.join(f'{k}: {v}' for k, v in provider_errors.items())}"

        return {
            'success': False,
            'provider': None,
            'provider_name': None,
            'model': None,
            'fallback_used': True,
            'gemini_error': provider_errors.get('gemini'),
            'groq_error': provider_errors.get('groq'),
            'ollama_error': provider_errors.get('ollama'),
            'errors': provider_errors,
            'error_message': error_msg
        }



    # --------------------------------------------------------------------------
    # 5. Specialized Academic Capabilities
    # --------------------------------------------------------------------------
    def _clean_json_str(self, text: str) -> str:
        """Strips markdown code blocks (e.g. ```json ... ```) to isolate raw JSON."""
        clean = (text or '').strip()
        if '```' in clean:
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', clean, re.IGNORECASE)
            if match:
                clean = match.group(1).strip()
        return clean

    def extract_syllabus_structure(
        self,
        pages_data: List[Dict[str, Any]],
        subject_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Module 2: Intelligent AI Syllabus Extraction & Structuring.
        Transforms page-by-page extracted PDF text into structured JSON matching:
        {
          "is_syllabus": true,
          "subject": "Course Name",
          "course_code": "CS301",
          "units": [
            {
              "unit_number": 1,
              "title": "Unit Title",
              "topics": [
                {
                  "name": "Topic Name",
                  "subtopics": ["Sub 1", "Sub 2"],
                  "source_pages": [1, 2]
                }
              ]
            }
          ],
          "unassigned_topics": [
            {
              "name": "Unassigned Topic",
              "subtopics": [],
              "source_pages": [1],
              "needs_review": true
            }
          ]
        }
        Uses page filtering, chunking, unit merging, topic deduplication,
        and disciplined fallback to rule-based heuristic parsing.
        """
        if not pages_data:
            raise InvalidInputException("No page text provided for syllabus extraction.")

        from pdf_service import parse_syllabus_heuristic, detect_syllabus_presence, is_non_syllabus_line

        # Quick pre-validation: check whether the document has any syllabus presence
        is_syllabus_heuristic, presence_msg = detect_syllabus_presence(pages_data)

        # Filter out pages that are purely non-syllabus (e.g. certificates, fee tables, pure headers)
        filtered_pages = []
        for p in pages_data:
            lines = [l.strip() for l in p.get('text', '').splitlines() if l.strip()]
            valid_lines = [l for l in lines if not is_non_syllabus_line(l)]
            # If page contains content that isn't purely administrative metadata, keep for analysis
            if valid_lines:
                filtered_pages.append(p)

        target_pages = filtered_pages if filtered_pages else pages_data

        # Process in chunks of up to 3 pages to respect token limits
        chunk_size = 3
        chunks = [target_pages[i:i + chunk_size] for i in range(0, len(target_pages), chunk_size)]

        merged_subject = subject_name if subject_name else None
        merged_course_code = None
        merged_units_dict: Dict[int, Dict[str, Any]] = {}
        merged_unassigned: List[Dict[str, Any]] = []
        ai_provider_used = "Heuristic Parser"
        ai_model_used = "rule-engine"
        fallback_flag = False
        any_ai_success = False

        system_instruction = (
            "You are an expert academic curriculum parser and syllabus extraction AI. "
            "Your task is to identify and extract ONLY official academic syllabus content from university course documents.\n"
            "STRICT GUIDELINES:\n"
            "1. First, check if the text contains course syllabus/curriculum content. If it contains ONLY cover pages, "
            "certificates, acknowledgements, fee receipts, examination rules, or administrative notices, indicate 'is_syllabus': false.\n"
            "2. Identify the Subject Name and Course Code (e.g. CS301, KCS-401) if available.\n"
            "3. Identify unit/module headings (UNIT 1, UNIT I, UNIT-II, Module 1, Module I, Chapter 1, Section A, etc.).\n"
            "4. Extract topics and subtopics strictly under their correct unit, preserving original wording and order.\n"
            "5. Completely IGNORE unrelated content: cover pages, certificates, acknowledgements, university vision/mission, "
            "examination passing rules, fee details, circulars, and running page headers/footers.\n"
            "6. Never invent or hallucinate missing topics or units. Use actual text only.\n"
            "7. If a topic cannot be confidently assigned to a unit, place it in 'unassigned_topics' with 'needs_review': true.\n"
            "8. Return STRICTLY valid JSON conforming to the requested schema without markdown conversational text."
        )

        for chunk in chunks:
            chunk_text_parts = []
            page_numbers = []
            for p in chunk:
                page_numbers.append(p['page'])
                chunk_text_parts.append(f"--- [Page {p['page']}] ---\n{p['text']}")

            chunk_combined = "\n\n".join(chunk_text_parts)
            prompt = (
                f"Extract the syllabus hierarchy from these pages ({', '.join(map(str, page_numbers))}).\n"
                f"Output strictly valid JSON with this exact structure:\n"
                f'{{\n'
                f'  "is_syllabus": true,\n'
                f'  "subject": "Course Name",\n'
                f'  "course_code": "CS301",\n'
                f'  "units": [\n'
                f'    {{\n'
                f'      "unit_number": 1,\n'
                f'      "title": "Unit 1: Foundations",\n'
                f'      "topics": [\n'
                f'        {{\n'
                f'          "name": "Topic Title",\n'
                f'          "subtopics": ["Subtopic A", "Subtopic B"],\n'
                f'          "source_pages": [{page_numbers[0]}]\n'
                f'        }}\n'
                f'      ]\n'
                f'    }}\n'
                f'  ],\n'
                f'  "unassigned_topics": [\n'
                f'    {{\n'
                f'      "name": "Ambiguous Topic",\n'
                f'      "subtopics": [],\n'
                f'      "source_pages": [{page_numbers[0]}],\n'
                f'      "needs_review": true\n'
                f'    }}\n'
                f'  ]\n'
                f'}}\n\n'
                f"Document Pages:\n{chunk_combined}"
            )

            try:
                resp = self.generate_response(prompt=prompt, system_instruction=system_instruction)
                if resp.get('success') and resp.get('response'):
                    clean_json = self._clean_json_str(resp['response'])
                    data = json.loads(clean_json)

                    if data.get('is_syllabus') is False and not data.get('units'):
                        continue

                    any_ai_success = True
                    ai_provider_used = resp.get('provider') or ai_provider_used
                    ai_model_used = resp.get('model') or ai_model_used
                    fallback_flag = resp.get('fallback_used', False)

                    if data.get('subject') and not merged_subject:
                        merged_subject = data['subject'].strip()
                    if data.get('course_code') and not merged_course_code:
                        merged_course_code = data['course_code'].strip()

                    # Merge units
                    for unit_item in data.get('units', []):
                        u_num = unit_item.get('unit_number') or (len(merged_units_dict) + 1)
                        if u_num not in merged_units_dict:
                            merged_units_dict[u_num] = {
                                "unit_number": u_num,
                                "title": unit_item.get('title') or f"Unit {u_num}",
                                "topics": []
                            }

                        existing_topic_names = {t['name'].lower().strip() for t in merged_units_dict[u_num]['topics']}

                        for t in unit_item.get('topics', []):
                            t_name = (t.get('name') or '').strip()
                            if not t_name:
                                continue
                            if t_name.lower() in existing_topic_names:
                                for ex in merged_units_dict[u_num]['topics']:
                                    if ex['name'].lower().strip() == t_name.lower():
                                        for st in t.get('subtopics', []):
                                            if st not in ex['subtopics']:
                                                ex['subtopics'].append(st)
                                        for sp in t.get('source_pages', []):
                                            if sp not in ex['source_pages']:
                                                ex['source_pages'].append(sp)
                            else:
                                merged_units_dict[u_num]['topics'].append({
                                    "name": t_name,
                                    "subtopics": t.get('subtopics') or [],
                                    "source_pages": t.get('source_pages') or page_numbers
                                })
                                existing_topic_names.add(t_name.lower())

                    # Merge unassigned topics
                    for ut in data.get('unassigned_topics', []):
                        ut_name = (ut.get('name') or '').strip()
                        if ut_name and not any(x['name'].lower().strip() == ut_name.lower() for x in merged_unassigned):
                            merged_unassigned.append({
                                "name": ut_name,
                                "subtopics": ut.get('subtopics') or [],
                                "source_pages": ut.get('source_pages') or page_numbers,
                                "needs_review": True
                            })
            except Exception as ex:
                logger.warning(f"AI syllabus chunk parsing note ({ex}); using heuristic fallback.")

        # Check if AI produced valid units
        sorted_units = [merged_units_dict[k] for k in sorted(merged_units_dict.keys()) if merged_units_dict[k]['topics']]
        if sorted_units:
            total_topics_count = sum(len(u['topics']) for u in sorted_units)
            return {
                "success": True,
                "is_syllabus": True,
                "subject": merged_subject or "Academic Course Syllabus",
                "detected_subject": merged_subject,
                "target_subject": subject_name,
                "course_code": merged_course_code,
                "units": sorted_units,
                "unassigned_topics": merged_unassigned,
                "total_topics": total_topics_count,
                "provider": ai_provider_used,
                "model": ai_model_used,
                "fallback_used": fallback_flag
            }

        # Fallback to deterministic heuristic parser if AI returned no units or failed
        heuristic_res = parse_syllabus_heuristic(pages_data, subject_name=subject_name)
        if not heuristic_res.get('is_syllabus'):
            return {
                "success": False,
                "is_syllabus": False,
                "subject": None,
                "course_code": None,
                "units": [],
                "unassigned_topics": [],
                "error_message": heuristic_res.get('error') or "No academic syllabus detected in the uploaded PDF.",
                "provider": "Heuristic Rule Engine",
                "model": "regex-parser",
                "fallback_used": True
            }

        h_units = heuristic_res.get('units', [])
        h_unassigned = heuristic_res.get('unassigned_topics', [])
        total_topics = sum(len(u.get('topics', [])) for u in h_units)

        return {
            "success": True,
            "is_syllabus": True,
            "subject": heuristic_res.get('subject') or "Academic Course Syllabus",
            "detected_subject": heuristic_res.get('detected_subject') or heuristic_res.get('subject'),
            "target_subject": heuristic_res.get('target_subject') or subject_name,
            "course_code": heuristic_res.get('course_code') or merged_course_code,
            "units": h_units,
            "unassigned_topics": h_unassigned,
            "total_topics": total_topics,
            "provider": "Heuristic Rule Engine (Fallback)",
            "model": "regex-parser",
            "fallback_used": True
        }


    def generate_study_roadmap(
        self,
        subject_name: str,
        units_and_topics: Optional[List[Dict[str, Any]]] = None,
        exam_date: Optional[date] = None,
        daily_hours: float = 2.0,
        preferred_days: Optional[List[str]] = None,
        completed_topics: Optional[Set[str]] = None,
        revision_preference: str = 'standard',
        topics_input: Optional[List[Dict[str, Any]]] = None,
        today: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Module 4: AI Study Roadmap Generator.
        Generates day-wise roadmap items respecting examination deadlines,
        daily study hours, completed topics, and revision preferences.
        """
        ref_today = today if today is not None else date.today()
        if not exam_date:
            raise InvalidInputException("Exam date is required.")

        available_days = (exam_date - ref_today).days
        if available_days <= 0:
            raise InvalidInputException("Exam date must be at least 1 day in the future.")

        completed_set = {t.lower().strip() for t in (completed_topics or set())}

        # Resolve topics input
        raw_topics = topics_input if topics_input is not None else (units_and_topics or [])

        # Flatten topic list if needed
        flat_topics = []
        for item in raw_topics:
            if isinstance(item, dict):
                u_name = item.get('unit_name') or item.get('unit') or "Unit 1"
                t_title = item.get('topic_title') or item.get('title') or item.get('name') or "Core Topic"
                is_comp = item.get('is_completed', False) or (t_title.lower().strip() in completed_set)
                tid = item.get('topic_id')
            else:
                u_name = "Unit 1"
                t_title = str(item).strip()
                is_comp = t_title.lower().strip() in completed_set
                tid = None

            flat_topics.append({
                "unit_name": u_name,
                "topic_title": t_title,
                "is_completed": is_comp,
                "topic_id": tid
            })

        if not flat_topics:
            raise InvalidInputException("No syllabus topics available to generate a roadmap.")

        # Capacity calculation: 1.5 hours estimated per topic
        est_hours_per_topic = 1.5
        total_required_hours = len(flat_topics) * est_hours_per_topic
        total_available_hours = available_days * daily_hours
        has_warning = total_required_hours > total_available_hours

        # Revision ratio calculation
        rev_percent = 0.20 if revision_preference == 'intensive' else 0.15
        revision_days = max(1, min(6, int(available_days * rev_percent)))
        if available_days <= 3:
            revision_days = 1
        study_days = max(1, available_days - revision_days)

        roadmap_items: List[Dict[str, Any]] = []
        topics_per_day = max(1, int(round(len(flat_topics) / study_days)))

        # Assign study days
        for idx, t in enumerate(flat_topics):
            day_offset = min(study_days - 1, idx // topics_per_day)
            scheduled_date = ref_today + timedelta(days=day_offset + 1)

            roadmap_items.append({
                "day_number": day_offset + 1,
                "scheduled_date": scheduled_date,
                "unit_name": t["unit_name"],
                "topic_title": t["topic_title"],
                "estimated_hours": min(daily_hours, est_hours_per_topic),
                "is_revision": False,
                "is_completed": t["is_completed"],
                "topic_id": t.get("topic_id")
            })

        # Append dedicated revision milestones
        unique_units = list(dict.fromkeys([t["unit_name"] for t in flat_topics]))
        for r_idx in range(revision_days):
            rev_day = study_days + r_idx + 1
            rev_date = ref_today + timedelta(days=rev_day)
            rev_unit = unique_units[r_idx % len(unique_units)] if unique_units else "Comprehensive Syllabus"

            roadmap_items.append({
                "day_number": rev_day,
                "scheduled_date": rev_date,
                "unit_name": rev_unit,
                "topic_title": f"Comprehensive Revision & Practice: {rev_unit}",
                "estimated_hours": daily_hours,
                "is_revision": True,
                "is_completed": False
            })

        return {
            "success": True,
            "subject": subject_name,
            "exam_date": exam_date,
            "daily_hours": daily_hours,
            "total_days": available_days,
            "study_days": study_days,
            "revision_days": revision_days,
            "total_required_hours": total_required_hours,
            "total_available_hours": total_available_hours,
            "has_workload_warning": has_warning,
            "items": roadmap_items
        }

    def chat_study_assistant(
        self,
        user_message: str,
        approved_syllabus_context: List[Dict[str, Any]],
        chat_history: Optional[List[Dict[str, str]]] = None,
        selected_context: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Module 5: EduMate AI Assistant.
        Answers student queries with natural, ChatGPT-style conversational intelligence,
        grounded in syllabus when available, multilingual (English, Hindi, Hinglish),
        and contextual across conversation turns.
        """
        clean_msg = (user_message or '').strip()
        if not clean_msg:
            raise InvalidInputException("Please enter a valid study query.")

        # Build concise syllabus reference text if available
        syllabus_lines = []
        for sub in (approved_syllabus_context or []):
            sub_name = sub.get('subject_name', 'Subject')
            syllabus_lines.append(f"Subject: {sub_name}")
            for u in sub.get('units', []):
                syllabus_lines.append(f"  {u.get('unit_title', 'Unit')}:")
                for t in u.get('topics', []):
                    t_str = f"    - {t.get('title')}"
                    if t.get('source_pages'):
                        t_str += f" (Source Pages: {t['source_pages']})"
                    syllabus_lines.append(t_str)

        syllabus_summary = "\n".join(syllabus_lines[:60])  # Bounded to avoid prompt bloat

        context_parts = []
        if selected_context:
            subj = selected_context.get('subject_name')
            unit = selected_context.get('unit_name')
            top = selected_context.get('topic_title')
            ctx_desc = []
            if subj: ctx_desc.append(f"Subject: {subj}")
            if unit: ctx_desc.append(f"Unit: {unit}")
            if top: ctx_desc.append(f"Topic: {top}")
            if ctx_desc:
                context_parts.append(f"CURRENT FOCUSED TOPIC: {', '.join(ctx_desc)}")
            if selected_context.get('preferred_language'):
                pref_lang = selected_context.get('preferred_language')
                context_parts.append(f"STUDENT PREFERRED EXPLANATION LANGUAGE: {pref_lang}. Adapt your natural conversational explanation to favor {pref_lang} (e.g. English, Hindi, or conversational Hinglish) while keeping technical symbols and code accurate.")

        if syllabus_summary:
            context_parts.append(f"STUDENT'S UPLOADED SYLLABUS REFERENCE (use as background context):\n{syllabus_summary}")

        context_block = "\n\n".join(context_parts) if context_parts else "No specific syllabus uploaded yet. Assist using general academic knowledge."

        system_instruction = (
            "You are EduMate AI, an intelligent, friendly, and expert college study companion and academic tutor.\n"
            "Your goal is to have natural, clear, ChatGPT-style conversations that genuinely help students understand, learn, and excel.\n\n"
            f"{context_block}\n\n"
            "CONVERSATIONAL GUIDELINES:\n"
            "1. Language & Tone: Adapt seamlessly to the student's language. If the student asks in English, reply in natural, clear English. "
            "If they ask in Hinglish (e.g., 'samjha do', 'in Hinglish', 'bhai pointer kyun use karte hain'), reply in natural, conversational Hinglish. "
            "If they ask in Hindi, reply in Hindi. Match their casual or formal tone.\n"
            "2. Contextual Awareness: Maintain conversation continuity across turns. When the user asks follow-up questions referencing 'it', 'here', 'that example', or 'again in simple words', resolve the reference from the conversation history naturally.\n"
            "3. Dynamic Depth: Keep short/simple answers concise and direct. Provide comprehensive step-by-step breakdowns only when asked or when explaining a complex topic.\n"
            "4. Natural Formatting (No Rigid Templates): NEVER force repetitive headers, boilerplate disclaimer tags, or arbitrary tables into every reply. "
            "Do NOT output tags like '[General Knowledge: ...]' or robotic warnings. Simply answer the question naturally.\n"
            "5. Rich Content Presentation: Use Markdown effectively:\n"
            "   - Use clean headings (###) when structuring multi-part explanations.\n"
            "   - Use bullet points only when listing items or steps.\n"
            "   - Format code inside fenced code blocks with language identifiers (e.g. ```c ... ```) and helpful inline comments.\n"
            "   - Format mathematical equations and complexity notations in standard LaTeX (e.g. $O(1)$, $O(n)$, $x^2$).\n"
            "   - Use Markdown tables when comparing two or more concepts.\n"
            "6. Pedagogical Quality: Use intuitive real-world analogies, concise code examples, or step-by-step walkthroughs whenever they make abstract concepts easy to grasp.\n"
            "7. Directness: Never start by repeating the student's question. Never output unsolicited study plans or revision schedules for conceptual queries."
        )

        resp = self.generate_response(prompt=clean_msg, system_instruction=system_instruction, chat_history=chat_history)

        # Detect any page references cited in response
        page_refs = re.findall(r'Page[s]?\s*([0-9]+(?:,\s*[0-9]+)*)', resp.get('response', ''), re.IGNORECASE)
        source_pages_cited = ", ".join(page_refs) if page_refs else None

        return {
            "success": resp.get('success', False),
            "reply": resp.get('response') or resp.get('error_message'),
            "provider": resp.get('provider'),
            "model": resp.get('model'),
            "fallback_used": resp.get('fallback_used', False),
            "source_pages": source_pages_cited
        }

    def generate_academic_content(
        self,
        content_type: str,
        topic_name: str,
        unit_name: str = "Unit 1",
        subject_name: str = "Computer Science",
        subtopics: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Module 6: AI Notes and Quiz Generation.
        Generates study notes, multiple-choice quizzes, short questions,
        long questions, or revision summaries for an approved topic.
        """
        valid_types = {'notes', 'short_notes', 'explain', 'concept', 'practice', 'summary', 'mcq', 'short_questions', 'long_questions'}
        if content_type not in valid_types:
            raise InvalidInputException(f"Unsupported content type '{content_type}'. Must be one of {valid_types}")

        clean_topic = (topic_name or '').strip()
        if not clean_topic:
            raise InvalidInputException("Topic name cannot be empty.")

        subtopics_str = ", ".join(subtopics) if subtopics else "Key fundamental principles"

        if content_type == 'mcq':
            system_instruction = (
                "You are an academic university examination creator. Generate 5 high-quality Multiple Choice Questions "
                "for the given topic. You MUST return strictly valid JSON formatted as a list of 5 objects with keys: "
                "'question' (string), 'options' (array of 4 strings starting with 'A)', 'B)', 'C)', 'D)'), "
                "'correct_answer' (integer 0 to 3), and 'explanation' (string explaining why the answer is correct)."
            )
            prompt = (
                f"Generate 5 MCQs for Subject: '{subject_name}', {unit_name}, Topic: '{clean_topic}'.\n"
                f"Subtopics covered: {subtopics_str}.\n"
                f"Return ONLY valid JSON matching this schema:\n"
                f'[\n'
                f'  {{\n'
                f'    "question": "Sample Question Text?",\n'
                f'    "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],\n'
                f'    "correct_answer": 1,\n'
                f'    "explanation": "Detailed explanation of correct answer."\n'
                f'  }}\n'
                f']'
            )
            resp = self.generate_response(prompt=prompt, system_instruction=system_instruction)

            # Parse JSON
            mcqs = []
            if resp.get('success') and resp.get('response'):
                try:
                    clean_json = self._clean_json_str(resp['response'])
                    parsed = json.loads(clean_json)
                    if isinstance(parsed, list) and len(parsed) >= 1:
                        mcqs = parsed
                except Exception as parse_err:
                    logger.warning(f"MCQ JSON parse warning ({parse_err}). Falling back to structured generator.")

            # Deterministic fallback quiz if AI didn't return valid JSON
            if not mcqs:
                mcqs = [
                    {
                        "question": f"Which of the following is a primary characteristic of {clean_topic}?",
                        "options": [
                            f"A) It establishes foundational principles for {unit_name}",
                            "B) It operates strictly in exponential time complexity",
                            "C) It cannot be implemented in modern software systems",
                            "D) It is only used for hardware testing"
                        ],
                        "correct_answer": 0,
                        "explanation": f"{clean_topic} is a core curriculum component of {unit_name} in {subject_name}."
                    },
                    {
                        "question": f"When analyzing {clean_topic}, which factor is most critical?",
                        "options": [
                            "A) Operating temperature",
                            f"B) Correctness and algorithmic efficiency related to {subtopics_str.split(',')[0]}",
                            "C) Number of physical monitor displays",
                            "D) Cable length"
                        ],
                        "correct_answer": 1,
                        "explanation": f"Algorithmic correctness and efficiency are paramount when evaluating {clean_topic}."
                    },
                    {
                        "question": f"In university exam evaluations, questions on {clean_topic} predominantly test:",
                        "options": [
                            "A) Historical year of invention",
                            "B) Random memory addresses",
                            "C) Conceptual understanding, application, and edge cases",
                            "D) Keyboard layout standards"
                        ],
                        "correct_answer": 2,
                        "explanation": f"Academic questions on {clean_topic} evaluate conceptual clarity and problem-solving."
                    }
                ]

            return {
                "success": True,
                "content_type": "mcq",
                "topic": clean_topic,
                "unit": unit_name,
                "subject": subject_name,
                "questions": mcqs,
                "provider": resp.get('provider') or "EduMate Question Generator",
                "model": resp.get('model'),
                "fallback_used": resp.get('fallback_used', False)
            }

        else:
            # Text generation for notes, short_notes, explain, concept, practice, summary, short questions, long questions
            type_instructions = {
                'notes': (
                    f"Create comprehensive, well-structured academic study notes for '{clean_topic}' ({unit_name}, {subject_name}).\n"
                    f"Include: 1. Overview & Definition, 2. Key Architecture/Concepts, 3. Important Formulas/Theorems, "
                    f"4. Real-world Examples, and 5. College Viva Important Points."
                ),
                'short_notes': (
                    f"Create concise, high-yield bulleted revision notes for '{clean_topic}' ({unit_name}, {subject_name}).\n"
                    f"Focus on key definitions, core concepts, critical formulas, and fast memory recall points."
                ),
                'explain': (
                    f"Explain the topic '{clean_topic}' ({unit_name}, {subject_name}) in simple, crystal-clear, beginner-friendly language.\n"
                    f"Use intuitive real-world analogies, straightforward step-by-step breakdowns, and avoid overly dry academic jargon where simple words suffice."
                ),
                'concept': (
                    f"Explain difficult and complex theoretical concepts within '{clean_topic}' ({unit_name}, {subject_name}).\n"
                    f"Provide clear, relatable real-world examples, practical scenarios, potential pitfalls/common mistakes, and edge cases."
                ),
                'practice': (
                    f"Generate university exam practice problems and conceptual questions for '{clean_topic}' ({unit_name}, {subject_name}).\n"
                    f"Provide step-by-step model solutions and explanations for each problem."
                ),
                'summary': (
                    f"Create a high-yield, quick revision summary sheet for '{clean_topic}' ({unit_name}).\n"
                    f"Use bullet points, bold key terms, formula summaries, and quick exam review tips."
                ),
                'short_questions': (
                    f"Generate 5 university examination short-answer questions (with model answers of 2-3 sentences each) "
                    f"for the topic '{clean_topic}' ({unit_name}, {subject_name})."
                ),
                'long_questions': (
                    f"Generate 2 university examination comprehensive/analytical questions (with structured outline answers) "
                    f"for the topic '{clean_topic}' ({unit_name}, {subject_name})."
                )
            }

            instruction = type_instructions.get(content_type, type_instructions['notes'])
            system_instruction = (
                "You are an experienced college professor and textbook author. "
                "Provide authoritative, clear, well-formatted academic study material with markdown headings and bullet points."
            )

            resp = self.generate_response(prompt=instruction, system_instruction=system_instruction)
            return {
                "success": resp.get('success', False),
                "content_type": content_type,
                "topic": clean_topic,
                "unit": unit_name,
                "subject": subject_name,
                "content": resp.get('response') or resp.get('error_message'),
                "provider": resp.get('provider'),
                "model": resp.get('model'),
                "fallback_used": resp.get('fallback_used', False)
            }


# Global Singleton Instance
ai_service = HybridAIService()
