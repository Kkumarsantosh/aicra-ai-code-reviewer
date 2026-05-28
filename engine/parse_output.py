"""
Parse Gemini output — extracted as a module.
"""

import sys
import os

# Import from scripts directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.parse_gemini_output import parse_gemini_output
