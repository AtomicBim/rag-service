import os
import sys
import requests
import gradio as gr
import config
from pathlib import Path
from qdrant_client import QdrantClient
from typing import Optional, Tuple, List
from openai import OpenAI

# Для просмотра файлов
try:
    import docx
    import pypdf
except ImportError:
    print("Warning: python-docx or pypdf not installed. Viewer will be limited.")

DOCS_DIR = os.getenv("DOCS_DIR", "./data")
EMBEDDING_MODEL = os.getenv("OPENROUTER_EMBEDDING_MODEL", "google/gemini-embedding-001")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

class RAGOrchestrator:
    def __init__(self, qdrant_client: QdrantClient):
        self.qdrant_client = qdrant_client
        
        if not OPENROUTER_API_KEY:
            print("❌ ОШИБКА: OPENROUTER_API_KEY не установлен.")
            self.openai_client = None
        else:
            print(f"Настройка OpenRouter клиента для эмбеддингов (модель: {EMBEDDING_MODEL})...")
            self.openai_client = OpenAI(
                api_key=OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1"
            )
        print("✅ Клиент-оркестратор готов к работе.")

    def get_embedding(self, text: str) -> Optional[list[float]]:
        """Получает эмбеддинг через OpenRouter."""
        if not self.openai_client:
            print("Клиент OpenAI не инициализирован.")
            return None
            
        try:
            resp = self.openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text
            )
            return resp.data[0].embedding
        except Exception as e:
            print(f"Ошибка получения эмбеддинга: {e}")
            return None

    def query_llm(self, question: str, context: str) -> str:
        """Обращается к LLM-сервису (rag-bot)."""
        result = self._make_api_request(
            config.OPENAI_API_ENDPOINT,
            {"question": question, "context": context},
            "answer",
            "LLM-сервису",
            120
        )
        return result or "Сервер вернул пустой ответ."
    
    def _make_api_request(self, endpoint: str, payload: dict, response_key: str, service_name: str, timeout: int):
        try:
            response = requests.post(endpoint, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json().get(response_key)
        except requests.exceptions.RequestException as e:
            error_msg = f"Ошибка при обращении к {service_name}: {e}"
            print(error_msg)
            return None if response_key == "embedding" else error_msg

    def process_query(self, question: str) -> Tuple[str, List[str], dict]:
        if not question:
            return "Пожалуйста, введите вопрос.", [], {}

        self._log_step(1, f"Получение эмбеддинга для вопроса: '{question[:30]}...'")
        question_embedding = self.get_embedding(question)
        if not question_embedding:
            return "Не удалось получить вектор для вопроса.", [], {}
        self._log_completion("эмбеддинг получен")

        self._log_step(2, "Поиск релевантного контекста в Qdrant...")
        structured_context, sources, chunks_map = self._search_and_prepare_context(question_embedding)
        if not structured_context:
            return "В базе знаний не найдено релевантного контекста.", [], {}

        self._log_step(3, "Отправка запроса на LLM-сервис...")
        answer = self.query_llm(question, structured_context)
        self._log_completion("ответ от LLM получен")

        return answer, sources, chunks_map
    
    def _search_and_prepare_context(self, question_embedding: list[float]) -> Tuple[list[dict], list[str], dict]:
        search_results = self.qdrant_client.search(
            collection_name=config.COLLECTION_NAME,
            query_vector=question_embedding,
            limit=config.SEARCH_LIMIT,
            with_payload=True
        )
        
        if not search_results:
            return [], [], {}
        
        context_payload = []
        chunks_map = {}
        
        for result in search_results:
            text = result.payload['text']
            fname = result.payload.get('source_file', 'unknown')
            
            context_payload.append({"text": text, "file": fname})
            
            if fname in chunks_map:
                chunks_map[fname] += "\n\n--- ЕЩЕ ОДИН ФРАГМЕНТ ---\n\n" + text
            else:
                chunks_map[fname] = text
        
        sources = sorted(list(chunks_map.keys()))[:5]
        self._log_completion(f"найдено {len(sources)} источников")
        return context_payload, sources, chunks_map
    
    def _log_step(self, step_num: int, message: str) -> None:
        print(f"\n{step_num}. {message}")
    
    def _log_completion(self, message: str) -> None:
        print(f"   ...{message}.")

def get_file_content(file_name: str) -> str:
    root_path = Path(DOCS_DIR)
    path = root_path / file_name
    
    # If not found directly, try to find it recursively
    if not path.exists():
        found_files = list(root_path.rglob(file_name))
        if found_files:
            path = found_files[0]
        else:
            return f"Файл '{file_name}' не найден в {DOCS_DIR} (и подпапках)."
    
    try:
        if path.suffix.lower() == ".docx":
            doc = docx.Document(path)
            return "\n".join([p.text for p in doc.paragraphs])
        elif path.suffix.lower() == ".pdf":
            reader = pypdf.PdfReader(path)
            return "\n".join([page.extract_text() for page in reader.pages])
        else:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        return f"Ошибка чтения файла: {e}"

# --- Инициализация и запуск Gradio ---
if __name__ == "__main__":
    try:
        print("Подключение к Qdrant...")
        q_client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)
        orchestrator = RAGOrchestrator(qdrant_client=q_client)

        print("\nЗапуск интерфейса Gradio...")
        
        with gr.Blocks(title="RAG Атомстройкомплекс") as demo:
            gr.Markdown("# 🧠 RAG-система для ВНД")
            
            # State to store relevant chunks for the current answer
            chunks_state = gr.State({})

            with gr.Row():
                with gr.Column(scale=1):
                    q_input = gr.Textbox(label="Ваш вопрос", placeholder="Введите вопрос...", lines=3)
                    ask_btn = gr.Button("🔍 Найти ответ", variant="primary")
                
                with gr.Column(scale=2):
                    answer_output = gr.Markdown(label="Ответ системы")
            
            gr.Markdown("### 📚 Источники и просмотр документов")
            with gr.Row():
                with gr.Column(scale=1):
                    sources_dropdown = gr.Dropdown(label="Найденные документы", interactive=True)
                with gr.Column(scale=2):
                    doc_viewer = gr.TextArea(label="Содержимое документа (релевантный фрагмент)", lines=15, interactive=False)

            def respond(question):
                ans, srcs, chunks = orchestrator.process_query(question)
                # Select first source if available
                first_src = srcs[0] if srcs else None
                # Get content for first source immediately
                first_content = ""
                if first_src and first_src in chunks:
                    first_content = chunks[first_src]
                
                return ans, gr.update(choices=srcs, value=first_src), chunks, first_content

            def show_source(file_name, chunks):
                if not file_name:
                    return ""
                if chunks and file_name in chunks:
                    return chunks[file_name]
                # Fallback to full content if somehow not in chunks (shouldn't happen for search results)
                return get_file_content(file_name)

            ask_btn.click(
                respond, 
                inputs=q_input, 
                outputs=[answer_output, sources_dropdown, chunks_state, doc_viewer]
            )
            
            sources_dropdown.change(
                show_source, 
                inputs=[sources_dropdown, chunks_state], 
                outputs=doc_viewer
            )
        
        demo.launch(server_name="0.0.0.0", server_port=7860)

    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")