from openai import AsyncOpenAI
from app.config import get_settings
from typing import List, Dict, Optional

settings = get_settings()

class AIService:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url
        )
        self.model = settings.openai_model
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """Generate chat completion using OpenAI Compatible API"""
        try:
            full_messages = []
            if system_prompt:
                full_messages.append({"role": "system", "content": system_prompt})
            full_messages.extend(messages)
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content
        except Exception as e:
            print(f"AI Service Error: {e}")
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

=== ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ ===
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
