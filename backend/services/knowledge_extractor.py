"""Knowledge Extractor - с чанкингом, агрегацией и AI-дедупликацией
Поддерживает повторные попытки при сетевых ошибках, безопасное падение.
"""

from openai import AsyncOpenAI
from app.config import get_settings
from typing import Dict, List
import logging
import asyncio
import re
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log
)
import openai

settings = get_settings()
logger = logging.getLogger(__name__)


class KnowledgeExtractor:
    SYSTEM_PROMPT = """Ты — аналитик бизнес-документов. Извлеки ТОЛЬКО полезную информацию для новых сотрудников.
## ИЗВЛЕКАТЬ:
### 1. ТОВАРЫ И УСЛУГИ
- Названия, виды, модели. На том языке на котором написано в оригинальном тексте
- Характеристики (размеры, материалы, цвета, состав, функционал)
- Опции и комплектации
### 2. ДОСТАВКА
- Условия и зоны (Доставка силами компании, транспортные компании, города)
- Сроки доставки товара из наличия и сроки поставки товара, если он идет под заказ
- Самовывоз. Откуда и через какое время после заказа можно забирать
- Отчего зависит стоимость доставки
 
### 3. ЦЕНА И ОПЛАТА
- Из чего формируется цена
- Условия скидок и акций
- Способы оплаты
- Предоплата и постоплата
- Работа по гарантийному письму
- Рассрочки и кредиты
### 4. РАБОТА С КЛИЕНТАМИ
- Типичные вопросы с ответами
- Возражения и как отвечать
- Важные уточнения
### 5. ЗАМЕРЫ И МОНТАЖ
- Способы монтажа
- Инструкции замеров
- Особенности установки
- Что нужно от клиента
- Самостоятельные замеры и монтажи (рекомендации)
### 6. ВАЖНЫЕ ДЕТАЛИ
- Сроки изготовления, годности, эксплуатации
- Гарантии (Сроки, что входит)
- Бизнес-правила 

### 7. ДОКУМЕНТЫ И ДАННЫЕ
- Договор и сметы
- Счет и закрывающие документы
- Банковская, юридическая и налоговая информация

### УТОЧНЕНИЯ
- Не присваивать свойства, характеристики, инструкции и т.д. от одного товара или услуги к другому
- Если какой-то информации не хватает в базе знаний, то проси менеджера подгрузить дополнительные документы с инструкциями и/или истории переписок с клиентами.
## НЕ ИЗВЛЕКАТЬ:
❌ Конкретные цены
❌ Диалоги с рекламщиками и поставщиками
❌ ID заказов, телефоны
❌ Приветствия, "спасибо", "понятно",
❌ Эмоции без деловой информации
Формат: структурированный текст с заголовками ## и списками.
Максимум 100000 символов."""

    MERGE_SYSTEM_PROMPT = """Ты — аналитик бизнес-документов. Твоя задача — объединить несколько фрагментов извлечённых знаний в один целостный документ.

Правила:
- Удали дублирующуюся информацию.
- Сгруппируй информацию по категориям (товары, монтаж, доставка, работа с клиентами, важные детали).
- Названия, виды, модели, товары. На том языке на котором написано в оригинальном тексте
- Сохрани все уникальные детали.
- Приведи к единому стилю: используй заголовки ## и списки.
- Итоговый документ должен быть структурированным и удобным для чтения новыми сотрудниками.

Если в фрагментах есть противоречия, выбери наиболее вероятную версию (основываясь на частоте упоминаний или контексте).
"""

    def __init__(self, chunk_size: int = 200000, chunk_overlap: int = 1000, max_concurrent: int = 3):
        """
        :param chunk_size: максимальный размер чанка в символах (уменьшен до 200k из-за токенов)
        :param chunk_overlap: перекрытие между чанками в символах
        :param max_concurrent: максимальное количество параллельных запросов к LLM
        """
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url
        )
        self.model = settings.openai_model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_concurrent = max_concurrent

    def _split_text_by_chunks(self, text: str) -> List[str]:
        """Разбивает текст на чанки с перекрытием, стараясь не разрывать предложения."""
        if not text.strip():
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + self.chunk_size
            if end >= text_len:
                chunks.append(text[start:])
                break

            # Ищем ближайший конец предложения
            search_start = max(end - 200, start)
            sep_pos = -1
            for pattern in [r'\.\s+', r'\?\s+', r'!\s+', r'\n\s*\n']:
                matches = list(re.finditer(pattern, text[search_start:end]))
                if matches:
                    last_match = matches[-1]
                    sep_pos = search_start + last_match.end()
                    break
            if sep_pos == -1:
                sep_pos = end

            chunk = text[start:sep_pos].strip()
            if chunk:
                chunks.append(chunk)

            start = max(sep_pos - self.chunk_overlap, start + 1)
            if start >= text_len or start <= sep_pos - self.chunk_overlap + 10:
                start = sep_pos

        return chunks

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type(
            (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError)
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    async def _call_llm(self, messages, **kwargs):
        """Вызов LLM с автоматическими повторными попытками при сетевых ошибках."""
        return await self.client.chat.completions.create(messages=messages, **kwargs)

    async def _extract_from_chunk(self, chunk: str, chunk_index: int) -> str:
        """Извлекает знания из одного чанка. При ошибке возвращает сырой чанк (не теряем данные)."""
        logger.info(f"Processing chunk {chunk_index + 1}, size {len(chunk)} chars")

        prompt = f"""Проанализируй часть документа (фрагмент {chunk_index + 1}) и извлеки знания для новых сотрудников.
Игнорируй: диалоги с монтажниками, цены, личные разговоры.

Фрагмент документа:
{chunk}"""

        try:
            response = await self._call_llm(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=16000  # уменьшено, т.к. извлечённые знания обычно короче
            )
            knowledge = response.choices[0].message.content.strip()
            logger.info(f"Chunk {chunk_index + 1} extracted {len(knowledge)} chars")
            return knowledge
        except Exception as e:
            logger.error(f"Error processing chunk {chunk_index + 1}: {e}. Returning raw chunk as fallback.")
            # Возвращаем исходный чанк с пометкой, чтобы LLM при слиянии сама решила, что с ним делать
            return f"# Необработанный фрагмент {chunk_index + 1}\n\n{chunk}"

    async def _merge_results(self, results: List[str]) -> str:
        """Объединяет несколько извлечённых фрагментов в один документ."""
        if not results:
            return "Нет данных для извлечения."

        if len(results) == 1:
            return results[0]

        combined = "\n\n---\n\n".join(results)

        max_input_tokens = 200000
        max_chars = max_input_tokens * 4
        if len(combined) > max_chars:
            logger.warning(f"Combined results too large ({len(combined)} chars), truncating to {max_chars}")
            combined = combined[:max_chars]

        merge_prompt = f"""Ниже представлены фрагменты извлечённых знаний из разных частей документов. 
Объедини их в единый структурированный документ, удалив дубликаты и сгруппировав информацию по категориям.

Фрагменты:
{combined}
"""
        try:
            response = await self._call_llm(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.MERGE_SYSTEM_PROMPT},
                    {"role": "user", "content": merge_prompt}
                ],
                temperature=0.2,
                max_tokens=24000
            )
            merged = response.choices[0].message.content.strip()
            logger.info(f"Merged result size: {len(merged)} chars")
            return merged
        except Exception as e:
            logger.error(f"Error merging results: {e}. Returning concatenated chunks.")
            return combined

    async def extract(self, content: str, max_size: int = 100000) -> Dict:
        """Основной метод для извлечения знаний с чанкингом и агрегацией. max_size — максимальный размер итогового документа."""
        original_size = len(content)

        if not content.strip():
            return {"success": False, "knowledge": "", "original_size": 0, "knowledge_size": 0, "error": "Empty"}

        logger.info(f"Starting extraction from {original_size} chars")

        # 1. Разбиваем на чанки
        chunks = self._split_text_by_chunks(content)
        logger.info(f"Split into {len(chunks)} chunks")

        # 2. Обрабатываем чанки параллельно
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def process_with_semaphore(chunk, idx):
            async with semaphore:
                return await self._extract_from_chunk(chunk, idx)

        tasks = [process_with_semaphore(chunk, i) for i, chunk in enumerate(chunks)]
        results = await asyncio.gather(*tasks)

        # 3. Объединяем результаты
        final_knowledge = await self._merge_results(results)

        # 4. При необходимости обрезаем до max_size (умная обрезка по границам)
        if len(final_knowledge) > max_size:
            final_knowledge = self._smart_truncate(final_knowledge, max_size)
            logger.info(f"Trimmed final knowledge to {len(final_knowledge)} chars")

        return {
            "success": True,
            "knowledge": final_knowledge,
            "original_size": original_size,
            "knowledge_size": len(final_knowledge)
        }

    # ========================================
    # AI-дедупликация при загрузке нескольких файлов
    # ========================================

    async def merge_knowledge(
        self,
        existing_knowledge: str,
        new_knowledge: str,
        new_file_name: str = "новый файл",
        max_size: int = 100000
    ) -> Dict:
        """
        Объединить существующую базу знаний с новыми извлечёнными знаниями.
        Удаляет дубликаты через LLM, оставляет только уникальную информацию.

        Args:
            existing_knowledge: текущая база знаний пользователя
            new_knowledge: знания извлечённые из нового файла
            new_file_name: имя файла (для контекста)
            max_size: максимальный размер итогового документа

        Returns:
            Dict с ключами: success, knowledge, original_size, merged_size, removed_duplicates, fallback
        """
        if not new_knowledge.strip():
            return {
                "success": False,
                "knowledge": existing_knowledge,
                "error": "Новые знания пустые"
            }

        # Если существующей базы нет — просто возвращаем новые знания
        if not existing_knowledge.strip():
            logger.info("No existing knowledge, returning new knowledge as-is")
            trimmed = new_knowledge[:max_size]
            return {
                "success": True,
                "knowledge": trimmed,
                "original_size": 0,
                "merged_size": len(trimmed),
                "removed_duplicates": False
            }

        logger.info(f"Merging knowledge: existing={len(existing_knowledge)} chars, new={len(new_knowledge)} chars")

        # Подготавливаем данные для LLM — обрезаем если слишком много (безопасно)
        max_input_chars = 300000  # увеличен лимит, чтобы реже обрезать
        existing_for_prompt = existing_knowledge
        new_for_prompt = new_knowledge

        total = len(existing_knowledge) + len(new_knowledge)
        if total > max_input_chars:
            ratio = max_input_chars / total
            existing_for_prompt = existing_knowledge[:int(len(existing_knowledge) * ratio)]
            new_for_prompt = new_knowledge[:int(len(new_knowledge) * ratio)]
            logger.warning(f"Truncated inputs for merge: existing={len(existing_for_prompt)}, new={len(new_for_prompt)}")

        merge_prompt = f"""У тебя есть два документа с базой знаний компании.

=== ТЕКУЩАЯ БАЗА ЗНАНИЙ ===
{existing_for_prompt}

=== НОВЫЕ ЗНАНИЯ (из файла "{new_file_name}") ===
{new_for_prompt}

ЗАДАЧА: Объедини эти документы в один. Правила:
1. Если информация из нового файла УЖЕ ЕСТЬ в текущей базе — НЕ дублируй её.
2. Если информация дополняет или уточняет существующую — добавь/обнови.
3. Если информация полностью новая — добавь в соответствующий раздел.
4. Сохрани структуру: заголовки ## и списки.
5. Убери повторы внутри самого нового документа.
6. Результат должен быть единым целостным документом."""

        try:
            response = await self._call_llm(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.MERGE_SYSTEM_PROMPT},
                    {"role": "user", "content": merge_prompt}
                ],
                temperature=0.2,
                max_tokens=24000
            )

            merged = response.choices[0].message.content.strip()

            # Умная обрезка до max_size по границам текста
            if len(merged) > max_size:
                merged = self._smart_truncate(merged, max_size)

            # Проверяем, уменьшился ли размер (признак удаления дубликатов)
            naive_concat_size = len(existing_knowledge) + len(new_knowledge)
            removed = len(merged) < naive_concat_size * 0.85

            logger.info(f"Merge complete: {len(merged)} chars (was {naive_concat_size} naive), dedup={removed}")

            return {
                "success": True,
                "knowledge": merged,
                "original_size": naive_concat_size,
                "merged_size": len(merged),
                "removed_duplicates": removed,
                "fallback": False
            }

        except Exception as e:
            logger.error(f"merge_knowledge error: {e}", exc_info=True)
            # Безопасный fallback: не обрезаем старую базу, добавляем новый блок с обрезкой при необходимости
            separator = f"\n\n=== {new_file_name} ===\n\n"
            if len(existing_knowledge) + len(separator) + len(new_knowledge) <= max_size:
                combined = existing_knowledge + separator + new_knowledge
            else:
                # Оставляем старую базу целиком, новый блок обрезаем
                available = max_size - len(existing_knowledge) - len(separator)
                if available > 100:
                    truncated_new = self._smart_truncate(new_knowledge, available)
                    combined = existing_knowledge + separator + truncated_new
                    logger.warning(f"Fallback: truncated new knowledge to {available} chars")
                else:
                    # Нет места даже для 100 символов — оставляем только старую базу
                    combined = existing_knowledge
                    logger.warning(f"No space for new file {new_file_name}, keeping existing knowledge only")
            return {
                "success": True,
                "knowledge": combined,
                "original_size": len(existing_knowledge) + len(new_knowledge),
                "merged_size": len(combined),
                "removed_duplicates": False,
                "fallback": True,
                "error": f"AI merge failed, used safe concat: {e}"
            }

    def _smart_truncate(self, text: str, max_size: int) -> str:
        """Обрезает текст до max_size, стараясь не разрывать предложения и абзацы."""
        if len(text) <= max_size:
            return text
        search_start = int(max_size * 0.85)
        # Ищем ближайший заголовок ## (учитываем начало строки)
        last_header = text.rfind('\n## ', search_start, max_size + int(max_size * 0.05))
        if last_header > search_start:
            return text[:last_header].strip()
        # Если заголовка нет, ищем конец абзаца
        last_para = text.rfind('\n\n', search_start, max_size + int(max_size * 0.05))
        if last_para > search_start:
            return text[:last_para].strip()
        # Ищем конец предложения
        last_sentence = -1
        for sep in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
            pos = text.rfind(sep, search_start, max_size + int(max_size * 0.05))
            if pos > last_sentence:
                last_sentence = pos + len(sep)
        if last_sentence > search_start:
            return text[:last_sentence].strip()
        # Fallback: жёсткая обрезка
        return text[:max_size].strip()


# Для обратной совместимости
knowledge_extractor = KnowledgeExtractor()