import os
import json
import time
import hashlib
import re
import subprocess
import threading
from datetime import datetime
from typing import List, Dict, Any, Set

from config import Config
from engine import db
from engine.git_manager import GitManager

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
        self.last_call_time = 0
        self.min_call_interval = 1.0  # 1 second between calls

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
        
        prompt = f"""You are a Document Architect. Analyze this FDS and build a hierarchical Structural Index (PageIndex).

FDS CONTENT SNIPPET:
{mapping_context}

TASK:
Identify the natural sections, chapters, and page ranges.
For each section, provide a brief summary of what it covers.

OUTPUT FORMAT (strict JSON):
{{
    "index": [
        {{
            "title": "1. Introduction",
            "page_start": 1,
            "page_end": 2,
            "level": 1,
            "summary": "Project background, objectives and KPIs."
        }},
        {{
            "title": "2. System Requirements",
            "page_start": 2,
            "page_end": 5,
            "level": 1,
            "summary": "Technical constraints, CMS configurations, and core logic."
        }}
    ]
}}
"""
        try:
            response = self._call_api(prompt, use_pro=False)
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

            prompt = f"""Extract requirements from this specific section of the FDS.

SECTION CONTEXT: {section['title']}
SECTION SUMMARY: {section['summary']}

SECTION CONTENT:
{section_text}

TASK:
Extract all functional and technical requirements.
DO NOT just output 1-liners. Use your deep understanding of software engineering and industry standards to make the requirements highly descriptive.
For each requirement:
1. Provide a comprehensive description that explains the "why" and "how".
2. Include implicit industry-standard expectations (e.g., security, edge cases, error handling, performance) that apply to the requirement.
3. Detail specific acceptance criteria.

Return as a JSON object with a "requirements" array.

OUTPUT FORMAT (strict JSON):
{{
    "requirements": [
        {{
            "id": "REQ-ID",
            "title": "Title",
            "description": "Comprehensive requirement text, including deep context, business logic, and industry standard implicit requirements (security, edge cases, etc.).",
            "type": "Functional/Technical",
            "acceptance_criteria": ["Criteria 1", "Criteria 2"]
        }}
    ]
}}
"""
            try:
                response = self._call_api(prompt, use_pro=False)
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
            
        prompt = f"""You are a requirements analyst. Extract ALL requirements from this FDS document.

FDS DOCUMENT:
{fds_text[:100000]}

TASK:
1. Identify every requirement (statements with "shall", "must", "should", numbered requirements, etc.)
2. DO NOT just output 1-liners. Use your deep understanding of software engineering and industry standards to make the requirements highly descriptive.
3. Provide a comprehensive description that explains the "why" and "how".
4. Include implicit industry-standard expectations (e.g., security, edge cases, error handling, performance) that apply to the requirement.
5. Extract requirement ID, title, description, type, and specific acceptance criteria.
6. Return as a JSON object with a "requirements" array.

OUTPUT FORMAT (strict JSON):
{{
    "requirements": [
        {{
            "id": "FDS-REQ-01",
            "title": "Short title",
            "description": "Comprehensive requirement text, including deep context, business logic, and industry standard implicit requirements (security, edge cases, etc.).",
            "type": "Functional",
            "acceptance_criteria": ["Criteria 1: ...", "Criteria 2: ..."],
            "keywords": ["wallet", "payment", "transaction"]
        }}
    ]
}}

RULES:
- Extract EVERY requirement, do not skip any
- Preserve original requirement IDs if present
- Keywords should help find relevant code files
- Return ONLY valid JSON
"""
        try:
            response = self._call_api(prompt, use_pro=False)
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
        total_batches = len(batches)
        
        for idx, batch in enumerate(batches):
            self._log_progress(analysis_id, "VERIFYING", f"Batch {idx+1}/{total_batches}...")
            
            relevant_files = set()
            for req in batch:
                rid = req.get('req_id') or req.get('id')
                relevant_files.update(mapping.get(rid, []))
            
            context = ""
            current_tokens = 0
            MAX_TOKENS = 60000
            
            for fpath in sorted(list(relevant_files))[:15]:
                if fpath in code_index:
                    fcontent = code_index[fpath]['content']
                    file_text = f"=== FILE: {fpath} ===\n{fcontent[:10000]}\n\n"
                    context += file_text
                    current_tokens += len(file_text) // 4
                    if current_tokens > MAX_TOKENS: break

            prompt = f"""Verify these requirements against the code context.

REQUIREMENTS:
{json.dumps([{ 'id': r.get('req_id') or r.get('id'), 'desc': r.get('description') } for r in batch], indent=2)}

CODE CONTEXT:
{context}

TASK:
Determine the implementation status for each requirement based on the provided code context.
Use your deep software engineering expertise and industry standards to provide a highly descriptive and analytical assessment.
DO NOT use brief 1-liners.
1. The reasoning must explicitly analyze how the codebase aligns (or fails to align) with the specific functional and non-functional aspects of the requirement, citing exact logic patterns, missing edge cases, or security/performance implications.
2. The gaps must be detailed and descriptive, explaining exactly what is missing and why it is critical for a robust implementation.

Return a JSON object with a "verifications" array.

OUTPUT FORMAT:
{{
  "verifications": [
    {{
      "requirement_id": "REQ-ID",
      "status": "VERIFIED | PARTIAL | NOT_IMPLEMENTED | CONFLICTING",
      "confidence": 0.0 to 1.0,
      "reasoning": "Detailed, descriptive reasoning analyzing the implementation against the requirement, including architecture, edge cases, and industry standards.",
      "evidence": [{{ "file": "path", "line": 123, "snippet": "..." }}],
      "gaps": ["Detailed description of missing logic or edge case 1", "Detailed description of missing logic 2"]
    }}
  ]
}}

METRIC DEFINITION:
- confidence (0.0 - 1.0): How CERTAIN you are that your assessment is correct based on the evidence you found (or lack thereof). 1.0 means you have exhaustively checked and are 100% sure.
"""
            try:
                response = self._call_api(prompt, use_pro=True)
                batch_data = self._parse_json_response(response, default={'verifications': []})
                verifications = batch_data.get('verifications', [])
                
                batch_ids = {r.get('req_id') or r.get('id') for r in batch}
                received_ids = {v.get('requirement_id') for v in verifications}
                missing_ids = batch_ids - received_ids
                
                for mid in missing_ids:
                    verifications.append({
                        "requirement_id": mid,
                        "status": "NOT_VERIFIED",
                        "confidence": 0,
                        "reasoning": "API did not return result for this requirement",
                        "evidence": [], "gaps": []
                    })
                
                # Enrich with derived metrics
                for v in verifications:
                    v['implementation_coverage'] = self.calculate_implementation_coverage(v)
                    v['reliability'] = self.assess_reliability(v['status'], v.get('confidence', 0))

                all_results.extend(verifications)
            except Exception as e:
                print(f"      [FDS] Batch {idx+1} failed: {e}")
                for req in batch:
                    all_results.append({
                        "requirement_id": req.get('req_id') or req.get('id'),
                        "status": "NOT_VERIFIED", "confidence": 0,
                        "implementation_coverage": 0,
                        "reliability": "UNCERTAIN",
                        "reasoning": f"Error during verification: {str(e)}",
                        "evidence": [], "gaps": []
                    })
            
            time.sleep(1)
            
        return all_results

    def _call_api(self, prompt: str, use_pro: bool = False) -> str:
        # Rate limiting
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_call_interval:
            time.sleep(self.min_call_interval - elapsed)
            
        model_tier = "pro" if use_pro else "flash"
        
        try:
            cmd = [
                Config.GEMINI_CLI_BIN,
                "--prompt", prompt,
                "--approval-mode", "plan",
                "--sandbox",
                "--model", model_tier,
                "--output-format", "text"
            ]
            
            # Use a generous 10-minute timeout for large documents
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=600)
            self.last_call_time = time.time()
            return result.stdout
        except subprocess.TimeoutExpired:
            print(f"      [FDS] API Call timed out after 600s")
            raise Exception("Gemini CLI call timed out")
        except subprocess.CalledProcessError as e:
            print(f"      [FDS] API Call failed: {e.stderr}")
            raise Exception(f"Gemini CLI call failed: {e.stderr}")

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
