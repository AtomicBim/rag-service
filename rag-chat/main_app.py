import os
import requests
import gradio as gr
import config
from qdrant_client import QdrantClient
from typing import Optional, Tuple
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from root .env file
root_dir = Path(__file__).parent.parent
load_dotenv(root_dir / ".env")

class RAGOrchestrator:
    def __init__(self, qdrant_client: QdrantClient):
        self.qdrant_client = qdrant_client
        print("✅ Клиент-оркестратор готов к работе.")

    def get_embedding(self, text: str) -> Optional[list[float]]:
        """Получает эмбеддинг, обращаясь к сервису на GPU-машине."""
        return self._make_api_request(
            config.EMBEDDING_SERVICE_ENDPOINT, 
            {"text": text}, 
            "embedding", 
            "сервису эмбеддингов",
            60
        )

    def query_llm(self, question: str, context: str) -> str:
        """Обращается к LLM-сервису."""
        result = self._make_api_request(
            config.OPENAI_API_ENDPOINT,
            {"question": question, "context": context},
            "answer",
            "LLM-сервису",
            120
        )
        return result or "Сервер вернул пустой ответ."
    
    def _make_api_request(self, endpoint: str, payload: dict, response_key: str, service_name: str, timeout: int):
        """Общий метод для выполнения API-запросов."""
        try:
            response = requests.post(endpoint, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json().get(response_key)
        except requests.exceptions.RequestException as e:
            error_msg = f"Ошибка при обращении к {service_name}: {e}"
            print(error_msg)
            return None if response_key == "embedding" else error_msg

    def process_query(self, question: str) -> Tuple[str, str]:
        """Простой процесс обработки вопроса (для обратной совместимости)."""
        return self.process_query_advanced(question)
    
    def process_query_advanced(
        self, 
        question: str, 
        top_k: int = None, 
        threshold: float = None, 
        search_type: str = "hybrid",
        rerank: bool = True,
        debug_mode: bool = False
    ) -> Tuple[str, str, str]:
        """Расширенный процесс обработки с настраиваемыми параметрами."""
        if not question:
            return "Пожалуйста, введите вопрос.", "", ""
        
        # Использовать значения по умолчанию из конфигурации если не переданы
        if top_k is None:
            top_k = config.SEARCH_LIMIT
        if threshold is None:
            threshold = getattr(config, 'DEFAULT_THRESHOLD', 0.7)
            
        debug_log = ""
        
        def log_debug(message: str):
            nonlocal debug_log
            if debug_mode:
                debug_log += f"{message}\n"
            print(message)

        log_debug(f"🔍 Параметры поиска: top_k={top_k}, threshold={threshold}, type={search_type}, rerank={rerank}")
        
        self._log_step(1, f"Получение эмбеддинга для вопроса: '{question[:30]}...'")
        question_embedding = self.get_embedding(question)
        if not question_embedding:
            return "Не удалось получить вектор для вопроса. Проверьте сервис эмбеддингов.", "", debug_log
        self._log_completion("эмбеддинг получен")

        self._log_step(2, "Поиск релевантного контекста через Search Service...")
        structured_context, sources = self._search_and_prepare_context_advanced(
            question, top_k, threshold, search_type, rerank, log_debug
        )
        if not structured_context:
            return "В базе знаний не найдено релевантного контекста.", "", debug_log

        self._log_step(3, "Отправка запроса на LLM-сервис...")
        answer = self.query_llm(question, structured_context)
        self._log_completion("ответ от LLM получен")
        
        sources_text = f"Источники ({len(sources)}): {', '.join(sources)}"
        log_debug(f"✅ Обработка завершена. Найдено источников: {len(sources)}")

        if debug_mode:
            return answer, sources_text, debug_log
        else:
            return answer, sources_text
    
    def _search_and_prepare_context(self, question: str) -> Tuple[list[dict], list[str]]:
        """Простая версия поиска для обратной совместимости."""
        return self._search_and_prepare_context_advanced(question, config.SEARCH_LIMIT)
    
    def _search_and_prepare_context_advanced(
        self, 
        question: str, 
        top_k: int, 
        threshold: float = 0.7, 
        search_type: str = "hybrid",
        rerank: bool = True,
        log_func=None
    ) -> Tuple[list[dict], list[str]]:
        """Расширенный поиск контекста с настраиваемыми параметрами."""
        def log_debug(msg):
            if log_func:
                log_func(f"   {msg}")
        
        try:
            log_debug(f"Отправка запроса в Search Service: top_k={top_k}, threshold={threshold}")
            
            # Используем продвинутый Search Service с GPU машины
            search_payload = {
                "query": question,
                "top_k": top_k,
                "threshold": threshold,
                "search_type": search_type,
                "rerank": rerank
            }
            
            search_response = requests.post(
                config.SEARCH_SERVICE_ENDPOINT,
                json=search_payload,
                timeout=30
            )
            search_response.raise_for_status()
            search_data = search_response.json()
            
            log_debug(f"Получен ответ от Search Service: {len(search_data.get('results', []))} результатов")
            
            if not search_data.get("results"):
                self._log_completion("результаты не найдены")
                return [], []
            
            # СОЗДАЕМ КОНТЕКСТ В ФОРМАТЕ, КОТОРЫЙ ОЖИДАЕТ RAG-BOT
            context_payload = [
                {"text": result["text"], "file": result["source_file"]}
                for result in search_data["results"]
            ]
            
            # Список источников для отображения в UI
            sources = sorted(list(set([result["source_file"] for result in search_data["results"]])))
            log_debug(f"Обработано источников: {len(sources)} уникальных файлов")
            self._log_completion(f"найдено {len(sources)} источников через Search Service")
            return context_payload, sources
            
        except Exception as e:
            error_msg = f"Ошибка поиска через Search Service: {e}"
            print(error_msg)
            log_debug(f"ОШИБКА: {error_msg}")
            # Fallback на прямой Qdrant как резервный вариант
            return self._fallback_qdrant_search_advanced(question, top_k, threshold, log_func)
    
    def _fallback_qdrant_search(self, question: str) -> Tuple[list[dict], list[str]]:
        """Простая версия fallback поиска."""
        return self._fallback_qdrant_search_advanced(question, config.SEARCH_LIMIT)
    
    def _fallback_qdrant_search_advanced(
        self, 
        question: str, 
        top_k: int, 
        threshold: float = 0.7, 
        log_func=None
    ) -> Tuple[list[dict], list[str]]:
        """Резервный поиск через прямое обращение к Qdrant с параметрами."""
        def log_debug(msg):
            if log_func:
                log_func(f"   FALLBACK: {msg}")
                
        try:
            self._log_step("FALLBACK", "Использую прямой поиск в Qdrant")
            log_debug(f"Параметры fallback: top_k={top_k}, threshold={threshold}")
            
            question_embedding = self.get_embedding(question)
            if not question_embedding:
                log_debug("Не удалось получить эмбеддинг для fallback")
                return [], []
                
            search_results = self.qdrant_client.search(
                collection_name=config.COLLECTION_NAME,
                query_vector=question_embedding,
                limit=top_k,
                score_threshold=threshold,
                with_payload=True
            )
            
            log_debug(f"Qdrant вернул {len(search_results)} результатов")
            
            if not search_results:
                return [], []
            
            # Фильтруем по порогу схожести если Qdrant не поддерживает score_threshold
            filtered_results = [
                result for result in search_results 
                if getattr(result, 'score', 1.0) >= threshold
            ]
            
            log_debug(f"После фильтрации по порогу {threshold}: {len(filtered_results)} результатов")
            
            context_payload = [
                {"text": result.payload['text'], "file": result.payload.get('source_file', 'unknown')}
                for result in filtered_results
            ]
            
            sources = sorted(list(set([result.payload.get('source_file', 'unknown') for result in filtered_results])))
            self._log_completion(f"найдено {len(sources)} источников (fallback)")
            return context_payload, sources
            
        except Exception as fallback_error:
            error_msg = f"Критическая ошибка: и Search Service, и Qdrant недоступны: {fallback_error}"
            print(error_msg)
            if log_func:
                log_func(f"КРИТИЧЕСКАЯ ОШИБКА: {error_msg}")
            return [], []
    
    def _log_step(self, step_num: int, message: str) -> None:
        """Логирование шага обработки."""
        print(f"\n{step_num}. {message}")
    
    def _log_completion(self, message: str) -> None:
        """Логирование завершения шага."""
        print(f"   ...{message}.")

# --- Инициализация и запуск Gradio ---
if __name__ == "__main__":
    try:
        print("Подключение к Qdrant...")
        q_client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)
        
        orchestrator = RAGOrchestrator(qdrant_client=q_client)

        print("\nЗапуск расширенного интерфейса Gradio...")
        
        # Get configuration from environment variables
        gradio_title = os.getenv("GRADIO_TITLE", "RAG-система для ВНД Атомстройкомплекс")
        gradio_description = os.getenv("GRADIO_DESCRIPTION", "Введите свой вопрос. Система найдет релевантные документы и сгенерирует ответ.")
        
        # Создаем расширенный интерфейс с настраиваемыми параметрами поиска
        with gr.Blocks(title=gradio_title) as demo:
            gr.Markdown(f"# {gradio_title}")
            gr.Markdown(gradio_description)
            
            with gr.Row():
                with gr.Column(scale=2):
                    question = gr.Textbox(
                        lines=4, 
                        label="Ваш вопрос к базе знаний",
                        placeholder="Введите ваш вопрос здесь..."
                    )
                    
                with gr.Column(scale=1):
                    with gr.Group():
                        gr.Markdown("### ⚙️ Параметры поиска")
                        top_k = gr.Slider(
                            minimum=5, 
                            maximum=50, 
                            value=config.SEARCH_LIMIT, 
                            step=1,
                            label="Количество результатов (top-k)",
                            info="Сколько фрагментов искать в базе знаний"
                        )
                        
                        threshold = gr.Slider(
                            minimum=0.0, 
                            maximum=1.0, 
                            value=getattr(config, 'DEFAULT_THRESHOLD', 0.7), 
                            step=0.05,
                            label="Порог схожести",
                            info="Минимальная схожесть для включения результата"
                        )
                        
                        search_type = gr.Radio(
                            choices=["semantic", "hybrid", "keyword"], 
                            value="hybrid",
                            label="Тип поиска",
                            info="semantic=по смыслу, keyword=по словам, hybrid=комбинированный"
                        )
                        
                        rerank = gr.Checkbox(
                            value=True, 
                            label="Переранжирование результатов",
                            info="Улучшает качество поиска, но увеличивает время"
                        )
            
            with gr.Row():
                with gr.Column():
                    submit_btn = gr.Button("🔍 Найти ответ", variant="primary", size="lg")
                    clear_btn = gr.Button("🗑️ Очистить", variant="secondary")
            
            with gr.Row():
                with gr.Column(scale=2):
                    answer = gr.Textbox(
                        label="📝 Ответ", 
                        lines=8,
                        interactive=False
                    )
                with gr.Column(scale=1):
                    sources = gr.Textbox(
                        label="📚 Источники", 
                        lines=8,
                        interactive=False
                    )
            
            # Секция отладки (скрыта по умолчанию)
            with gr.Accordion("🔧 Режим отладки", open=False):
                debug_mode = gr.Checkbox(
                    value=False, 
                    label="Включить детальное логирование",
                    info="Показывает подробную информацию о процессе поиска"
                )
                debug_log = gr.Textbox(
                    label="🐛 Журнал отладки", 
                    lines=6,
                    interactive=False,
                    visible=False
                )
                
                def toggle_debug(debug_enabled):
                    return gr.update(visible=debug_enabled)
                
                debug_mode.change(
                    fn=toggle_debug, 
                    inputs=[debug_mode], 
                    outputs=[debug_log]
                )
            
            # Обработчик кнопки поиска
            def process_with_params(question, top_k, threshold, search_type, rerank, debug_mode):
                if debug_mode:
                    answer_text, sources_text, debug_text = orchestrator.process_query_advanced(
                        question, int(top_k), float(threshold), search_type, rerank, debug_mode
                    )
                    return answer_text, sources_text, debug_text
                else:
                    answer_text, sources_text = orchestrator.process_query_advanced(
                        question, int(top_k), float(threshold), search_type, rerank, debug_mode
                    )
                    return answer_text, sources_text, ""
            
            submit_btn.click(
                fn=process_with_params,
                inputs=[question, top_k, threshold, search_type, rerank, debug_mode],
                outputs=[answer, sources, debug_log]
            )
            
            # Обработчик кнопки очистки
            def clear_all():
                return "", "", "", ""
                
            clear_btn.click(
                fn=clear_all,
                outputs=[question, answer, sources, debug_log]
            )
            
            # Примеры вопросов
            gr.Examples(
                examples=[
                    "Какие требования к оформлению технической документации?",
                    "Какие меры безопасности должны соблюдаться при работе?",
                    "Какова процедура согласования проектной документации?",
                    "Какие стандарты качества применяются в компании?"
                ],
                inputs=question,
                label="💡 Примеры вопросов"
            )
        
        # Запускаем Gradio с настройками из переменных окружения  
        server_name = os.getenv("GRADIO_SERVER_NAME", "0.0.0.0")
        server_port = int(os.getenv("RAG_CHAT_PORT", "7860"))
        
        demo.launch(server_name=server_name, server_port=server_port)

    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ ОРКЕСТРАТОРА: {e}")
