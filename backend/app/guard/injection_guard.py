import structlog
import re

logger = structlog.get_logger()

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?prior\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"forget\s+what\s+i\s+told\s+you", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"print\s+your\s+instructions", re.IGNORECASE),
]

def check_prompt_injection(user_input: str, user_id: str, tenant_id: str) -> bool:
    """
    Checks user input against heuristic patterns for prompt injection.
    Returns True if safe, False if an injection attempt is detected.
    """
    for pattern in INJECTION_PATTERNS:
        if pattern.search(user_input):
            logger.warning(
                "prompt_injection_detected",
                user_id=user_id,
                tenant_id=tenant_id,
                input_snippet=user_input[:100],
                pattern=pattern.pattern
            )
            return False
            
    return True
