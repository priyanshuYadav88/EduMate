"""
EduMate Intelligent PDF Processing Service
Module 1 & Syllabus Extraction Engine:
- Secure PDF validation (extension, MIME type, file size, magic bytes)
- Multi-engine text extraction (pymupdf / pypdf fallback)
- Preservation of page numbers and structural references
- Detection of scanned / image-only pages
- Tesseract OCR fallback for scanned pages (pytesseract or tesseract CLI with mutool)
- Detection of whether PDF contains an academic syllabus vs unrelated document
- Filtering of unrelated content (cover pages, certificates, acknowledgements,
  university background, exam rules, fee details, notices, headers & footers)
- Detection of Subject Name and Course Code
- Robust Unit / Module header detection (Unit 1, UNIT I, UNIT-II, Module 1, etc.)
- Topics and subtopics extraction under correct units preserving order and wording
- Marking unassigned topics for manual student review
"""

import io
import os
import re
import shutil
import tempfile
import subprocess
import logging
from typing import Dict, Any, List, Tuple, Optional

# Attempt PyMuPDF import; gracefully fall back to pypdf if unavailable
try:
    import pymupdf
    HAVE_PYMUPDF = True
except ImportError:
    HAVE_PYMUPDF = False

import pypdf

# Attempt pytesseract + PIL
try:
    import pytesseract
    from PIL import Image
    HAVE_PYTESSERACT = True
except ImportError:
    HAVE_PYTESSERACT = False

TESSERACT_BIN = shutil.which("tesseract")
MUTOOL_BIN = shutil.which("mutool")
HAVE_OCR_CAPABILITY = HAVE_PYTESSERACT or (TESSERACT_BIN is not None and MUTOOL_BIN is not None)

logger = logging.getLogger(__name__)

# Maximum file size allowed: 15 MB
MAX_PDF_SIZE_BYTES = 15 * 1024 * 1024

# Non-syllabus document / section patterns (to ignore or classify document as non-syllabus)
NON_SYLLABUS_PATTERNS = [
    re.compile(r'\b(this is to certify that|bonafide certificate|certificate of (completion|originality|appreciation)|declaration by the (student|candidate))\b', re.I),
    re.compile(r'\b(acknowledgement[s]?|i express my (sincere )?gratitude|i would like to thank|deep sense of gratitude)\b', re.I),
    re.compile(r'\b(vision and mission of the (institute|university|department)|chancellor\'?s message|vice-chancellor\'?s message|director\'?s message|principal\'?s message|board of governors|anti-ragging committee)\b', re.I),
    re.compile(r'\b(fee structure|tuition fee|admission fee|examination fee|hostel charges|payment receipt|challan|late fee fine|refund policy)\b', re.I),
    re.compile(r'\b(rules of examination|passing marks|minimum attendance required|attendance criteria|evaluation scheme|distribution of marks|maximum marks\s*:\s*\d+|duration of examination\s*:\s*\d+|question paper pattern|instructions for paper setter|examination blueprint|minimum pass criteria|calculators?|strictly prohibited|suggested text books|text books & references|reference books?)\b', re.I),
    re.compile(r'\b(office order|circular no|tender notice|invitation for bids|recruitment notification|dated\s*:\s*\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\b', re.I),
]

PAGE_HEADER_FOOTER_PATTERN = re.compile(
    r'^(page\s*\d+(\s*of\s*\d+)?|\d+\s*of\s*\d+|-\s*\d+\s*-|\[\s*\d+\s*\]|www\.[a-z0-9\-]+\.[a-z]+|http[s]?://|academic year\s*:\s*20\d\d[-–]\d\d|aktu syllabus\s*20\d\d.*)$',
    re.I
)

TABLE_HEADER_PATTERN = re.compile(
    r'\b(?:unit|module)\s*(?:/|no\.?|number)?\b.*?\b(?:topic|content|lecture|hours)\b'
    r'|\b(?:topic|content)\b.*?\b(?:lecture|hours|unit)\b|\bunit\s*/\s*module\b|\btopics\s*&?\s*subtopics\b',
    re.I
)

HOURS_PATTERN = re.compile(
    r'^(\[\s*\d+\s*(?:hours?|hrs?)?\s*\]?|\d+\s*(?:hours?|hrs?)\]?|hours?\]?|\[\s*\d+\s*|\bhours\b|^0\d$|^\d{1,2}\s*(?:hrs?|hours?|lectures?|l)?$)',
    re.I
)

UNIT_HEADER_PATTERN = re.compile(
    r'^\s*(?:unit|module|chapter|part|section)[\s\-_.:]*([0-9ivx]+|[a-e])\b[\s:\-–—\.]*(.*)$',
    re.IGNORECASE
)

STANDALONE_ROMAN_NUMERAL_PATTERN = re.compile(r'^[IVX]{1,4}$', re.I)

COURSE_CODE_PATTERNS = [
    re.compile(r'(?:course|subject|paper)\s*code\s*[:\-]?\s*([A-Za-z0-9\-]+)', re.I),
    re.compile(r'\b([A-Z]{2,5}[-\s]?[0-9]{3,4}[A-Z]?)\b'),
]


class PDFProcessingException(Exception):
    """Custom exception raised during PDF validation or extraction."""
    def __init__(self, message: str, status_code: str = 'Failed'):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_pdf_upload(file_storage, filename: str) -> int:
    """
    Validates file extension, MIME type, size, and PDF magic header bytes.
    Returns file length in bytes.
    """
    if not filename or not filename.lower().endswith('.pdf'):
        raise PDFProcessingException(
            "Invalid file format. Please upload a valid document with a .pdf extension.",
            status_code='Failed'
        )

    # Check file size
    file_storage.seek(0, io.SEEK_END)
    file_size = file_storage.tell()
    file_storage.seek(0)

    if file_size <= 0:
        raise PDFProcessingException(
            "The uploaded file is empty (0 bytes). Please upload a valid syllabus PDF.",
            status_code='Failed'
        )

    if file_size > MAX_PDF_SIZE_BYTES:
        raise PDFProcessingException(
            f"File size exceeds the 15 MB limit ({round(file_size / (1024 * 1024), 2)} MB). Please upload a smaller PDF.",
            status_code='Failed'
        )

    # Validate PDF magic bytes (%PDF-)
    magic_header = file_storage.read(5)
    file_storage.seek(0)
    if not magic_header.startswith(b'%PDF-'):
        raise PDFProcessingException(
            "File header verification failed. The file is not a valid PDF document.",
            status_code='Failed'
        )

    return file_size


def _run_ocr_on_page(page_obj, page_num: int, file_bytes: bytes) -> Optional[str]:
    """
    Executes OCR on a scanned page if OCR capability is present.
    Supports pymupdf + pytesseract, or mutool draw + tesseract CLI fallback.
    """
    if not HAVE_OCR_CAPABILITY:
        return None

    # Method A: pymupdf + pytesseract
    if HAVE_PYMUPDF and HAVE_PYTESSERACT and page_obj is not None:
        try:
            pix = page_obj.get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text = (pytesseract.image_to_string(img) or "").strip()
            if text:
                return text
        except Exception as e:
            logger.warning(f"pymupdf/pytesseract OCR error on page {page_num}: {e}")

    # Method B: mutool draw + tesseract CLI fallback
    if MUTOOL_BIN and TESSERACT_BIN:
        tmp_pdf = None
        tmp_png = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
                f.write(file_bytes)
                tmp_pdf = f.name
            tmp_png = f"{tmp_pdf}_p{page_num}.png"
            draw_cmd = [MUTOOL_BIN, 'draw', '-o', tmp_png, '-r', '150', tmp_pdf, str(page_num)]
            subprocess.run(draw_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
            if os.path.exists(tmp_png):
                ocr_cmd = [TESSERACT_BIN, tmp_png, 'stdout', '-l', 'eng']
                proc = subprocess.run(ocr_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15)
                text = (proc.stdout or "").strip()
                if text:
                    return text
        except Exception as e:
            logger.warning(f"mutool/tesseract CLI OCR error on page {page_num}: {e}")
        finally:
            if tmp_pdf and os.path.exists(tmp_pdf):
                try: os.remove(tmp_pdf)
                except OSError: pass
            if tmp_png and os.path.exists(tmp_png):
                try: os.remove(tmp_png)
                except OSError: pass

    return None


def extract_pdf_content(file_bytes: bytes) -> Dict[str, Any]:
    """
    Extracts text page-by-page from PDF bytes.
    If a page has insufficient selectable text (< 40 chars), runs OCR if available,
    or flags that OCR is required.

    Returns a dictionary containing:
    - pages: List of {"page": int, "text": str, "is_ocr": bool, "char_count": int}
    - full_text: Combined formatted text with page markers
    - total_pages: Total number of pages
    - ocr_applied: Boolean indicating if OCR was performed
    - status: Final status ('Processing' or 'OCR Required')
    """
    pages_result: List[Dict[str, Any]] = []
    ocr_applied = False
    full_text_chunks: List[str] = []
    total_pages = 0

    if HAVE_PYMUPDF:
        try:
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        except Exception as e:
            raise PDFProcessingException(
                f"Failed to parse PDF document. The file may be corrupted: {str(e)}",
                status_code='Failed'
            )

        if doc.is_encrypted:
            raise PDFProcessingException(
                "This PDF is password-protected or encrypted. Please remove password protection before uploading.",
                status_code='Failed'
            )

        total_pages = len(doc)
        if total_pages == 0:
            raise PDFProcessingException("The uploaded PDF contains 0 pages.", status_code='Failed')

        for page_index in range(total_pages):
            page_num = page_index + 1
            page = doc[page_index]
            try:
                page_text = page.get_text("text") or ""
            except Exception as e:
                logger.warning(f"Error reading native text on page {page_num}: {e}")
                page_text = ""

            page_clean_text = page_text.strip()
            is_page_ocr = False

            if len(page_clean_text) < 40 or len(page_clean_text.split()) < 8:
                ocr_text = _run_ocr_on_page(page, page_num, file_bytes)
                if ocr_text:
                    page_clean_text = ocr_text
                    is_page_ocr = True
                    ocr_applied = True

            pages_result.append({
                "page": page_num,
                "text": page_clean_text,
                "is_ocr": is_page_ocr,
                "char_count": len(page_clean_text)
            })
            if page_clean_text:
                full_text_chunks.append(f"--- [Page {page_num}] ---\n{page_clean_text}")

        doc.close()
    else:
        # Fallback to pypdf
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        except Exception as e:
            raise PDFProcessingException(
                f"Failed to parse PDF document. The file may be corrupted: {str(e)}",
                status_code='Failed'
            )

        if reader.is_encrypted:
            raise PDFProcessingException(
                "This PDF is password-protected or encrypted. Please remove password protection before uploading.",
                status_code='Failed'
            )

        total_pages = len(reader.pages)
        if total_pages == 0:
            raise PDFProcessingException("The uploaded PDF contains 0 pages.", status_code='Failed')

        for page_index in range(total_pages):
            page_num = page_index + 1
            page = reader.pages[page_index]
            try:
                page_text = page.extract_text() or ""
            except Exception as e:
                logger.warning(f"Error extracting text on page {page_num}: {e}")
                page_text = ""

            page_clean_text = page_text.strip()
            is_page_ocr = False

            if len(page_clean_text) < 40 or len(page_clean_text.split()) < 8:
                ocr_text = _run_ocr_on_page(None, page_num, file_bytes)
                if ocr_text:
                    page_clean_text = ocr_text
                    is_page_ocr = True
                    ocr_applied = True

            pages_result.append({
                "page": page_num,
                "text": page_clean_text,
                "is_ocr": is_page_ocr,
                "char_count": len(page_clean_text)
            })
            if page_clean_text:
                full_text_chunks.append(f"--- [Page {page_num}] ---\n{page_clean_text}")

    full_extracted_text = "\n\n".join(full_text_chunks).strip()

    if not full_extracted_text or len(full_extracted_text) < 15:
        if not HAVE_OCR_CAPABILITY:
            raise PDFProcessingException(
                "This PDF appears to be a scanned image document without selectable text. "
                "OCR is required to extract its contents.",
                status_code='OCR Required'
            )
        raise PDFProcessingException(
            "No readable text or syllabus content could be extracted from this PDF, even after OCR analysis. "
            "Please ensure the PDF is clear and readable, or input topics manually.",
            status_code='Failed'
        )

    return {
        "pages": pages_result,
        "full_text": full_extracted_text,
        "total_pages": total_pages,
        "ocr_applied": ocr_applied,
        "status": "OCR Required" if (ocr_applied and not HAVE_OCR_CAPABILITY) else "Processing"
    }


def normalize_unit_number(raw_num_str: str, fallback_index: int) -> int:
    """Converts Arabic numeral, Roman numeral, or letter (A-E) to integer."""
    raw = raw_num_str.strip().lower()
    try:
        return int(raw)
    except ValueError:
        roman_map = {
            'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
            'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10
        }
        if raw in roman_map:
            return roman_map[raw]
        letter_map = {'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5}
        if raw in letter_map:
            return letter_map[raw]
        return fallback_index


def is_non_syllabus_line(line: str) -> bool:
    """Checks if a single line represents non-syllabus metadata (cover, rules, fees, headers)."""
    clean = line.strip()
    if not clean:
        return True
    if len(clean) < 2 and clean.upper() not in {'I', 'V', 'X', '1', '2', '3', '4', '5'}:
        return True

    # Page headers/footers
    if PAGE_HEADER_FOOTER_PATTERN.match(clean):
        return True

    # Table column headers and hours markers
    if TABLE_HEADER_PATTERN.search(clean) or HOURS_PATTERN.match(clean):
        return True

    # Unrelated sections
    for pat in NON_SYLLABUS_PATTERNS:
        if pat.search(clean):
            return True

    # Generic academic metadata (hours, credits, marks, lectures)
    if re.match(r'^(page\s*\d+|credits?\s*:\s*\d+|marks?\s*:\s*\d+|lectures?\s*:\s*\d+|hours?\s*:\s*\d+|tutorial\s*:\s*\d+|practical\s*:\s*\d+|semester\s*:\s*[ivx0-9]+)\b', clean, re.I):
        return True

    return False


def detect_syllabus_presence(pages_data: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Detects whether the uploaded PDF contains an academic syllabus vs unrelated document.
    Returns (is_syllabus: bool, explanation_or_error: str).
    """
    total_text = " ".join([p.get('text', '') for p in pages_data]).lower()
    if not total_text or len(total_text.strip()) < 20:
        return False, "The document does not contain readable text."

    # Check for unit / module headings and table-based unit rows
    unit_matches = 0
    in_syllabus_table = False
    for p in pages_data:
        for line in p.get('text', '').splitlines():
            clean = line.strip()
            if not clean:
                continue
            if UNIT_HEADER_PATTERN.match(clean):
                unit_matches += 1
            elif TABLE_HEADER_PATTERN.search(clean) or 'detailed syllabus' in clean.lower():
                in_syllabus_table = True
            elif in_syllabus_table and (STANDALONE_ROMAN_NUMERAL_PATTERN.match(clean) or re.match(r'^(?:unit\s*)?[1-5]$', clean, re.I)):
                unit_matches += 1

    # Check syllabus keywords
    syllabus_keywords = [
        'syllabus', 'detailed syllabus', 'course curriculum', 'course contents',
        'course content', 'course outline', 'course structure',
        'unit 1', 'unit i', 'unit-i', 'unit - 1', 'unit-1',
        'module 1', 'module i', 'module-i', 'course code',
        'subject code', 'learning objectives', 'course objectives', 'prerequisite',
        'course outcome', 'course outcomes', 'learning outcome', 'learning outcomes',
        'bloom’s knowledge level', 'blooms knowledge level', 'bloom knowledge level',
        'lecture', 'lectures'
    ]
    keyword_hits = sum(1 for kw in syllabus_keywords if kw in total_text)

    # Check non-syllabus rejection markers (certificates, notices, fee receipts)
    purely_unrelated_markers = [
        'this is to certify that', 'bonafide certificate', 'certificate of completion',
        'tender notice', 'invitation for bids', 'fee structure for academic year',
        'hostel admission form', 'payment receipt'
    ]
    unrelated_hits = sum(1 for um in purely_unrelated_markers if um in total_text)

    if unrelated_hits > 0 and unit_matches == 0 and keyword_hits < 2:
        return False, (
            "No academic syllabus detected in the uploaded PDF. The document appears to contain "
            "administrative notices, certificates, or fee details rather than course units and topics."
        )

    if unit_matches >= 1 or keyword_hits >= 2:
        return True, "Syllabus detected."

    return False, (
        "No academic syllabus detected in the uploaded PDF. Please upload an official syllabus "
        "or course curriculum document containing course units and topics."
    )


def extract_course_metadata(pages_data: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts Subject Name and Course Code from the first few pages with high precision.
    Prioritizes explicit Subject and Course Code headers and filters out university/degree names.
    Supports multi-code lines (e.g. BCC302 / BCC402) and two-line code/subject pairs.
    """
    detected_subject = None
    detected_code = None

    # Step 1: Scan for explicit Course Title, Subject Name, and Course Code
    for p in pages_data[:4]:
        lines = p.get('text', '').splitlines()
        for idx, line in enumerate(lines):
            clean = line.strip()
            if not clean:
                continue

            # Course Code detection
            if not detected_code:
                m_code = re.search(r'(?:course|subject|paper)\s*code\s*[:\-]?\s*([A-Za-z0-9\-]+)', clean, re.I)
                if m_code:
                    c = m_code.group(1).strip()
                    if 2 <= len(c) <= 12 and any(ch.isdigit() for ch in c):
                        detected_code = c
                else:
                    m_codes = re.findall(r'\b([A-Z]{2,5}[-\s]?[0-9]{3,4}[A-Z]?)\b', clean)
                    if m_codes and any(ch.isdigit() for ch in m_codes[0]):
                        detected_code = ' / '.join(m_codes[:2]) if (len(m_codes) > 1 and '/' in clean) else m_codes[0]

            # Subject Name detection
            if not detected_subject:
                # 1. Course Title: XYZ or Subject: XYZ
                sub_match = re.search(r'(?:course\s*title|subject\s*(?:name)?|paper\s*(?:title)?)\s*[:\-]\s*([^•\n\r]+)', clean, re.I)
                if sub_match:
                    cand = sub_match.group(1).strip()
                    cand = re.split(r'(?=[A-Z][a-z]+:)|[•\n\r]', cand)[0].strip(' :-–—•')
                    # Validate candidate is not a degree or university header
                    if 3 <= len(cand) <= 80 and not re.search(r'\b(b\.tech|m\.tech|semester|curriculum|scheme|evaluation|university)\b', cand, re.I):
                        detected_subject = cand
                else:
                    # 2. CODE: SUBJECT (e.g. KCS301: DATA STRUCTURES)
                    m_code_sub = re.search(r'\b[A-Z]{2,5}[-\s]?[0-9]{3,4}[A-Z]?\s*[:\-]\s*([A-Za-z\s&]{4,70})', clean)
                    if m_code_sub:
                        cand = m_code_sub.group(1).strip()
                        if not re.search(r'\b(b\.tech|m\.tech|semester|syllabus|curriculum|scheme|evaluation)\b', cand, re.I):
                            detected_subject = cand
                    # 3. CODE: on this line, and SUBJECT on the next line
                    elif clean.endswith(':') or re.search(r'\b[A-Z]{2,5}[-\s]?[0-9]{3,4}[A-Z]?\b.*:$', clean):
                        if idx + 1 < len(lines):
                            next_clean = lines[idx + 1].strip()
                            if 3 <= len(next_clean) <= 80 and not re.search(r'\b(b\.tech|m\.tech|semester|syllabus|curriculum|scheme|evaluation|course outcome|bloom|co\s*\d)\b', next_clean, re.I):
                                detected_subject = next_clean

    # Step 2: Fallback prominent title heuristic ONLY if explicit search didn't find a subject
    if not detected_subject and pages_data:
        for line in pages_data[0].get('text', '').splitlines():
            clean = line.strip()
            if re.search(r'\b(university|dr\.\s*a\.p\.j|evaluation scheme|curriculum for|study and evaluation|b\.tech|m\.tech|scheme of)\b', clean, re.I):
                continue
            if any(k in clean.lower() for k in ['syllabus for', 'course:', 'subject:']):
                cand = re.sub(r'^(syllabus\s*for|course\s*title\s*:?|subject\s*:?)\s*', '', clean, flags=re.I).strip()
                if 4 <= len(cand) <= 80 and not UNIT_HEADER_PATTERN.match(cand):
                    detected_subject = cand
                    break

    return detected_subject, detected_code


def parse_syllabus_heuristic(
    pages_data: List[Dict[str, Any]],
    subject_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Intelligent heuristic regex/rule-based syllabus parser.
    Used when AI providers are unavailable or as an immediate verification engine.
    - Accurately classifies whether the document contains an academic syllabus
    - Identifies Subject Name and Course Code
    - Detects Unit headings (UNIT 1, UNIT I, UNIT-II, Module 1, etc.)
    - Handles wrapped table column layouts and multi-line unit titles
    - Merges wrapped topic lines and extracts subtopics
    - Deduplicates units and topics across page breaks
    - Marks unassigned topics for manual student review
    - Ignores cover pages, certificates, exam rules, fee tables, notices, and page headers/footers
    """
    is_syllabus, message = detect_syllabus_presence(pages_data)
    if not is_syllabus:
        return {
            "is_syllabus": False,
            "subject": None,
            "course_code": None,
            "units": [],
            "unassigned_topics": [],
            "error": message
        }

    detected_subject, detected_code = extract_course_metadata(pages_data)
    final_subject = detected_subject or (subject_name.strip() if subject_name and subject_name.strip() else None) or "Academic Course Syllabus"

    units: List[Dict[str, Any]] = []
    current_unit: Optional[Dict[str, Any]] = None
    unassigned_topics: List[Dict[str, Any]] = []
    seen_topics = set()
    awaiting_unit_title = False
    current_active_topic = None
    in_references_section = False
    in_syllabus_table = False
    ref_start_pattern = re.compile(r'\b(suggested\s+)?(text\s*books|reference\s*books|suggested\s*readings?|references\s*:)\b', re.I)

    for p in pages_data:
        page_num = p['page']
        lines = p['text'].splitlines()

        for line in lines:
            raw_line = line.strip()
            if not raw_line:
                continue
            if len(raw_line) < 2 and raw_line.upper() not in {'I', 'V', 'X', '1', '2', '3', '4', '5'}:
                continue

            # Check if this line is a transition into reference books or bibliography
            if ref_start_pattern.search(raw_line):
                in_references_section = True
                current_active_topic = None
                continue

            if in_references_section:
                continue

            # Check table header or detailed syllabus section transition
            if TABLE_HEADER_PATTERN.search(raw_line) or 'detailed syllabus' in raw_line.lower():
                in_syllabus_table = True
                current_active_topic = None
                continue

            # Check for Unit / Module Heading or Table Row Unit Numeral
            unit_match = UNIT_HEADER_PATTERN.match(raw_line)
            is_table_unit = False
            if not unit_match and in_syllabus_table:
                if STANDALONE_ROMAN_NUMERAL_PATTERN.match(raw_line) or re.match(r'^(?:unit\s*)?[1-5]$', raw_line, re.I):
                    is_table_unit = True

            if unit_match or is_table_unit:
                in_references_section = False
                raw_num = unit_match.group(1).strip() if unit_match else raw_line
                unit_title_rest = unit_match.group(2).strip() if unit_match else ''

                norm_num = normalize_unit_number(raw_num, len(units) + 1)
                unit_title_clean = f"Unit {norm_num}"
                if unit_title_rest:
                    unit_title_clean = f"{unit_title_clean}: {unit_title_rest}".strip(" :-–—")

                # Check if this unit already exists (e.g. across page breaks)
                existing_unit = next((u for u in units if u['unit_number'] == norm_num), None)
                if existing_unit:
                    current_unit = existing_unit
                    if unit_title_rest and (': ' not in existing_unit['title'] or existing_unit['title'] == f"Unit {norm_num}"):
                        existing_unit['title'] = unit_title_clean
                else:
                    current_unit = {
                        "unit_number": norm_num,
                        "title": unit_title_clean,
                        "topics": []
                    }
                    units.append(current_unit)

                awaiting_unit_title = True if not unit_title_rest and not is_table_unit else False
                current_active_topic = None
                continue

            # Check if this line is unrelated content (rules, cover, fee, notices, headers, hours, table meta)
            if is_non_syllabus_line(raw_line):
                current_active_topic = None
                continue

            # Multi-line unit title continuation in table cells (e.g. "UNIT 1:\nIntroduction")
            if awaiting_unit_title and current_unit:
                if re.match(r'^[•\-\*\u2022\u25E6]|\b[0-9]+[\.\-\)]', raw_line):
                    awaiting_unit_title = False
                else:
                    if ':' not in current_unit['title']:
                        current_unit['title'] += f": {raw_line}"
                    else:
                        current_unit['title'] += f" {raw_line}"
                    continue

            # Clean leading bullet points, numbers, dashes
            is_bullet_item = bool(re.match(r'^[•\-\*\u2022\u25E6]|\b[0-9]+[\.\-\)]', raw_line))
            clean_topic = re.sub(r'^[0-9]+[\.\-\)]\s*|^[\*\-\•\u2022\u25E6]\s*', '', raw_line).strip()

            # Filter out lines that look like administrative instructions or course metadata
            if re.match(r'^(page\s*\d+|credits?|lecture|tutorial|practical|semester|exam|hours?|marks?)\b', clean_topic, re.I):
                continue

            # If this is a continuation of the previous topic line (wrapped sentence in PDF)
            if not is_bullet_item and current_active_topic is not None and not clean_topic.endswith(':'):
                current_active_topic['raw_text'] += f" {clean_topic}"
                continue

            if len(clean_topic) < 3 or len(clean_topic) > 180:
                continue

            current_active_topic = {
                'raw_text': clean_topic,
                'page': page_num
            }

            # If a unit is active, attach topic to current unit, otherwise to unassigned
            if current_unit:
                current_unit["topics"].append(current_active_topic)
            else:
                unassigned_topics.append(current_active_topic)

    # Process all collected topic items: extract topic name and subtopics, and deduplicate
    def format_topics_list(topic_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted = []
        for rec in topic_records:
            full_txt = rec['raw_text'].strip()
            p_num = rec['page']

            # If a topic text is long and contains multiple sentences/topics (as in table cells):
            if len(full_txt) > 85 and re.search(r'\.\s+(?=[A-Z])', full_txt):
                raw_segments = [s.strip() for s in re.split(r'\.\s+(?=[A-Z])|;\s*', full_txt) if s.strip()]
            else:
                raw_segments = [full_txt]

            for seg in raw_segments:
                subtopics = []
                topic_name = seg
                if ':' in seg and len(seg.split(':', 1)[0]) < 65:
                    parts = seg.split(':', 1)
                    topic_name = parts[0].strip()
                    subtopics = [s.strip(' .') for s in re.split(r'[,;]', parts[1]) if len(s.strip(' .')) > 2]
                elif ';' in seg:
                    parts = seg.split(';')
                    topic_name = parts[0].strip()
                    subtopics = [s.strip(' .') for s in parts[1:] if len(s.strip(' .')) > 2]

                norm_key = topic_name.lower().strip()
                if norm_key in seen_topics:
                    # Merge subtopics and pages if already exists
                    for existing in formatted:
                        if existing['name'].lower().strip() == norm_key:
                            for st in subtopics:
                                if st not in existing['subtopics']:
                                    existing['subtopics'].append(st)
                            if p_num not in existing['source_pages']:
                                existing['source_pages'].append(p_num)
                    continue
                seen_topics.add(norm_key)

                formatted.append({
                    "name": topic_name,
                    "subtopics": subtopics[:8],
                    "source_pages": [p_num]
                })
        return formatted

    # Format units topics
    for u in units:
        u['topics'] = format_topics_list(u['topics'])
        # Enhance unit title if it's generic "Unit X" and first topic is informative
        if ':' not in u['title'] and u['topics']:
            first_name = u['topics'][0]['name']
            if len(first_name) < 55:
                u['title'] = f"{u['title']}: {first_name}"

    # Format unassigned topics
    unassigned_formatted = []
    for ut in unassigned_topics:
        res = format_topics_list([ut])
        for r in res:
            r['needs_review'] = True
            unassigned_formatted.append(r)

    # Filter out empty units
    valid_units = [u for u in units if u["topics"]]

    if not valid_units and not unassigned_formatted:
        return {
            "is_syllabus": False,
            "subject": None,
            "detected_subject": None,
            "course_code": None,
            "units": [],
            "unassigned_topics": [],
            "error": "No curriculum units or topics could be confidently identified in this document."
        }

    return {
        "is_syllabus": True,
        "subject": final_subject,
        "detected_subject": detected_subject,
        "target_subject": subject_name,
        "course_code": detected_code,
        "units": valid_units,
        "unassigned_topics": unassigned_formatted
    }
