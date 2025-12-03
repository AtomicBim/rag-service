"""
File Processing Workflow
Orchestrates audio extraction and speech recognition
"""
import os
import logging
import aiohttp
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Supported formats
VIDEO_FORMATS = ['.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.flv']
AUDIO_FORMATS = ['.mp3', '.wav', '.m4a', '.aac', '.opus', '.ogg', '.wma', '.flac']


class FileProcessor:
    """
    Processes files through the microservices pipeline
    """

    def __init__(self, audio_extractor_url: str, speech_recognition_url: str):
        """
        Initialize processor

        Args:
            audio_extractor_url: URL of audio extractor service
            speech_recognition_url: URL of speech recognition service
        """
        self.audio_extractor_url = audio_extractor_url
        self.speech_recognition_url = speech_recognition_url

    def get_file_type(self, filename: str) -> str:
        """
        Determine file type

        Args:
            filename: File name

        Returns:
            'video', 'audio', or 'unknown'
        """
        ext = os.path.splitext(filename)[1].lower()

        if ext in VIDEO_FORMATS:
            return 'video'
        elif ext in AUDIO_FORMATS:
            return 'audio'
        else:
            return 'unknown'

    async def extract_audio(
        self,
        video_path: str,
        status_callback: Optional[Callable] = None
    ) -> Optional[str]:
        """
        Extract audio from video file

        Args:
            video_path: Path to video file
            status_callback: Callback for status updates

        Returns:
            Path to extracted audio or None on error
        """
        logger.info(f"Extracting audio from: {video_path}")

        if status_callback:
            await status_callback("🎬 Извлечение аудио из видео...")

        try:
            async with aiohttp.ClientSession() as session:
                with open(video_path, 'rb') as f:
                    form = aiohttp.FormData()
                    form.add_field('file', f, filename=os.path.basename(video_path))

                    async with session.post(
                        f"{self.audio_extractor_url}/extract",
                        data=form,
                        timeout=aiohttp.ClientTimeout(total=600)
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"Audio extraction failed: {error_text}")
                            return None

                        result = await response.json()

                        if result["status"] == "success":
                            audio_path = result["output_path"]
                            logger.info(f"Audio extracted: {audio_path}")

                            if status_callback:
                                await status_callback("✅ Аудио извлечено успешно")

                            return audio_path
                        else:
                            logger.error("Audio extraction failed")
                            return None

        except Exception as e:
            logger.error(f"Error extracting audio: {e}", exc_info=True)
            return None

    async def recognize_speech(
        self,
        audio_path: str,
        status_callback: Optional[Callable] = None
    ) -> Optional[dict]:
        """
        Recognize speech from audio file

        Args:
            audio_path: Path to audio file
            status_callback: Callback for status updates

        Returns:
            Recognition result dict or None on error
        """
        logger.info(f"Recognizing speech from: {audio_path}")

        if status_callback:
            await status_callback("🎤 Распознавание речи (WhisperX + диаризация)...")

        try:
            async with aiohttp.ClientSession() as session:
                with open(audio_path, 'rb') as f:
                    form = aiohttp.FormData()
                    form.add_field('file', f, filename=os.path.basename(audio_path))

                    async with session.post(
                        f"{self.speech_recognition_url}/recognize",
                        data=form,
                        timeout=aiohttp.ClientTimeout(total=1800)  # 30 min timeout
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"Speech recognition failed: {error_text}")
                            return None

                        result = await response.json()

                        if result["status"] == "success":
                            logger.info("Speech recognition completed")

                            if status_callback:
                                await status_callback("✅ Распознавание завершено")

                            return result["result"]
                        else:
                            logger.error("Speech recognition failed")
                            return None

        except Exception as e:
            logger.error(f"Error recognizing speech: {e}", exc_info=True)
            return None

    async def process_file(
        self,
        file_path: str,
        file_name: str,
        status_callback: Optional[Callable] = None
    ) -> dict:
        """
        Process file through the complete pipeline

        Args:
            file_path: Path to input file
            file_name: Original file name
            status_callback: Callback for status updates

        Returns:
            dict with status and result
        """
        logger.info(f"Processing file: {file_name}")

        # Determine file type
        file_type = self.get_file_type(file_name)

        if file_type == 'unknown':
            logger.error(f"Unsupported file type: {file_name}")
            return {
                "status": "error",
                "error": "Неподдерживаемый формат файла"
            }

        try:
            # If video, extract audio first
            if file_type == 'video':
                audio_path = await self.extract_audio(file_path, status_callback)

                if not audio_path:
                    return {
                        "status": "error",
                        "error": "Не удалось извлечь аудио из видео"
                    }

                # Clean up original video file
                try:
                    os.remove(file_path)
                except:
                    pass

            else:
                # Audio file, use directly
                audio_path = file_path

                if status_callback:
                    await status_callback("🎵 Аудио файл получен")

            # Recognize speech
            result = await self.recognize_speech(audio_path, status_callback)

            if not result:
                return {
                    "status": "error",
                    "error": "Не удалось распознать речь"
                }

            # Clean up audio file
            try:
                os.remove(audio_path)
            except:
                pass

            return {
                "status": "success",
                "result": result
            }

        except Exception as e:
            logger.error(f"Error processing file: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
