from openai import AsyncOpenAI
from app.config import get_settings
from typing import List, Dict, Optional, Any
import time
import logging

settings = get_settings()
logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Простой Circuit Breaker для отслеживания доступности AI провайдера.
    - CLOSED: Провайдер работает, запросы идут к нему
    - OPEN: Провайдер недоступен, запросы идут к резервному
    - Автоматически переходит в HALF-OPEN после reset_seconds
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    
    def __init__(self, max_fails: int = 3, reset_seconds: int = 60):
        self.max_fails = max_fails
        self.reset_seconds = reset_seconds
        self.fail_count = 0
        self.state = self.CLOSED
        self.last_fail_time = 0
    
    def record_success(self):
        """Записать успешный запрос"""
        self.fail_count = 0
        self.state = self.CLOSED
    
    def record_failure(self):
        """Записать неудачный запрос"""
        self.fail_count += 1
        self.last_fail_time = time.time()
        if self.fail_count >= self.max_fails:
            self.state = self.OPEN
            logger.warning(f"Circuit breaker OPENED after {self.fail_count} consecutive failures")
    
    def is_available(self) -> bool:
        """Проверить, доступен ли провайдер для запросов"""
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            # Проверяем, прошло ли достаточно времени для попытки восстановления
            if time.time() - self.last_fail_time >= self.reset_seconds:
                self.state = self.HALF_OPEN
                logger.info("Circuit breaker moved to HALF_OPEN — will try primary provider")
                return True  # Дадим один шанс
            return False
        if self.state == self.HALF_OPEN:
            return True  # Один шанс для восстановления
        return False


class AIService:
    def __init__(self):
        # Основной AI провайдер
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url
        )
        self.model = settings.openai_model
        
        # Резервный AI провайдер (если настроен)
        self.backup_client = None
        self.backup_model = None
        self.has_backup = False
        
        if settings.openai_api_key_backup and settings.openai_base_url_backup:
            self.backup_client = AsyncOpenAI(
                api_key=settings.openai_api_key_backup,
                base_url=settings.openai_base_url_backup
            )
            self.backup_model = settings.openai_model_backup or self.model
            self.has_backup = True
            logger.info(f"Backup AI configured: {settings.openai_base_url_backup} (model: {self.backup_model})")
        else:
            logger.info("No backup AI configured — failover disabled")
        
        # Circuit breaker для основного провайдера
        self.circuit_breaker = CircuitBreaker(
            max_fails=getattr(settings, 'ai_failover_max_fails', 3),
            reset_seconds=getattr(settings, 'ai_failover_reset_seconds', 60)
        )
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Проверить доступность основного и резервного AI провайдеров.
        Отправляет минимальный запрос к каждому провайдеру и замеряет время ответа.
        Возвращает статус и задержку для каждого провайдера.
        """
        result = {
            "primary": {"available": False, "latency_ms": None, "error": None},
            "backup": {"available": False, "latency_ms": None, "error": None, "configured": self.has_backup},
            "circuit_breaker": {
                "state": self.circuit_breaker.state,
                "fail_count": self.circuit_breaker.fail_count,
                "max_fails": self.circuit_breaker.max_fails,
                "reset_seconds": self.circuit_breaker.reset_seconds,
            }
        }

        # Проверяем основного провайдера
        try:
            start = time.time()
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0
            )
            latency = round((time.time() - start) * 1000)
            result["primary"]["available"] = True
            result["primary"]["latency_ms"] = latency
            # Если health check прошёл успешно — сбрасываем circuit breaker
            self.circuit_breaker.record_success()
        except Exception as e:
            result["primary"]["available"] = False
            result["primary"]["error"] = str(e)
            # Записываем неудачу в circuit breaker
            self.circuit_breaker.record_failure()

        # Проверяем резервного провайдера (если настроен)
        if self.has_backup:
            try:
                start = time.time()
                response = await self.backup_client.chat.completions.create(
                    model=self.backup_model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    temperature=0
                )
                latency = round((time.time() - start) * 1000)
                result["backup"]["available"] = True
                result["backup"]["latency_ms"] = latency
            except Exception as e:
                result["backup"]["available"] = False
                result["backup"]["error"] = str(e)

        return result

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """Generate chat completion using OpenAI Compatible API with automatic failover"""
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        
        # Пробуем основного провайдера если circuit breaker позволяет
        if self.circuit_breaker.is_available():
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                result = response.choices[0].message.content
                self.circuit_breaker.record_success()
                return result
            except Exception as e:
                logger.warning(f"Primary AI provider failed: {e}")
                self.circuit_breaker.record_failure()
                
                # Если есть резервный провайдер — переключаемся
                if self.has_backup:
                    logger.info("Switching to backup AI provider...")
                    try:
                        response = await self.backup_client.chat.completions.create(
                            model=self.backup_model,
                            messages=full_messages,
                            temperature=temperature,
                            max_tokens=max_tokens
                        )
                        result = response.choices[0].message.content
                        logger.info("Backup AI provider responded successfully")
                        return result
                    except Exception as backup_error:
                        logger.error(f"Backup AI provider also failed: {backup_error}")
                        return f"Ошибка при генерации ответа: оба AI провайдера недоступны. Попробуйте позже."
                else:
                    return f"Ошибка при генерации ответа: {str(e)}"
        
        # Основной провайдер недоступен (circuit breaker OPEN) — пробуем резервный
        elif self.has_backup:
            try:
                response = await self.backup_client.chat.completions.create(
                    model=self.backup_model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                result = response.choices[0].message.content
                logger.info("Used backup AI provider (primary circuit breaker is OPEN)")
                return result
            except Exception as e:
                logger.error(f"Backup AI provider failed (primary already unavailable): {e}")
                return f"Ошибка при генерации ответа: оба AI провайдера недоступны. Попробуйте позже."
        
        # Нет резервного, основной недоступен — всё равно пробуем (circuit breaker в HALF_OPEN)
        else:
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                result = response.choices[0].message.content
                self.circuit_breaker.record_success()
                return result
            except Exception as e:
                self.circuit_breaker.record_failure()
                return f"Ошибка при генерации ответа: {str(e)}"
    
    async def get_user_context(self, user_id: str, appwrite_service) -> str:
        """
        Получить контекст пользователя из users.knowledge.
        Это основной метод для построения system prompt.
        """
        try:
            knowledge = await appwrite_service.get_user_knowledge(user_id)
            return knowledge
        except Exception as e:
            print(f"Error getting user context: {e}")
            return ""
    
    def build_context_prompt(self, knowledge: str, custom_instructions: str = "") -> str:
        """
        Построить system prompt с использованием извлечённых знаний.
        
        Args:
            knowledge: Извлечённые знания из users.knowledge
            custom_instructions: Дополнительные инструкции пользователя
        """
        prompt = """Ты — ИИ-ассистент для сотрудников компании (менеджеров). Твоя задача — помогать менеджерам отвечать на вопросы клиентов, используя базу знаний.

ПРАВИЛА:
1. Ты общаешься с менеджером, а не с клиентом. Не обращайся к менеджеру как к клиенту.
2. Когда менеджер задаёт вопрос (или приводит вопрос клиента), ты должен:
   - Найти в базе знаний релевантную информацию.
   - Если нужны уточнения, то предложи уточнить необходимые детали.
   - Предложить готовый ответ или шаблон ответа, который менеджер может использовать.
   - **Оформляй готовый ответ или шаблон в виде блока кода с тройными обратными кавычками (```)**, чтобы он визуально выделялся, как вставка кода на сайтах.
   - Если уместно, укажи источник (раздел базы знаний) после блока кода.
3. Если информации в базе нет — честно скажи об этом и предложи, как лучше уточнить у клиента или что проверить.
4. Не используй местоимения «вы», «вам» по отношению к менеджеру. Используй нейтральные формулировки: «менеджер может ответить», «следует уточнить», «рекомендуется».
5. Отвечай профессионально, кратко, по делу. Если нужно, приведи структурированную информацию (списки, пункты)."""

        if knowledge:
            prompt += f"""

=== БАЗА ЗНАНИЙ КОМПАНИИ ===
{knowledge}
=== КОНЕЦ БАЗЫ ЗНАНИЙ ==="""

        if custom_instructions:
            prompt += f"""

=== ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ (НАИВЫСШИЙ ПРИОРИТЕТ) ===
ВНИМАНИЕ: Инструкции ниже имеют наивысший приоритет. Если между данными из базы знаний и этими инструкциями возникает противоречие, всегда следуй инструкциям.
{custom_instructions}"""
        
        return prompt
    
    def build_training_prompt(self, scenario: str = "general", chat_history: str = "") -> str:
        """Build system prompt for training mode"""
        scenarios = {
            "general": "общие вопросы о товарах и услугах",
            "sales": "продажи, работа с возражениями",
            "support": "техническая поддержка, решение проблем",
            "installation": "вопросы по установке и использованию"
        }
        
        scenario_desc = scenarios.get(scenario, scenarios["general"])
        
        prompt = f"""Ты - симулятор клиента для обучения сотрудников.

Сначала изучи контекст переписки и пойми:
- Какую компанию представляет сотрудник
- Какие товары/услуги она предлагает
- Как клиенты обычно общаются

РЕЖИМ ТРЕНИНГА: {scenario_desc}

ТВОЯ РОЛЬ:
1. Играй роль РЕАЛЬНОГО клиента этой компании
2. Задавай вопросы, которые реально задают клиенты (изучи контекст)
3. Используй естественный язык, типичные для клиентов фразы
4. Иногда создавай сложные ситуации - возражения, сомнения, нестандартные запросы
5. Реагируй на ответы сотрудника как живой клиент

ПРАВИЛА:
- Начни с типичного вопроса клиента
- Если ответ хороший - проявляй заинтересованность
- Если ответ неполный - задавай уточняющие вопросы
- Веди себя естественно, не формально"""

        if chat_history:
            prompt += f"""

=== КОНТЕКСТ ПЕРЕПИСКИ (ИЗУЧИ БИЗНЕС КОМПАНИИ) ===
{chat_history[:50000]}
=== КОНЕЦ КОНТЕКСТА ==="""
        else:
            prompt += """

ВНИМАНИЕ: Контекст не загружен. Симулируй общего клиента, интересующегося товарами/услугами."""
        
        return prompt
    
    async def generate_training_feedback(
        self,
        conversation: List[Dict[str, str]],
        chat_history: str = ""
    ) -> Dict:
        """Generate feedback after training session"""
        feedback_prompt = """Проанализируй диалог между сотрудником (assistant) и клиентом (user).

Дай развернутую обратную связь:

ОЦЕНКА: [от 1 до 10]

СИЛЬНЫЕ СТОРОНЫ:
- [что сотрудник сделал хорошо]

ЗОНЫ РОСТА:
- [что можно улучшить]

РЕКОМЕНДАЦИИ:
- [конкретные советы]

ОБЩИЙ КОММЕНТАРИЙ:
[развернутый анализ диалога]

=== ДИАЛОГ ===
"""
        for msg in conversation:
            role = "Сотрудник" if msg["role"] == "assistant" else "Клиент"
            feedback_prompt += f"\n{role}: {msg['content']}"
        
        if chat_history:
            feedback_prompt += f"\n\n=== ЭТАЛОННЫЕ ОТВЕТЫ ИЗ ПЕРЕПИСКИ ===\n{chat_history[:3000]}"
        
        response = await self.chat_completion(
            messages=[{"role": "user", "content": "Дай обратную связь по диалогу."}],
            system_prompt=feedback_prompt,
            temperature=0.5
        )
        
        return {
            "full_feedback": response,
            "overall_score": self._extract_score(response),
            "strengths": self._extract_list(response, "СИЛЬНЫЕ СТОРОНЫ"),
            "weaknesses": self._extract_list(response, "ЗОНЫ РОСТА"),
            "recommendations": self._extract_list(response, "РЕКОМЕНДАЦИИ")
        }
    
    def _extract_score(self, text: str) -> float:
        """Extract score from feedback text"""
        import re
        match = re.search(r'ОЦЕНКА[:\s]*(\d+(?:[.,]\d+)?)', text)
        if match:
            return float(match.group(1).replace(',', '.'))
        return 0.0
    
    def _extract_list(self, text: str, section: str) -> List[str]:
        """Extract list items from a section"""
        import re
        pattern = rf'{section}[:\s]*\n((?:[-•]\s*.+\n?)+)'
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            items = re.findall(r'[-•]\s*(.+)', match.group(1))
            return [item.strip() for item in items if item.strip()]
        return []


# Singleton instance
ai_service = AIService()
