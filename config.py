"""
Configuration for AICRA (AI Code Review and Automation).
All settings in one place.
"""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), 'config', '.env'))


class Config:
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
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ai_code_review")
    
    # ── GitHub ──
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    GITHUB_API_URL = "https://api.github.com"
    GITHUB_ORG = os.getenv("GITHUB_ORG", "")  # If repos are under an org
    
    # ── SonarQube ──
    SONAR_HOST = os.getenv("SONAR_HOST", "http://10.32.83.180:9002")
    SONAR_TOKEN = os.getenv("SONAR_TOKEN", "")
    SONAR_SCANNER_PATH = os.getenv("SCANNER_PATH", "")
    SONAR_JAVA_HOME = os.getenv("SONAR_JAVA_HOME", "/opt/homebrew/opt/openjdk@17")
    
    # ── Gemini ──
    GEMINI_CLI_BIN = os.getenv("GEMINI_CLI_BIN", "gemini")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_DEFAULT_MODEL = "flash"
    GEMINI_LARGE_MODEL = "pro"
    GEMINI_LOW_TEMP = 0.1
    MAX_ISSUES_FOR_AI = int(os.getenv("MAX_ISSUES_FOR_AI", "60"))
    
    # ── Risk Detection ──
    RISK_LARGE_CHANGE_THRESHOLD = int(os.getenv("RISK_LARGE_CHANGE_THRESHOLD", "50"))
    RISK_SENSITIVE_PATTERNS = os.getenv("RISK_SENSITIVE_PATTERNS", "auth,security,permission,encrypt,payment,token,password,secret,credential,.env,docker-compose,Dockerfile").split(",")
    
    # ── Jira (MANDATORY: Use READ-ONLY API Token for security) ──
    JIRA_URL = os.getenv("JIRA_URL", "")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
    JIRA_DEFAULT_ENVIRONMENT = os.getenv("JIRA_DEFAULT_ENVIRONMENT", "UAT")
    
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
    STANDARDS_DIR = os.path.join(BASE_DIR, "scripts", "standards")
    STANDARDS_FILE = os.path.join(BASE_DIR, "scripts", "my_coding_standards.md")
