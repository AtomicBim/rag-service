"""
Yandex Messenger Bot API Client
Wrapper for Yandex Messenger Bot API
"""
import os
import logging
import aiohttp
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Yandex Messenger API base URL
API_BASE_URL = "https://botapi.messenger.yandex.net"


class YandexMessengerClient:
    """
    Asynchronous client for Yandex Messenger Bot API
    """

    def __init__(self, bot_token: str):
        """
        Initialize client

        Args:
            bot_token: Bot authentication token
        """
        self.bot_token = bot_token
        self.session: Optional[aiohttp.ClientSession] = None
        self.upload_dir = "/app/uploads"
        os.makedirs(self.upload_dir, exist_ok=True)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Optional[dict]:
        """
        Make HTTP request to Yandex API

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint
            **kwargs: Additional request parameters

        Returns:
            Response JSON or None on error
        """
        url = f"{API_BASE_URL}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"OAuth {self.bot_token}"

        session = await self._get_session()

        try:
            async with session.request(method, url, headers=headers, **kwargs) as response:
                if response.status == 200:
                    # Try to parse as JSON
                    try:
                        return await response.json()
                    except:
                        # If not JSON, return empty dict
                        return {}
                else:
                    # Read error response as text
                    try:
                        response_text = await response.text()
                    except:
                        response_text = "<unable to decode response>"

                    logger.error(
                        f"API request failed: {method} {endpoint} - "
                        f"Status: {response.status}, Response: {response_text}"
                    )
                    return None

        except Exception as e:
            logger.error(f"Request error: {e}", exc_info=True)
            return None

    async def test_connection(self) -> bool:
        """
        Test API connection

        Returns:
            bool: True if connection successful
        """
        # Try to get updates (simple API call)
        result = await self.get_updates(limit=1)
        return result is not None

    async def get_updates(
        self,
        offset: int = 0,
        limit: int = 100,
        timeout: int = 60
    ) -> Optional[List[Dict]]:
        """
        Get bot updates (long polling)

        Args:
            offset: Update ID offset
            limit: Max number of updates
            timeout: Long polling timeout

        Returns:
            List of updates or None on error
        """
        params = {
            "offset": offset,
            "limit": limit,
            "timeout": timeout
        }

        response = await self._make_request(
            "GET",
            "/bot/v1/messages/getUpdates/",
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout + 10)
        )

        if response and "updates" in response:
            return response["updates"]

        return None

    async def send_message(
        self,
        chat_id: str,
        text: str,
        inline_keyboard: Optional[List[List[Dict]]] = None
    ) -> Optional[Dict]:
        """
        Send text message to chat

        Args:
            chat_id: Target chat ID or login (for private chats, pass login from 'from' field)
            text: Message text
            inline_keyboard: Optional inline keyboard buttons (list of rows, each row is list of buttons)

        Returns:
            Response dict with message info or None on error
        """
        import json as json_module

        logger.info(f"Sending message to {chat_id}: {text[:50]}...")

        # For private chats, Yandex API requires 'login' field instead of 'chat_id'
        # Login format: email (e.g., "user@domain.ru")
        # Group chat_id format: numeric or special format
        if "@" in chat_id:
            # Private chat - use login
            payload = {
                "login": chat_id,
                "text": text
            }
        else:
            # Group chat - use chat_id
            payload = {
                "chat_id": chat_id,
                "text": text
            }

        # Add inline keyboard if provided
        if inline_keyboard:
            # Yandex Messenger expects inline_keyboard as array of rows (each row is array of buttons)
            # Flatten if needed (single row of buttons)
            payload["inline_keyboard"] = inline_keyboard

            # DEBUG: Log the payload to verify JSON structure
            try:
                json_str = json_module.dumps(payload, ensure_ascii=False, indent=2)
                logger.debug(f"Payload with inline_keyboard:\n{json_str}")
            except Exception as e:
                logger.error(f"Failed to serialize payload to JSON: {e}")
                return None

        response = await self._make_request(
            "POST",
            "/bot/v1/messages/sendText/",
            json=payload
        )

        if response:
            logger.info(f"Message sent successfully to {chat_id}")
            return response
        else:
            logger.error(f"Failed to send message to {chat_id}")
            return None

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> bool:
        """
        Answer callback query from inline keyboard button

        Args:
            callback_query_id: Callback query ID
            text: Optional notification text
            show_alert: If True, show as alert instead of notification

        Returns:
            bool: True if successful
        """
        payload = {
            "callback_query_id": callback_query_id
        }

        if text:
            payload["text"] = text

        if show_alert:
            payload["show_alert"] = True

        response = await self._make_request(
            "POST",
            "/bot/v1/messages/answerCallbackQuery/",
            json=payload
        )

        return response is not None

    async def download_file(
        self,
        file_id: str,
        file_name: str = "unknown"
    ) -> Optional[str]:
        """
        Download file from Yandex Messenger

        Args:
            file_id: File ID from message
            file_name: Original file name

        Returns:
            Path to downloaded file or None on error
        """
        logger.info(f"Downloading file: {file_id} ({file_name})")

        # Download file using POST with application/json
        # According to Yandex Messenger Bot API documentation, getFile requires POST with JSON payload
        session = await self._get_session()

        try:
            payload = {"file_id": file_id}
            headers = {
                "Authorization": f"OAuth {self.bot_token}",
                "Content-Type": "application/json"
            }

            logger.info(f"Requesting file via POST application/json, file_id={file_id}")

            async with session.post(
                f"{API_BASE_URL}/bot/v1/messages/getFile/",
                headers=headers,
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to download file: {response.status}, Response: {error_text}")
                    return None

                # Save file (sanitize file_id to remove slashes)
                safe_file_id = file_id.replace("/", "_").replace("\\", "_")
                file_path = os.path.join(self.upload_dir, f"{safe_file_id}_{file_name}")

                with open(file_path, "wb") as f:
                    while True:
                        chunk = await response.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)

                logger.info(f"File downloaded: {file_path}")
                return file_path

        except Exception as e:
            logger.error(f"Error downloading file: {e}", exc_info=True)
            return None

    async def send_file(
        self,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None
    ) -> bool:
        """
        Send file to chat

        Args:
            chat_id: Target chat ID
            file_path: Path to file to send
            caption: Optional file caption

        Returns:
            bool: True if successful
        """
        logger.info(f"Sending file to {chat_id}: {file_path}")

        # First, upload file to get file_id
        session = await self._get_session()

        try:
            with open(file_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("file", f, filename=os.path.basename(file_path))

                headers = {"Authorization": f"OAuth {self.bot_token}"}

                async with session.post(
                    f"{API_BASE_URL}/bot/v1/files/upload/",
                    headers=headers,
                    data=form
                ) as response:
                    if response.status != 200:
                        logger.error(f"Failed to upload file: {response.status}")
                        return False

                    upload_response = await response.json()
                    file_id = upload_response.get("file_id")

                    if not file_id:
                        logger.error("No file_id in upload response")
                        return False

            # Now send file message
            payload = {
                "chat_id": chat_id,
                "file_id": file_id
            }

            if caption:
                payload["caption"] = caption

            response = await self._make_request(
                "POST",
                "/bot/v1/messages/sendFile/",
                json=payload
            )

            if response:
                logger.info(f"File sent successfully to {chat_id}")
                return True
            else:
                logger.error(f"Failed to send file message to {chat_id}")
                return False

        except Exception as e:
            logger.error(f"Error sending file: {e}", exc_info=True)
            return False
