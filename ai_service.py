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
        ollama_base_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
        gemini_timeout_sec: float = 12.0,
        ollama_timeout_sec: float = 20.0,
        max_gemini_retries: int = 1
    ):
        self.gemini_api_key = gemini_api_key or os.getenv('GEMINI_API_KEY', '').strip()
        self.gemini_model = gemini_model or os.getenv('GEMINI_MODEL', 'gemini-3.8-flash').strip()
        self.ollama_base_url = (ollama_base_url or os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')
        self.ollama_model = ollama_model or os.getenv('OLLAMA_MODEL', 'gemma3:1b').strip()
        self.gemini_timeout_sec = gemini_timeout_sec
        self.ollama_timeout_sec = ollama_timeout_sec
        self.max_gemini_retries = max_gemini_retries

    # --------------------------------------------------------------------------
    # 1. Provider Health & Diagnostics (Safe for Admin and Status Display)
    # --------------------------------------------------------------------------
    def get_provider_status(self) -> Dict[str, Any]:
        """
        Check connectivity and configuration of both providers.
        Never exposes the actual API key.
        """
        has_gemini_key = bool(self.gemini_api_key and len(self.gemini_api_key) > 8)

        # Check Ollama connectivity
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

        overall_available = has_gemini_key or (ollama_reachable and ollama_model_ready)

        return {
            'overall_available': overall_available,
            'primary': {
                'provider': 'gemini',
                'model': self.gemini_model,
                'configured': has_gemini_key,
                'key_masked': f"{self.gemini_api_key[:6]}...{self.gemini_api_key[-4:]}" if has_gemini_key else 'Not configured',
                'status': 'Configured (Primary)' if has_gemini_key else 'Missing API Key'
            },
            'fallback': {
                'provider': 'ollama',
                'model': self.ollama_model,
                'base_url': self.ollama_base_url,
                'reachable': ollama_reachable,
                'model_ready': ollama_model_ready,
                'available_models': ollama_installed_models,
                'status': 'Ready (Fallback)' if (ollama_reachable and ollama_model_ready) else (
                    'Server unreachable' if not ollama_reachable else f"Model '{self.ollama_model}' not found"
                )
            }
        }

    # --------------------------------------------------------------------------
    # 2. Primary Provider: Google Gemini
    # --------------------------------------------------------------------------
    def _call_gemini(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """
        Executes text generation using the official Google Gen AI SDK (google.genai)
        or direct REST API fallback if the SDK is not installed in the environment.
        Includes bounded retries for transient connection errors.
        """
        if not self.gemini_api_key:
            raise AIServiceException("Gemini API key is not configured in .env")

        # Check whether google.genai is importable
        has_sdk = False
        try:
            import google.genai
            from google.genai import errors, types
            has_sdk = True
        except ImportError:
            has_sdk = False

        if has_sdk:
            # Instantiate Client with specified API key and timeout in milliseconds
            client = google.genai.Client(
                api_key=self.gemini_api_key,
                http_options={'timeout': int(self.gemini_timeout_sec * 1000)}
            )

            config = None
            if system_instruction:
                config = types.GenerateContentConfig(system_instruction=system_instruction)

            last_error = None
            for attempt in range(1 + self.max_gemini_retries):
                try:
                    response = client.models.generate_content(
                        model=self.gemini_model,
                        contents=prompt,
                        config=config
                    )
                    if response and hasattr(response, 'text') and response.text:
                        return response.text.strip()
                    raise AIServiceException("Gemini returned an empty response.")
                except errors.ClientError as e:
                    logger.warning(f"Gemini ClientError on attempt {attempt + 1}: {e}")
                    raise AIServiceException(f"Gemini provider error (code {getattr(e, 'code', '4xx')}): {getattr(e, 'message', str(e))}")
                except errors.ServerError as e:
                    logger.warning(f"Gemini ServerError on attempt {attempt + 1}: {e}")
                    last_error = e
                    if attempt < self.max_gemini_retries:
                        time.sleep(1.0)
                        continue
                    raise AIServiceException(f"Gemini server error (code {getattr(e, 'code', '5xx')}): {str(e)}")
                except Exception as e:
                    logger.warning(f"Gemini connection error on attempt {attempt + 1}: {e}")
                    last_error = e
                    if attempt < self.max_gemini_retries:
                        time.sleep(1.0)
                        continue
                    raise AIServiceException(f"Gemini request failed: {str(e)}")
            raise AIServiceException(f"Gemini failed after retries: {str(last_error)}")

        # Direct REST API call if google.genai SDK is not installed
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        last_error = None
        for attempt in range(1 + self.max_gemini_retries):
            try:
                resp = requests.post(
                    endpoint,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=self.gemini_timeout_sec
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
                        err_data = resp.json()
                        err_msg = err_data.get('error', {}).get('message', resp.text)
                    except Exception:
                        pass
                    raise AIServiceException(f"Gemini provider error ({resp.status_code}): {err_msg}")
                elif resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_gemini_retries:
                        time.sleep(1.0)
                        continue
                    raise AIServiceException(f"Gemini server error ({resp.status_code}): {resp.text}")
                else:
                    raise AIServiceException(f"Gemini unexpected status ({resp.status_code}): {resp.text}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Gemini REST connection error on attempt {attempt + 1}: {e}")
                last_error = e
                if attempt < self.max_gemini_retries:
                    time.sleep(1.0)
                    continue
                raise AIServiceException(f"Gemini request failed: {str(e)}")

        raise AIServiceException(f"Gemini REST failed after retries: {str(last_error)}")

    # --------------------------------------------------------------------------
    # 3. Fallback Provider: Local Ollama (gemma3:1b)
    # --------------------------------------------------------------------------
    def _call_ollama(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """
        Executes text generation using local Ollama REST API.
        """
        url = f"{self.ollama_base_url}/api/generate"
        payload = {
            'model': self.ollama_model,
            'prompt': prompt,
            'stream': False
        }
        if system_instruction:
            payload['system'] = system_instruction

        try:
            resp = requests.post(url, json=payload, timeout=self.ollama_timeout_sec)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get('response', '').strip()
                if text:
                    return text
                raise AIServiceException("Ollama returned an empty response.")
            raise AIServiceException(f"Ollama returned HTTP status {resp.status_code}: {resp.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Ollama connection error: {e}")
            raise AIServiceException(f"Ollama server unavailable at {self.ollama_base_url}: {str(e)}")

    # --------------------------------------------------------------------------
    # 4. Hybrid Dispatcher with Disciplined Automatic Fallback
    # --------------------------------------------------------------------------
    def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for text generation.
        1. Validates user prompt (rejects empty/whitespace without touching AI).
        2. Attempts Google Gemini primary.
        3. If Gemini encounters a provider/availability/quota error, falls back to Ollama.
        4. Returns actual provider used, response text, and fallback flag.
        5. If both fail, raises clear exception or returns honest failure structure.
        """
        clean_prompt = (prompt or '').strip()
        if not clean_prompt:
            raise InvalidInputException("Prompt cannot be empty or whitespace only.")

        gemini_error = None
        ollama_error = None

        # Attempt 1: Gemini Primary
        try:
            output = self._call_gemini(clean_prompt, system_instruction=system_instruction)
            return {
                'success': True,
                'provider': 'gemini',
                'model': self.gemini_model,
                'fallback_used': False,
                'response': output
            }
        except Exception as e:
            gemini_error = str(e)
            logger.info(f"Gemini primary unavailable ({gemini_error}). Attempting Ollama fallback...")

        # Attempt 2: Ollama Fallback
        try:
            output = self._call_ollama(clean_prompt, system_instruction=system_instruction)
            return {
                'success': True,
                'provider': 'ollama',
                'model': self.ollama_model,
                'fallback_used': True,
                'gemini_error': gemini_error,
                'response': output
            }
        except Exception as e:
            ollama_error = str(e)
            logger.error(f"Ollama fallback also failed ({ollama_error}).")

        # Both providers failed — return honest failure without fake output
        return {
            'success': False,
            'provider': None,
            'model': None,
            'fallback_used': True,
            'gemini_error': gemini_error,
            'ollama_error': ollama_error,
            'error_message': (
                f"Both AI providers are currently unavailable. "
                f"Primary (Gemini): {gemini_error} | Fallback (Ollama): {ollama_error}"
            )
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
            else:
                u_name = "Unit 1"
                t_title = str(item).strip()
                is_comp = t_title.lower().strip() in completed_set

            flat_topics.append({
                "unit_name": u_name,
                "topic_title": t_title,
                "is_completed": is_comp
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
                "is_completed": t["is_completed"]
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
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Module 5: EduMate AI Assistant.
        Answers student queries with grounding in their approved syllabus.
        Cites source pages when applicable, clearly identifies general knowledge,
        and displays provider provenance.
        """
        clean_msg = (user_message or '').strip()
        if not clean_msg:
            raise InvalidInputException("Please enter a valid study query.")

        # Build concise syllabus reference text
        syllabus_lines = []
        for sub in approved_syllabus_context:
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

        system_instruction = (
            "You are EduMate AI Study Assistant for college students. "
            "Your role is to explain concepts clearly, provide study guidance, and assist with academic queries.\n"
            "STUDENT'S ENROLLED SYLLABUS CONTEXT:\n"
            f"{syllabus_summary or 'No approved syllabus uploaded yet.'}\n\n"
            "INSTRUCTIONS:\n"
            "1. If the student's question relates to a topic in their syllabus, explain it clearly with examples "
            "and cite the relevant syllabus unit/source pages (e.g. '[Syllabus Ref: Unit 1, Page 2]').\n"
            "2. If the student asks about a concept NOT in their syllabus, answer helpfully with general academic knowledge, "
            "and state explicitly: '[General Knowledge: Topic is outside your uploaded syllabus]'.\n"
            "3. Never invent fake page references.\n"
            "4. Be concise, pedagogical, encouraging, and format formulas using clear text/markdown."
        )

        resp = self.generate_response(prompt=clean_msg, system_instruction=system_instruction)

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
