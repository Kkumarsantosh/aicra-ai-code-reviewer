import os
import json
import time
import hashlib
import re
from typing import List, Dict, Any, Set

from config import Config
from engine import db
from engine.ai_provider import AIProvider
from engine.git_manager import GitManager

_JSON_TEMP = Config.AI_TEMPERATURE_JSON   # all FDS calls produce structured JSON

class FDSAnalyzer:
    """
    Optimized FDS Gap Analyzer that:
    1. Uses PageIndex (Hierarchical Structural Indexing) to avoid context loss.
    2. Builds a targeted code index LOCALLY.
    3. Verifies requirements in BATCHES.
    """
    
    SCORING_CONFIG = {
        "VERIFIED": 100,
        "PARTIAL": 50,
        "NOT_IMPLEMENTED": 0,
        "CONFLICTING": 0,
        "NOT_VERIFIED": 0
    }

    def __init__(self):
        self.git = GitManager()
        self.ai = AIProvider()

    def _log_progress(self, analysis_id: int, step: str, message: str):
        """Log analysis progress to database and console."""
        print(f"      [FDS] [{step}] {message}")
        if analysis_id:
            db.insert(
                "INSERT INTO fds_logs (analysis_id, step, message, created_at) VALUES (%s, %s, %s, NOW(3))",
                (analysis_id, step, message)
            )

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC INTERFACE
    # ─────────────────────────────────────────────────────────────────────────

    def parse_fds_document(self, fds_id: int, content: str, analysis_id: int = None) -> int:
        """
        Layer 1: Hierarchical PageIndex Ingestion.
        Instead of chunking (chinking), we map the document structure first.
        """
        if analysis_id:
            self._log_progress(analysis_id, "STRUCTURE", "Mapping document hierarchical structure (PageIndex)...")
        else:
            print(f"      [FDS] Mapping structure for FDS {fds_id}...")

        # Step 1: Build the structural index (The "Map")
        sections = self._map_document_structure(fds_id, content, analysis_id=analysis_id)
        if not sections:
            # Fallback to simple extraction if mapping fails
            if analysis_id: self._log_progress(analysis_id, "FALLBACK", "Mapping failed. Falling back to linear extraction.")
            requirements = self._extract_requirements_single_call(content)
            return self._store_extracted_requirements(fds_id, requirements)

        # Step 2: Extract requirements per section (The "Zoom")
        if analysis_id:
            self._log_progress(analysis_id, "EXTRACTION", f"Extracting requirements from {len(sections)} sections...")
        
        all_requirements = self._extract_requirements_from_sections(fds_id, content, sections, analysis_id=analysis_id)
        
        return len(all_requirements)

    def _map_document_structure(self, fds_id: int, content: str, analysis_id: int = None) -> List[Dict]:
        """Phase 1: Build the semantic map of the document (PageIndex)."""
        # Limit content for mapping to first 50k chars to get the gist/TOC
        mapping_context = content[:50000]
        
        prompt = f"""You are a Senior Technical Business Analyst with 15 years of experience reading Functional Design Specifications (FDS), Software Requirement Specifications (SRS), and technical design documents across banking, fintech, and enterprise software.

You understand document structure regardless of format: numbered sections, tables of contents, unnumbered prose sections, page headers, and flat PDFs with no explicit structure markers.

DOCUMENT CONTENT (first 50,000 characters):
{mapping_context}

TASK:
Build a hierarchical PageIndex (structural map) of this document.
- Identify every logical section, chapter, and subsection.
- If the document has a Table of Contents, use it as your primary guide.
- If there is no TOC, infer structure from numbered headings, bold titles, or thematic breaks.
- page_start and page_end refer to the page numbers marked "--- PAGE X ---" in the text. If no page markers exist, use sequential position (1, 2, 3...).
- level: 1 = top-level chapter, 2 = subsection, 3 = sub-subsection.
- summary: 1-2 sentences capturing what kinds of requirements live in this section (not just restating the title).

RULES:
- Cover the ENTIRE document. Do not stop after the first few sections.
- Introductions, appendices, glossaries, and non-requirement sections still get index entries.
- If the document has no discernible structure, create one entry covering the whole document.

OUTPUT FORMAT (strict JSON, no prose before or after):
{{
    "index": [
        {{
            "title": "1. Introduction",
            "page_start": 1,
            "page_end": 2,
            "level": 1,
            "summary": "Project background, stakeholder context, and high-level objectives."
        }},
        {{
            "title": "2. Functional Requirements",
            "page_start": 3,
            "page_end": 8,
            "level": 1,
            "summary": "Core business logic including wallet transactions, redemption flow, and merchant callbacks."
        }},
        {{
            "title": "2.1 Wallet Transactions",
            "page_start": 3,
            "page_end": 5,
            "level": 2,
            "summary": "Credit, debit, balance inquiry, and transaction history requirements."
        }}
    ]
}}
"""
        try:
            response = self.ai.complete(prompt, use_large_model=False, temperature=_JSON_TEMP)
            data = self._parse_json_response(response, default={'index': []})
            index_data = data.get('index', [])
            
            # CRITICAL: Verify document still exists (prevents race condition with deletion)
            check = db.execute("SELECT id FROM fds_documents WHERE id = %s", (fds_id,))
            if not check:
                print(f"      [FDS] Mapping aborted: FDS {fds_id} no longer exists.")
                return []

            # Store in DB
            stored_sections = []
            for item in index_data:
                section_id = db.insert(
                    "INSERT INTO fds_structural_index (fds_id, title, summary, page_start, page_end, level) VALUES (%s, %s, %s, %s, %s, %s)",
                    (fds_id, item['title'], item['summary'], item.get('page_start'), item.get('page_end'), item.get('level', 1))
                )
                item['id'] = section_id
                stored_sections.append(item)
            
            if analysis_id:
                self._log_progress(analysis_id, "STRUCTURE", f"Successfully mapped {len(stored_sections)} document sections.")
            
            return stored_sections
        except Exception as e:
            if analysis_id: self._log_progress(analysis_id, "STRUCTURE_ERROR", f"Structure mapping failed: {str(e)[:100]}")
            print(f"      [FDS] Structure mapping failed: {e}")
            return []

    def _extract_requirements_from_sections(self, fds_id: int, content: str, sections: List[Dict], analysis_id: int = None) -> List[Dict]:
        """Phase 2: Extract requirements using the structural map for context."""
        all_reqs = []
        
        # Split content by pages for easy lookup
        # (Assuming the convention "--- PAGE X ---" exists in the text as seen in fds/8)
        pages = re.split(r'--- PAGE \d+ ---', content)
        total_sections = len(sections)
        
        for idx, section in enumerate(sections):
            if analysis_id:
                self._log_progress(analysis_id, "EXTRACTION", f"Processing section {idx+1}/{total_sections}: {section['title']}...")
            
            start = section.get('page_start', 1)
            end = section.get('page_end', start)
            
            # Extract relevant page text
            section_text = ""
            try:
                for p_num in range(start, end + 1):
                    if p_num < len(pages):
                        section_text += f"\n--- PAGE {p_num} ---\n{pages[p_num]}"
            except: pass

            if not section_text.strip(): continue

            prompt = f"""You are a Senior Business Analyst and QA Architect with deep expertise in IEEE 830, enterprise FDS documents, and translating business intent into verifiable software requirements.

You are extracting requirements from a specific section of a Functional Design Specification.

DOCUMENT SECTION: {section['title']}
SECTION PURPOSE: {section['summary']}

SECTION CONTENT:
{section_text}

TASK:
Extract every requirement in this section — explicit and implicit.

EXTRACTION RULES:
1. EXPLICIT REQUIREMENTS: Any statement using "shall", "must", "will", "should", or a numbered requirement ID.
2. IMPLICIT REQUIREMENTS: Any feature description that implies a standard engineering expectation. Examples:
   - A "login" feature implicitly requires: brute-force protection, session timeout, secure password storage (bcrypt/argon2), audit logging.
   - A "payment" feature implicitly requires: idempotency, transaction rollback on failure, PCI compliance considerations.
   - Any "API callback" implicitly requires: retry handling, signature verification, idempotency key.
3. MODAL STRENGTH: Treat "shall"/"must" as MANDATORY, "should" as RECOMMENDED, "may" as OPTIONAL. Include all three but tag the type field accordingly.
4. DO NOT produce 1-line requirements. Every description must explain the "what", "why", and the failure scenario if not implemented.
5. ACCEPTANCE CRITERIA must be testable and specific. Not "the system works correctly" — instead "given a duplicate webhook with the same idempotency key, the system returns HTTP 200 without re-processing the transaction".

OUTPUT FORMAT (strict JSON, no prose before or after):
{{
    "requirements": [
        {{
            "id": "REQ-001",
            "title": "Concise title naming the feature and the constraint",
            "description": "Full description: what the system must do, why it exists, what failure looks like if not implemented, and any industry-standard implicit expectations that apply.",
            "type": "Mandatory",
            "acceptance_criteria": [
                "Given [precondition], when [action], then [expected outcome with specific values]",
                "Given [error condition], when [retry], then [idempotent outcome]"
            ]
        }}
    ]
}}
"""
            try:
                response = self.ai.complete(prompt, use_large_model=False, temperature=_JSON_TEMP)
                data = self._parse_json_response(response, default={'requirements': []})
                reqs = data.get('requirements', [])
                
                # Check if document still exists before bulk insertion loop
                check = db.execute("SELECT id FROM fds_documents WHERE id = %s", (fds_id,))
                if not check:
                    if analysis_id: self._log_progress(analysis_id, "EXTRACTION_ABORTED", "Document no longer exists.")
                    print(f"      [FDS] Extraction loop aborted: FDS {fds_id} no longer exists.")
                    break

                # Store with section link
                for r in reqs:
                    db.insert(
                        "INSERT INTO fds_requirements (fds_id, section_id, req_id, description, req_type, source_page) VALUES (%s, %s, %s, %s, %s, %s)",
                        (fds_id, section['id'], r.get('id', ''), r.get('description', ''), r.get('type', 'Functional'), f"Pages {start}-{end}")
                    )
                    all_reqs.append(r)
                
                if analysis_id:
                    self._log_progress(analysis_id, "EXTRACTION", f"Captured {len(reqs)} requirements from '{section['title']}'.")

            except Exception as e:
                if analysis_id: self._log_progress(analysis_id, "EXTRACTION_ERROR", f"Failed section {section['title']}: {str(e)[:100]}")
                print(f"      [FDS] Extraction failed for section {section['title']}: {e}")
                
        return all_reqs

    def _store_extracted_requirements(self, fds_id: int, requirements: List[Dict]) -> int:
        """Helper to store requirements when using fallback linear extraction."""
        insert_data = []
        for req in requirements:
            insert_data.append((
                fds_id, 
                str(req.get('id', ''))[:50], 
                req.get('description', ''), 
                str(req.get('type', 'Functional'))[:50],
                ""
            ))

        if insert_data:
            db.execute_many(
                "INSERT INTO fds_requirements (fds_id, req_id, description, req_type, source_page) VALUES (%s, %s, %s, %s, %s)",
                insert_data
            )
        return len(requirements)

    def analyze_gap(self, repo_id: int, branch: str, fds_id: int, analysis_id: int):
        """
        Main orchestration for gap analysis.
        """
        start_time = time.time()
        
        try:
            # 1. Update status
            db.update(
                "UPDATE fds_gap_analyses SET status = 'analyzing', version = version + 1 WHERE id = %s",
                (analysis_id,)
            )
            
            # 2. Get FDS Content and Requirements
            doc = db.execute("SELECT content FROM fds_documents WHERE id = %s", (fds_id,))
            if not doc:
                raise Exception(f"FDS document {fds_id} not found")
            fds_text = doc[0]['content']
            
            reqs = db.execute("SELECT req_id, description, req_type FROM fds_requirements WHERE fds_id = %s", (fds_id,))
            if not reqs:
                self._log_progress(analysis_id, "EXTRACTION", "No requirements found. Extracting...")
                count = self.parse_fds_document(fds_id, fds_text, analysis_id=analysis_id)
                if count == 0:
                    raise Exception("Failed to extract requirements")
                reqs = db.execute("SELECT req_id, description, req_type FROM fds_requirements WHERE fds_id = %s", (fds_id,))

            # 3. Setup Repo
            self._log_progress(analysis_id, "CLONING", f"Syncing branch: {branch}...")
            work_dir = os.path.join(Config.WORKSPACE_DIR, f"fds_gap_{fds_id}_{analysis_id}")
            if not os.path.exists(work_dir):
                self.git.clone_repo(repo_id, branch, work_dir)
            
            # 4. Build Code Index (Local)
            self._log_progress(analysis_id, "INDEXING", "Building code search index...")
            code_index = self._build_code_index(work_dir)
            self._log_progress(analysis_id, "INDEXED", f"Indexed {len(code_index)} source files")
            
            # 5. Map Requirements to Files (Local)
            self._log_progress(analysis_id, "MAPPING", "Mapping requirements to code files...")
            requirement_mapping = self._map_requirements_to_files(reqs, code_index)
            
            # 6. Verify Requirements (Batched API)
            self._log_progress(analysis_id, "VERIFYING", f"Verifying {len(reqs)} requirements in batches...")
            results = self._verify_requirements_batched(analysis_id, reqs, requirement_mapping, code_index)
            
            # 7. Store Results
            self._log_progress(analysis_id, "STORING", "Saving results...")
            self._store_results(analysis_id, results)
            
            elapsed = int(time.time() - start_time)
            self._log_progress(analysis_id, "COMPLETE", f"Analysis complete in {elapsed}s")
            
            return True
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self._log_progress(analysis_id, "FAILED", f"Error: {str(e)}")
            db.update(
                "UPDATE fds_gap_analyses SET status = 'failed', analysis_data = %s WHERE id = %s",
                (f"{str(e)}\n{error_details}", analysis_id)
            )
            return False

    def _extract_requirements_single_call(self, fds_text: str) -> List[Dict]:
        """Extract ALL requirements from FDS in ONE API call with caching."""
        cache_key = hashlib.sha256(fds_text.encode()).hexdigest()[:32]
        
        # Check cache
        cached = db.execute("SELECT requirements_json FROM fds_extraction_cache WHERE cache_key = %s", (cache_key,))
        if cached:
            print("      [FDS] Using cached requirement extraction")
            return json.loads(cached[0]['requirements_json'])
            
        prompt = f"""You are a Senior Business Analyst and QA Architect with deep expertise in IEEE 830, enterprise FDS documents, and translating business intent into verifiable software requirements.

FDS DOCUMENT:
{fds_text[:100000]}

TASK:
Extract EVERY requirement from this document — explicit and implicit.

EXTRACTION RULES:
1. EXPLICIT: Any statement with "shall", "must", "will", "should", a numbered ID (e.g. FR-01), or a clear imperative ("The system displays...").
2. IMPLICIT: Any feature that carries standard engineering expectations. Examples:
   - "User login" → implies: brute-force lockout, session expiry, secure password storage, audit log.
   - "Payment processing" → implies: idempotency, rollback on failure, PCI scope considerations.
   - "API callback / webhook" → implies: signature verification, retry with idempotency, dead-letter handling.
   - "Report generation" → implies: pagination, export size limits, access control.
3. MODAL STRENGTH: Tag type as "Mandatory" (shall/must), "Recommended" (should), or "Optional" (may).
4. DEPTH: Every description must answer — what must the system do, why does it exist, and what is the failure scenario if it is not implemented?
5. ACCEPTANCE CRITERIA must be testable. Not "works correctly" — instead "given a duplicate request with the same idempotency key, the system returns 200 without re-executing the transaction."
6. KEYWORDS: 3-8 lowercase terms that would appear in the source code implementing this requirement (function names, table names, route patterns, class names).
7. Preserve original IDs if present. Generate sequential IDs (FDS-REQ-01, FDS-REQ-02...) when absent.

ANTI-PATTERNS — do NOT do these:
- Do not produce 1-line descriptions.
- Do not skip implicit security, error handling, or performance requirements.
- Do not merge two distinct requirements into one entry.
- Do not include UI layout or cosmetic details as functional requirements.

OUTPUT FORMAT (strict JSON, no prose before or after):
{{
    "requirements": [
        {{
            "id": "FDS-REQ-01",
            "title": "Concise title naming the feature and the constraint",
            "description": "Full description: what the system must do, why it exists, what failure looks like if not implemented, and any industry-standard implicit expectations that apply.",
            "type": "Mandatory",
            "acceptance_criteria": [
                "Given [precondition], when [action], then [specific measurable outcome]",
                "Given [failure condition], when [retry/recovery], then [safe idempotent outcome]"
            ],
            "keywords": ["wallet", "debit", "transaction", "balance"]
        }}
    ]
}}
"""
        try:
            response = self.ai.complete(prompt, use_large_model=False, temperature=_JSON_TEMP)
            data = self._parse_json_response(response, default={'requirements': []})
            requirements = data.get('requirements', [])
            
            if requirements:
                db.execute(
                    "INSERT INTO fds_extraction_cache (cache_key, requirements_json) VALUES (%s, %s) ON DUPLICATE KEY UPDATE requirements_json = VALUES(requirements_json)",
                    (cache_key, json.dumps(requirements))
                )
            
            return requirements
        except Exception as e:
            print(f"      [FDS] Extraction failed: {e}")
            return []

    def _build_code_index(self, repo_path: str) -> Dict[str, Dict]:
        index = {}
        source_extensions = {'.py', '.go', '.java', '.js', '.ts', '.cs', '.php', '.rb', '.cpp', '.c', '.h', '.hpp'}
        skip_dirs = {'.git', 'node_modules', 'vendor', '__pycache__', '.venv', 'dist', 'build', 'target'}
        
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in source_extensions:
                    continue
                
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, repo_path)
                
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    index[rel_path] = {
                        'path': rel_path,
                        'content': content,
                        'keywords': self._extract_keywords_local(content, filename)
                    }
                except: pass
        return index

    def _extract_keywords_local(self, content: str, filename: str) -> Set[str]:
        keywords = set()
        name_parts = re.split(r'[_\-./]', filename.lower())
        keywords.update([p for p in name_parts if len(p) > 2])
        
        words = re.findall(r'\b[a-zA-Z]{4,}\b', content)
        for w in words[:200]:
            keywords.add(w.lower())
        return keywords

    def _map_requirements_to_files(self, requirements: List[Dict], code_index: Dict) -> Dict[str, List[str]]:
        mapping = {}
        for req in requirements:
            req_id = req.get('req_id') or req.get('id')
            desc = req.get('description', '').lower()
            
            req_keywords = set(re.findall(r'\b[a-zA-Z]{4,}\b', desc))
            
            file_scores = []
            for path, data in code_index.items():
                overlap = len(req_keywords & data['keywords'])
                path_lower = path.lower()
                for kw in req_keywords:
                    if kw in path_lower: overlap += 5
                
                if overlap > 0:
                    file_scores.append((path, overlap))
            
            file_scores.sort(key=lambda x: x[1], reverse=True)
            mapping[req_id] = [f[0] for f in file_scores[:8]]
        return mapping

    def calculate_implementation_coverage(self, verification: Dict) -> float:
        """
        Convert status to a 0-1 coverage score.
        """
        status = verification.get('status', 'NOT_IMPLEMENTED')
        
        if status == 'VERIFIED':
            return 1.0
        elif status == 'PARTIAL':
            evidence_count = len(verification.get('evidence', []))
            gaps_count = len(verification.get('gaps', []))
            total = evidence_count + gaps_count
            return evidence_count / total if total > 0 else 0.5
        elif status == 'NOT_IMPLEMENTED':
            return 0.0
        else:
            return 0.0

    def assess_reliability(self, status: str, confidence: float) -> str:
        """Determine actionability of the finding."""
        if confidence >= 0.9:
            certainty = "DEFINITE"
        elif confidence >= 0.7:
            certainty = "LIKELY"
        else:
            certainty = "UNCERTAIN"
        
        if status == 'VERIFIED':
            return f"{certainty}_IMPLEMENTED"
        elif status == 'PARTIAL':
            return f"{certainty}_PARTIAL"
        elif status in ['NOT_IMPLEMENTED', 'CONFLICTING']:
            return f"{certainty}_GAP"
        else:
            return "UNCERTAIN"

    def _verify_requirements_batched(self, analysis_id: int, requirements: List[Dict],
                                      mapping: Dict[str, List[str]], code_index: Dict) -> List[Dict]:
        BATCH_SIZE = 5
        all_results = []
        batches = [requirements[i:i + BATCH_SIZE] for i in range(0, len(requirements), BATCH_SIZE)]

        for idx, batch in enumerate(batches):
            self._log_progress(analysis_id, "VERIFYING", f"Batch {idx+1}/{len(batches)}...")
            context = self._build_code_context(batch, mapping, code_index)
            all_results.extend(self._run_single_batch(batch, context))
            time.sleep(1)

        return all_results

    def _build_code_context(self, batch: List[Dict], mapping: Dict, code_index: Dict) -> str:
        relevant_files: set = set()
        for req in batch:
            rid = req.get('req_id') or req.get('id')
            relevant_files.update(f for f in mapping.get(rid, []) if isinstance(f, str))

        context = ""
        tokens = 0
        for fpath in sorted(relevant_files)[:15]:
            if fpath not in code_index:
                continue
            block = f"=== FILE: {fpath} ===\n{code_index[fpath]['content'][:10000]}\n\n"
            tokens += len(block) // 4
            if tokens > 60000:
                break
            context += block
        return context

    def _run_single_batch(self, batch: List[Dict], context: str) -> List[Dict]:
        try:
            response = self.ai.complete(
                self._build_verification_prompt(batch, context),
                use_large_model=True,
                temperature=_JSON_TEMP,
            )
            data = self._parse_json_response(response, default={'verifications': []})
            verifications = data.get('verifications', [])
            verifications = self._fill_missing_results(batch, verifications)
            return self._enrich_verifications(verifications)
        except Exception as e:
            print(f"      [FDS] Batch verification failed: {e}")
            return self._not_verified_results(batch, str(e))

    def _fill_missing_results(self, batch: List[Dict], verifications: List[Dict]) -> List[Dict]:
        batch_ids = {str(r.get('req_id') or r.get('id', '')) for r in batch}
        received_ids = {str(v.get('requirement_id', '')) for v in verifications}
        for mid in batch_ids - received_ids:
            verifications.append({
                "requirement_id": mid,
                "status": "NOT_VERIFIED",
                "confidence": 0,
                "reasoning": "API did not return result for this requirement",
                "evidence": [], "gaps": [],
            })
        return verifications

    def _enrich_verifications(self, verifications: List[Dict]) -> List[Dict]:
        for v in verifications:
            v['implementation_coverage'] = self.calculate_implementation_coverage(v)
            v['reliability'] = self.assess_reliability(v['status'], v.get('confidence', 0))
        return verifications

    @staticmethod
    def _not_verified_results(batch: List[Dict], reason: str) -> List[Dict]:
        return [{
            "requirement_id": str(req.get('req_id') or req.get('id', '')),
            "status": "NOT_VERIFIED", "confidence": 0,
            "implementation_coverage": 0, "reliability": "UNCERTAIN",
            "reasoning": f"Error during verification: {reason}",
            "evidence": [], "gaps": [],
        } for req in batch]

    def _build_verification_prompt(self, batch: List[Dict], context: str) -> str:
        req_list = json.dumps(
            [{'id': r.get('req_id') or r.get('id'), 'description': r.get('description')} for r in batch],
            indent=2,
        )
        return f"""You are a Senior QA Architect and Code Auditor with 15 years of experience verifying software implementations against functional specifications. You have conducted gap analyses for banking systems, payment gateways, and regulated enterprise software.

You think like an auditor: you look for what IS in the code, what is MISSING, and what CONFLICTS with the spec. You do not guess — if the code is not visible in the context provided, you lower your confidence and say so explicitly.

REQUIREMENTS TO VERIFY:
{req_list}

CODE CONTEXT:
{context}

TASK:
For each requirement, determine its implementation status by reading the provided code.

STATUS DEFINITIONS — assign exactly one:

VERIFIED
The requirement is fully implemented. You can cite specific functions, routes, classes, or logic in the provided code that satisfy EVERY aspect of the requirement, including its implicit expectations (security, error handling, edge cases).

PARTIAL
The core logic exists but at least one critical aspect is missing or incomplete. The requirement is partially satisfied. You must list the specific gaps.

NOT_IMPLEMENTED
No code addressing this requirement exists in the provided context. The feature is absent.

CONFLICTING
Code exists but implements the requirement DIFFERENTLY from the specification. Example: spec requires JWT auth, code uses session cookies. State exactly what conflicts.

NOT_VERIFIED
The provided code context does not contain enough information to make a determination. Lower confidence and explain what you would need to see.

CALIBRATION RULES:
- Do NOT mark VERIFIED just because a function with a related name exists. Read the implementation.
- Do NOT mark NOT_IMPLEMENTED just because you cannot find an exact function name. The logic may exist under different naming.
- PARTIAL is the most common real-world status. Use it when the happy path works but error handling, edge cases, or security controls are missing.
- Confidence reflects your certainty given the code VISIBLE TO YOU. If the implementation may exist in files not shown, lower confidence to 0.6 or below.

REASONING QUALITY:
- Name the specific function, route, class, or variable that implements (or fails to implement) the requirement.
- For PARTIAL and NOT_IMPLEMENTED: describe the exact missing piece and why it matters in production.
- For CONFLICTING: quote both the spec's expectation and the code's actual behavior.
- Do NOT write "the code appears to..." — state what it does or does not do.

ANTI-PATTERNS — do NOT do these:
- Do not mark VERIFIED based on a comment or variable name alone.
- Do not mark CONFLICTING because the implementation uses a different technical approach that achieves the same outcome.
- Do not produce gaps like "could be improved" — gaps must be MISSING behaviour, not style preferences.
- Do not produce reasoning like "the code handles this correctly" without citing the specific code.

OUTPUT FORMAT (strict JSON, no prose before or after):
{{
  "verifications": [
    {{
      "requirement_id": "REQ-ID",
      "status": "VERIFIED | PARTIAL | NOT_IMPLEMENTED | CONFLICTING | NOT_VERIFIED",
      "confidence": 0.0,
      "reasoning": "Specific analysis citing exact code. Name the function/route/class. State what it does and what it is missing.",
      "evidence": [
        {{"file": "path/to/file.go", "line": 87, "snippet": "relevant code line"}}
      ],
      "gaps": [
        "Specific missing behaviour with production impact."
      ]
    }}
  ]
}}"""

    def _parse_json_response(self, response: str, default: Any) -> Any:
        try:
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(response)
        except:
            return default

    def _store_results(self, analysis_id: int, verifications: List[Dict]):
        # 1. Update individual verifications
        for v in verifications:
            status = v.get('status', 'NOT_VERIFIED')
            db.insert(
                """INSERT INTO fds_requirement_verifications 
                   (analysis_id, requirement_id, status, confidence, implementation_coverage, assessment_confidence, reliability, evidence_json, gaps_json, reasoning)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    analysis_id, 
                    v.get('requirement_id'), 
                    status,
                    v.get('confidence', 0),
                    v.get('implementation_coverage', 0),
                    v.get('confidence', 0),
                    v.get('reliability', 'UNCERTAIN'),
                    json.dumps(v.get('evidence', [])),
                    json.dumps(v.get('gaps', [])),
                    v.get('reasoning', '')
                )
            )
            
        # 2. Update summary and analysis_data (for legacy template support)
        total = len(verifications)
        verified = sum(1 for v in verifications if v.get('status') == 'VERIFIED')
        partial = sum(1 for v in verifications if v.get('status') == 'PARTIAL')
        not_impl = sum(1 for v in verifications if v.get('status') in ['NOT_IMPLEMENTED', 'CONFLICTING'])
        
        legacy_results = []
        for v in verifications:
            legacy_status = v.get('status')
            if legacy_status == 'VERIFIED': legacy_status = 'IMPLEMENTED'
            if legacy_status == 'NOT_IMPLEMENTED': legacy_status = 'MISSING'
            
            legacy_results.append({
                'req_id': v.get('requirement_id'),
                'status': legacy_status,
                'confidence': int(v.get('confidence', 0) * 100),
                'reasoning': v.get('reasoning', ''),
                'answers': {
                    'relevant_logic_found': v.get('status') in ['VERIFIED', 'PARTIAL'],
                    'logic_matches_spec': v.get('status') == 'VERIFIED'
                }
            })

        coverage = 0
        if total > 0:
            coverage = ((verified * 1.0) + (partial * 0.5)) / total * 100
            
        db.update(
            """UPDATE fds_gap_analyses 
               SET status = 'complete', 
                   total_requirements = %s,
                   verified_count = %s,
                   partial_count = %s,
                   not_implemented_count = %s,
                   coverage_percentage = %s,
                   results_json = %s,
                   analysis_data = %s,
                   completed_at = NOW()
               WHERE id = %s""",
            (
                total, verified, partial, not_impl, coverage, 
                json.dumps(verifications), 
                json.dumps({"gap_analysis": legacy_results}),
                analysis_id
            )
        )
