"""
Email Sender Module
Sends recognition results via Yandex SMTP
"""
import os
import logging
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Dict

logger = logging.getLogger(__name__)


class EmailSender:
    """
    Sends emails via Yandex SMTP
    """

    def __init__(self):
        """Initialize email sender with configuration from environment"""
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.yandex.ru")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")

        # Validate configuration
        if not self.smtp_user or not self.smtp_password:
            logger.error("SMTP credentials not configured")

    def _create_email_body(self, result: dict, file_name: str) -> str:
        """
        Create HTML email body with result summary

        Args:
            result: Recognition result dict
            file_name: Original file name

        Returns:
            HTML string
        """
        metadata = result.get("metadata", {})
        segments = result.get("segments", [])

        # Create segments preview (first 5 segments)
        segments_preview = ""
        for i, seg in enumerate(segments[:5]):
            speaker = seg.get("speaker", "Unknown")
            text = seg.get("text", "")
            start = seg.get("start", 0)
            end = seg.get("end", 0)

            segments_preview += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">{speaker}</td>
                <td style="padding: 8px; border: 1px solid #ddd;">{start:.2f}s - {end:.2f}s</td>
                <td style="padding: 8px; border: 1px solid #ddd;">{text}</td>
            </tr>
            """

        if len(segments) > 5:
            segments_preview += f"""
            <tr>
                <td colspan="3" style="padding: 8px; border: 1px solid #ddd; text-align: center; font-style: italic;">
                    ... и ещё {len(segments) - 5} сегментов (см. прикреплённый JSON файл)
                </td>
            </tr>
            """

        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
                h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
                h2 {{ color: #34495e; margin-top: 30px; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 15px; }}
                th {{ background-color: #3498db; color: white; padding: 12px; text-align: left; }}
                td {{ padding: 8px; border: 1px solid #ddd; }}
                .metadata {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .metadata-item {{ margin: 8px 0; }}
                .label {{ font-weight: bold; color: #2c3e50; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🎤 Результат распознавания речи</h1>

                <div class="metadata">
                    <h2>📊 Метаданные</h2>
                    <div class="metadata-item"><span class="label">Файл:</span> {file_name}</div>
                    <div class="metadata-item"><span class="label">Время обработки:</span> {metadata.get('processing_time', 'N/A')}</div>
                    <div class="metadata-item"><span class="label">Модель:</span> {metadata.get('model', 'N/A')}</div>
                    <div class="metadata-item"><span class="label">Устройство:</span> {metadata.get('device', 'N/A')}</div>
                    <div class="metadata-item"><span class="label">Язык:</span> {metadata.get('language', 'N/A')}</div>
                    <div class="metadata-item"><span class="label">Сегментов:</span> {metadata.get('num_segments', 0)}</div>
                    <div class="metadata-item"><span class="label">Спикеров:</span> {metadata.get('num_speakers', 0)}</div>
                    <div class="metadata-item"><span class="label">Символов текста:</span> {metadata.get('total_text_length', 0)}</div>
                </div>

                <h2>📝 Сегменты (предпросмотр)</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Спикер</th>
                            <th>Время</th>
                            <th>Текст</th>
                        </tr>
                    </thead>
                    <tbody>
                        {segments_preview}
                    </tbody>
                </table>

                <p style="margin-top: 30px; color: #7f8c8d; font-size: 0.9em;">
                    📎 Полный результат в формате JSON прикреплён к письму.
                </p>

                <p style="margin-top: 20px; color: #95a5a6; font-size: 0.85em; border-top: 1px solid #ecf0f1; padding-top: 15px;">
                    🤖 Это письмо создано автоматически ботом распознавания речи на базе WhisperX.
                </p>
            </div>
        </body>
        </html>
        """

        return html_body

    async def send_result(self, result: dict, file_name: str, recipient_email: str) -> bool:
        """
        Send recognition result via email

        Args:
            result: Recognition result dict
            file_name: Original file name
            recipient_email: Email address to send result to

        Returns:
            bool: True if email sent successfully
        """
        if not self.smtp_user or not self.smtp_password:
            logger.error("Cannot send email: SMTP credentials not configured")
            return False

        if not recipient_email:
            logger.error("Cannot send email: recipient_email not provided")
            return False

        try:
            logger.info(f"Sending email to {recipient_email}")

            # Create message (using 'mixed' for attachments)
            msg = MIMEMultipart('mixed')
            msg['From'] = self.smtp_user
            msg['To'] = recipient_email
            msg['Subject'] = f"Результат распознавания речи: {file_name}"

            # Create HTML body
            html_body = self._create_email_body(result, file_name)
            html_part = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(html_part)

            # Attach JSON file using MIMEApplication (correct way for Yandex SMTP)
            json_data = json.dumps(result, ensure_ascii=False, indent=2)
            json_filename = f"{os.path.splitext(file_name)[0]}_result.json"

            # Create MIMEApplication part for JSON with base64 encoding
            json_part = MIMEApplication(
                json_data.encode('utf-8'),
                _subtype='json',
                Name=json_filename  # CRITICAL: Name parameter for email clients
            )

            # Set Content-Disposition with filename (CRITICAL: both filename and name parameters)
            json_part.add_header(
                'Content-Disposition',
                'attachment',
                filename=json_filename
            )

            msg.attach(json_part)

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.smtp_use_tls:
                    server.starttls()

                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {recipient_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            return False
