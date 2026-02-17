"""
Configuration module for Text2SQL Agent.
Handles GPU detection, path configuration, and LLM parameters.
"""
import os
import subprocess
from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).parent.absolute()

def detect_gpu():
    """
    Detect if NVIDIA GPU is available for acceleration.
    
    Returns:
        bool: True if GPU is detected, False otherwise
    """
    try:
        result = subprocess.run(
            ['nvidia-smi'], 
            capture_output=True, 
            text=True, 
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return False

# GPU Detection
HAS_GPU = detect_gpu()

# Database Configuration
DB_NAME = os.getenv("DB_NAME", "ecommerce.db")
DB_PATH = PROJECT_ROOT / DB_NAME

# Ollama Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

# LLM Parameters (optimized for speed)
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_NUM_PREDICT = int(os.getenv("LLM_NUM_PREDICT", "512"))

# Retry Configuration
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Display configuration on import
if __name__ != "__main__":
    print("=" * 50)
    print("Text2SQL Agent Configuration")
    print("=" * 50)
    print(f"GPU Acceleration: {'✅ Enabled' if HAS_GPU else '❌ Disabled (CPU mode)'}")
    print(f"Database: {DB_PATH}")
    print(f"Ollama URL: {OLLAMA_BASE_URL}")
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Temperature: {LLM_TEMPERATURE}")
    print(f"Max Tokens: {LLM_NUM_PREDICT}")
    print("=" * 50)
