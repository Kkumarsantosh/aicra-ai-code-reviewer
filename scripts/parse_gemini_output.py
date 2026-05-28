"""
Robust Gemini output parser — updated for Original Prompt Format.
Handles structured markdown and captures deep remediation fields.
"""

import json
import re
import sys
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GeminiOutputParser:
    """
    Parses Gemini's structured code review output into standardized dictionaries.
    Updated for Original Prompt markers like FAILURE_SCENARIO, LOGIC_FAILURE, etc.
    """

    def parse(self, text: str) -> dict:
        text = text.strip()
        text_to_use = self._unwrap_response(text)
        
        result = {
            "sonarValidation": self.parse_validations(text_to_use),
            "logicalFindings": self.parse_findings(text_to_use),
            "suggestions": self.parse_suggestions(text_to_use),
            "riskPredictions": self.parse_risk_predictions(text_to_use),
            "assessment": self.parse_assessment(text_to_use),
            "commitQuality": self.parse_commit_quality(text_to_use),
            "parse_errors": []
        }

        if not result["assessment"] or not result["assessment"].get("summary"):
            result["parse_errors"].append("ASSESSMENT block missing or incomplete")
        
        return result

    def _unwrap_response(self, text: str) -> str:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                if "response" in data:
                    return data["response"]
                elif "candidates" in data:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
        except: pass
        return text

    def parse_assessment(self, text: str) -> dict:
        pattern = r'ASSESSMENT_START\s*(.*?)\s*ASSESSMENT_END'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        
        assessment = {"overallRisk": "MEDIUM", "recommendation": "NEEDS_DISCUSSION", "summary": "", "positives": [], "topRisks": []}
        block = match.group(1).strip() if match else text
        
        assessment["overallRisk"] = self.extract_field(block, "RISK_LEVEL", "MEDIUM").upper()
        assessment["recommendation"] = self.extract_field(block, "RECOMMENDATION", "NEEDS_DISCUSSION").upper()
        assessment["summary"] = self.extract_field(block, "SUMMARY")
        assessment["positives"] = self.extract_multi_field(block, "POSITIVE")
        assessment["topRisks"] = self.extract_multi_field(block, "TOP_RISK")
        
        return assessment

    def parse_validations(self, text: str) -> list:
        validations = []
        blocks = re.split(r'-*VALIDATION_START-*', text, flags=re.IGNORECASE)
        
        for block in blocks[1:]:
            end_match = re.search(r'-*VALIDATION_END-*', block, re.IGNORECASE)
            block_content = block[:end_match.start()].strip() if end_match else block.strip()
            
            v = {
                'sonarRule': self.extract_field(block_content, 'SONAR_RULE'),
                'file': self.extract_field(block_content, 'FILE'),
                'line': self.extract_field(block_content, 'LINE'),
                'verdict': self.extract_field(block_content, 'VERDICT', 'CONFIRMED'),
                'severity': self.extract_field(block_content, 'SEVERITY', 'MEDIUM'),
                'confidence': self.extract_field(block_content, 'CONFIDENCE', '0.7'),
                'explanation': self.extract_field(block_content, 'FAILURE_SCENARIO') or self.extract_field(block_content, 'EXPLANATION'),
                'productionImpact': self.extract_field(block_content, 'PRODUCTION_IMPACT'),
                'currentCode': self.extract_code_block(block_content, 'CURRENT_CODE'),
                'remediationPlan': self.extract_field(block_content, 'REMEDIATION_PLAN'),
                'strategicApproach': self.extract_field(block_content, 'STRATEGIC_APPROACH'),
                'standard': self.extract_field(block_content, 'STANDARD'),
                'mermaidDiagram': self.extract_mermaid(block_content),
                'fix': self.extract_code_block(block_content, 'FIX')
            }
            if v['file'] or v['sonarRule'] or v['explanation']:
                validations.append(v)
        return validations

    def parse_findings(self, text: str) -> list:
        findings = []
        blocks = re.split(r'-*FINDING_START-*', text, flags=re.IGNORECASE)
        
        for block in blocks[1:]:
            end_match = re.search(r'-*FINDING_END-*', block, re.IGNORECASE)
            block_content = block[:end_match.start()].strip() if end_match else block.strip()
                
            f = {
                'id': self.extract_field(block_content, 'ID'),
                'title': self.extract_field(block_content, 'TITLE'),
                'category': self.extract_field(block_content, 'CATEGORY'),
                'severity': self.extract_field(block_content, 'SEVERITY', 'MEDIUM'),
                'file': self.extract_field(block_content, 'FILE'),
                'lineStart': self.extract_field(block_content, 'LINE_START'),
                'lineEnd': self.extract_field(block_content, 'LINE_END'),
                # Updated fields
                'theLogicFailure': self.extract_field(block_content, 'LOGIC_FAILURE') or self.extract_field(block_content, 'WHAT_BREAKS'),
                'productionImpact': self.extract_field(block_content, 'PRODUCTION_IMPACT'),
                'remediationPlan': self.extract_field(block_content, 'REMEDIATION_PLAN'),
                'strategicApproach': self.extract_field(block_content, 'STRATEGIC_APPROACH'),
                'standard': self.extract_field(block_content, 'STANDARD'),
                'currentCode': self.extract_code_block(block_content, 'CURRENT_CODE'),
                'thePrincipalFix': self.extract_code_block(block_content, 'FIX') or self.extract_code_block(block_content, 'FIXED_CODE'),
                'proofTest': self.extract_code_block(block_content, 'TEST'),
                'mermaidDiagram': self.extract_mermaid(block_content),
                'confidence': float(self.extract_field(block_content, 'CONFIDENCE', '0.85'))
            }
            if f['title'] or f['theLogicFailure'] or f['file']:
                findings.append(f)
        return findings

    def parse_suggestions(self, text: str) -> list:
        pattern = r'-*SUGGESTIONS_START-*\s*(.*?)\s*-*SUGGESTIONS_END-*'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match: return []
        
        suggestions = []
        for line in match.group(1).strip().split('\n'):
            line = line.strip()
            if not line: continue
            clean_line = re.sub(r'^(\d+[\.\)]|[-*•\[\] ]+)', '', line).strip()
            if clean_line: suggestions.append(clean_line)
        return suggestions

    def parse_risk_predictions(self, text: str) -> dict:
        pattern = r'-*RISK_PREDICTION_START-*\s*(.*?)\s*-*RISK_PREDICTION_END-*'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        res = {"recommendation": "", "predictions": []}
        if not match: return res
            
        block = match.group(1).strip()
        res["recommendation"] = self.extract_field(block, "RECOMMENDATION")
        pred_parts = re.split(r'PREDICTION:', block, flags=re.IGNORECASE)
        for part in pred_parts[1:]:
            p = {
                "file": self.extract_field(part, 'FILE'),
                "risk": self.extract_field(part, 'RISK', 'MEDIUM'),
                "reason": self.extract_field(part, 'REASON'),
                "probability": self.extract_field(part, 'PROBABILITY')
            }
            if p["file"]: res["predictions"].append(p)
        return res

    def parse_commit_quality(self, text: str) -> dict:
        pattern = r'COMMIT_QUALITY_START(.*?)COMMIT_QUALITY_END'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        quality = {"messageScore": 5, "messageEval": "", "standardsScore": 5, "standardsEval": "", "documentationScore": 5, "documentationEval": ""}
        if not match: return quality
        
        block = match.group(1)
        quality["messageScore"] = int(self.extract_field(block, "MESSAGE_SCORE", "5"))
        quality["messageEval"] = self.extract_field(block, "MESSAGE_EVALUATION")
        quality["standardsScore"] = int(self.extract_field(block, "STANDARDS_SCORE", "5"))
        quality["standardsEval"] = self.extract_field(block, "STANDARDS_EVALUATION")
        quality["documentationScore"] = int(self.extract_field(block, "DOCUMENTATION_SCORE", "5"))
        quality["documentationEval"] = self.extract_field(block, "DOCUMENTATION_EVALUATION")
        return quality

    def extract_field(self, block: str, field_name: str, default='') -> str:
        pattern = rf'^\s*[\*#]*{field_name}[\*#]*\s*[:\-]\s*(.*?)(?=\n\s*[\*#]*[A-Z0-9_]{{3,}}[\*#]*\s*[:\-]|\n---[A-Z]|\Z)'
        match = re.search(pattern, block, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        if match:
            val = match.group(1).strip().replace('`', "'")
            return default if val.upper().startswith('NONE') else val
        
        pattern_simple = rf'{field_name}\s*[:\-]\s*(.*)'
        match_simple = re.search(pattern_simple, block, re.IGNORECASE)
        if match_simple:
            val = match_simple.group(1).strip().replace('`', "'")
            return default if val.upper().startswith('NONE') else val
        return default

    def extract_multi_field(self, block: str, field_name: str) -> list:
        pattern = rf'^\s*[\*#]*{field_name}[\*#]*\s*[:\-]\s*(.*?)(?=\n\s*[\*#]*[A-Z0-9_]{{3,}}[\*#]*\s*[:\-]|\n---[A-Z]|\Z)'
        matches = re.findall(pattern, block, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        return [m.strip().replace('`', "'") for m in matches if m.strip().upper() != 'NONE']

    def extract_code_block(self, text: str, field_name: str) -> str:
        pattern = rf'{field_name}\s*[:\-]\s*\n?(.*?)(?=\n\s*[A-Z0-9_]{{3,}}\s*[:\-]|\n---[A-Z]|\Z)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            if len(text) < 3000:
                match_any = re.search(r'```(?:\w*)\s*\n(.*?)```', text, re.DOTALL)
                if match_any: return match_any.group(1).strip()
            return ''
        
        content = match.group(1).strip()
        content = re.sub(r'^```\w*\n?', '', content)
        content = re.sub(r'\n?```$', '', content)
        return content.strip()

    def extract_mermaid(self, text: str) -> str:
        match = re.search(r'```mermaid\s*\n(.*?)\n\s*```', text, re.DOTALL | re.IGNORECASE)
        if match: return match.group(1).strip()
        
        mermaid_field = self.extract_field(text, 'MERMAID_SEQUENCE_DIAGRAM') or self.extract_field(text, 'MERMAID')
        if mermaid_field:
            mermaid_field = re.sub(r'^```\w*\n?', '', mermaid_field)
            mermaid_field = re.sub(r'\n?```$', '', mermaid_field)
            return mermaid_field.strip()
        return ''

def parse_gemini_output(text: str) -> dict:
    return GeminiOutputParser().parse(text)
