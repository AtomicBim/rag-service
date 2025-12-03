"""
LLM Analyzer Integration
Handles communication with LLM Analyzer service
"""
import os
import json
import logging
import aiohttp
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

LLM_ANALYZER_URL = os.getenv("LLM_ANALYZER_URL", "http://llm_analyzer:8005")


async def request_analysis(json_file_path: str, analysis_type: str) -> Dict[str, Any]:
    """
    Request analysis from LLM Analyzer service

    Args:
        json_file_path: Path to transcript JSON file
        analysis_type: Type of analysis (summarize, positions, tasks, enhance_json)

    Returns:
        Analysis result dict with status and result/error
    """
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "json_file_path": json_file_path,
                "analysis_type": analysis_type
            }

            logger.info(f"Requesting {analysis_type} analysis for {json_file_path}")

            async with session.post(
                f"{LLM_ANALYZER_URL}/analyze",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=180)  # 3 minutes timeout for LLM
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Analysis completed: {analysis_type}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Analysis failed: {response.status} - {error_text}")
                    return {
                        "status": "error",
                        "error": f"HTTP {response.status}: {error_text}"
                    }

    except aiohttp.ClientTimeout:
        logger.error(f"Analysis timeout for {analysis_type}")
        return {
            "status": "error",
            "error": "Таймаут запроса к LLM (>3 минут). Возможно, LM Studio не запущена."
        }
    except Exception as e:
        logger.error(f"Error requesting analysis: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


def create_llm_keyboard(json_file_path: str, file_hash: str, exclude_actions: set = None) -> list:
    """
    Create inline keyboard with LLM analysis options

    Args:
        json_file_path: Path to transcript JSON file (for logging/debugging)
        file_hash: Hash identifier for the file (must be consistent across calls)
        exclude_actions: Set of action types to exclude (already completed)

    Returns:
        Inline keyboard structure (flat array)
    """
    if exclude_actions is None:
        exclude_actions = set()

    logger.info(f"create_llm_keyboard called with file_hash={file_hash}, exclude_actions: {exclude_actions}")

    # All available buttons
    all_buttons = [
        {
            "text": "📝 Саммаризация",
            "action": "summarize",
        },
        {
            "text": "⚖️ Позиции сторон",
            "action": "positions",
        },
        {
            "text": "✅ Задачи и ответственные",
            "action": "tasks",
        },
        {
            "text": "🔄 Enhanced JSON",
            "action": "enhance_json",
        }
    ]

    # Filter out excluded actions and build keyboard
    keyboard = []
    for btn in all_buttons:
        if btn["action"] not in exclude_actions:
            keyboard.append({
                "text": btn["text"],
                "callback_data": {
                    "action": btn["action"],
                    "file_id": file_hash
                }
            })
            logger.debug(f"Added button: {btn['text']} (action: {btn['action']})")
        else:
            logger.debug(f"Excluded button: {btn['text']} (action: {btn['action']})")

    logger.info(f"Returning keyboard with {len(keyboard)} buttons")
    return keyboard
