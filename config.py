"""
Configuration for AICRA (AI Code Review and Automation).
All settings in one place.
"""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), 'config', '.env'))

class Config:
    _GEMINI_FAST     = "gemini-2.0-flash"
    _GEMINI_POWERFUL = "gemini-2.5-pro-preview"

    # ── App ──
    APP_NAME = "AICRA"
    HOST = "0.0.0.0"
    PORT = 3000
    DEBUG = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t", "yes")
    SECRET_KEY = os.getenv("SECRET_KEY", "ai-code-review-secret-key-change-me")
    
    # ── MySQL ──
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ai_code_review")
    
    # ── GitHub ──
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    GITHUB_API_URL = "https://api.github.com"
    GITHUB_ORG = os.getenv("GITHUB_ORG", "")  # If repos are under an org
    
    # ── SonarQube ──
    SONAR_HOST = os.getenv("SONAR_HOST", "http://localhost:9000")
    SONAR_TOKEN = os.getenv("SONAR_TOKEN", "")
    SONAR_SCANNER_PATH = os.getenv("SCANNER_PATH", "")
    SONAR_JAVA_HOME = os.getenv("SONAR_JAVA_HOME", "/opt/homebrew/opt/openjdk@17")
    
    # ── AI Provider (unified) ──
    # Choose: openai | anthropic | gemini | gemini_cli
    AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini_cli")

    # ── OpenAI ──
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_FAST_MODEL = os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")
    OPENAI_POWERFUL_MODEL = os.getenv("OPENAI_POWERFUL_MODEL", "gpt-4o")

    # ── Anthropic Claude ──
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_FAST_MODEL = os.getenv("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5-20251001")
    ANTHROPIC_POWERFUL_MODEL = os.getenv("ANTHROPIC_POWERFUL_MODEL", "claude-sonnet-4-6")

    # ── Google Gemini (Python SDK, AI_PROVIDER=gemini) ──
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # ── Gemini CLI (AI_PROVIDER=gemini_cli) ──
    GEMINI_CLI_BIN = os.getenv("GEMINI_CLI_BIN", "gemini")

    # ── Temperature ────────────────────────────────────────────────────────────
    # AI_TEMPERATURE      — analytical tasks: code review, classification, risk scoring
    # AI_TEMPERATURE_JSON — structured-output tasks: document parsing, JSON grouping
    # Industry standard for code analysis: 0.1–0.2.  Creative writing: 0.7–1.0.
    AI_TEMPERATURE      = float(os.getenv("AI_TEMPERATURE",      "0.2"))
    AI_TEMPERATURE_JSON = float(os.getenv("AI_TEMPERATURE_JSON", "0.1"))

    # ── Custom AI base URL (Azure OpenAI, Ollama, LiteLLM proxy, etc.) ──
    AI_BASE_URL = os.getenv("AI_BASE_URL", "")

    # ── Custom AI Bridge (AI_PROVIDER=custom) ──
    CUSTOM_AI_URL      = os.getenv("CUSTOM_AI_URL", "")
    CUSTOM_AI_USER     = os.getenv("CUSTOM_AI_USER", "")
    CUSTOM_AI_PASSWORD = os.getenv("CUSTOM_AI_PASSWORD", "")

    # ── Resolved model tiers — auto-selected from AI_PROVIDER ──
    _FAST_MODELS = {
        "openai":     os.getenv("OPENAI_FAST_MODEL",    "gpt-4o-mini"),
        "anthropic":  os.getenv("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5-20251001"),
        "gemini":     _GEMINI_FAST,
        "vertexai":   _GEMINI_FAST,
        "gemini_cli": _GEMINI_FAST,
        "custom":     "custom",
    }
    _POWERFUL_MODELS = {
        "openai":     os.getenv("OPENAI_POWERFUL_MODEL",    "gpt-4o"),
        "anthropic":  os.getenv("ANTHROPIC_POWERFUL_MODEL", "claude-sonnet-4-6"),
        "gemini":     _GEMINI_POWERFUL,
        "vertexai":   _GEMINI_POWERFUL,
        "gemini_cli": _GEMINI_POWERFUL,
        "custom":     "custom",
    }
    AI_FAST_MODEL     = _FAST_MODELS.get(AI_PROVIDER,     _FAST_MODELS["openai"])
    AI_POWERFUL_MODEL = _POWERFUL_MODELS.get(AI_PROVIDER, _POWERFUL_MODELS["openai"])

    MAX_ISSUES_FOR_AI = int(os.getenv("MAX_ISSUES_FOR_AI", "60"))
    
    # ── Risk Detection ──
    RISK_LARGE_CHANGE_THRESHOLD = int(os.getenv("RISK_LARGE_CHANGE_THRESHOLD", "50"))
    RISK_SENSITIVE_PATTERNS = os.getenv("RISK_SENSITIVE_PATTERNS", "auth,security,permission,encrypt,payment,token,password,secret,credential,.env,docker-compose,Dockerfile").split(",")
    
    # ── Jira (MANDATORY: Use READ-ONLY API Token for security) ──
    JIRA_URL = os.getenv("JIRA_URL", "")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
    JIRA_DEFAULT_ENVIRONMENT = os.getenv("JIRA_DEFAULT_ENVIRONMENT", "UAT")
    JIRA_DEFAULT_PROJECT = os.getenv("JIRA_DEFAULT_PROJECT", "")
    
    # ── Jira Delivery Metrics Configuration ──
    JIRA_COMPLETED_STATUSES = os.getenv("JIRA_COMPLETED_STATUSES", "Done,Closed,Released,Resolved").split(",")
    JIRA_IN_PROGRESS_STATUSES = os.getenv("JIRA_IN_PROGRESS_STATUSES", "In Progress,In Dev,In Review,In QA").split(",")
    
    JIRA_FEATURE_TYPES = os.getenv("JIRA_FEATURE_TYPES", "Story,Task,Feature,Enhancement").split(",")
    JIRA_BUG_TYPES = os.getenv("JIRA_BUG_TYPES", "Bug,Defect,Incident").split(",")
    JIRA_TECH_DEBT_TYPES = os.getenv("JIRA_TECH_DEBT_TYPES", "Technical Debt,Improvement,Refactoring").split(",")
    JIRA_RESEARCH_TYPES = os.getenv("JIRA_RESEARCH_TYPES", "Sub-task,Spike,Research,PoC").split(",")
    
    # ── Paths ──
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
    REPORTS_DIR = os.path.join(BASE_DIR, "reports")
    PROMPT_FILE = os.path.join(BASE_DIR, "engine", "prompt.txt")
    STANDARDS_DIR = os.path.join(BASE_DIR, "standards")
    STANDARDS_FILE = os.path.join(BASE_DIR, "standards", "my_coding_standards.md")
