"""Knowledge Extractor - с чанкингом, агрегацией и AI-дедупликацией"""

from openai import AsyncOpenAI
from app.config import get_settings
from typing import Dict, List
import logging
import asyncio
import re

settings = get_settings()
logger = logging.getLogger(__name__)


class KnowledgeExtractor:
    SYSTEM_PROMPT = """Ты — аналитик бизнес-переписки. Извлеки ТОЛЬКО полезную информацию для новых сотрудников.

## ИЗВЛЕКАТЬ:

### 1. ТОВАРЫ И УСЛУГИ
- Названия, виды, модели
- Характеристики (размеры, материалы, цвета)
- Опции и комплектации

### 2. МОНТАЖ И УСТАНОВКА
- Способы монтажа
- Особенности установки
- Что нужно от клиента

### 3. ДОСТАВКА
- Условия и зоны
- Сроки
- Самовывоз

### 4. РАБОТА С КЛИЕНТАМИ
- Типичные вопросы с ответами
- Возражения и как отвечать
- Важные уточнения

### 5. ВАЖНЫЕ ДЕТАЛИ
- Сроки изготовления
- Оплата, гарантии
- Бизнес-правила

## НЕ ИЗВЛЕКАТЬ:
❌ Конкретные цены
❌ Личные разговоры
❌ Диалоги с монтажниками/поставщиками
❌ ID заказов, телефоны
❌ Приветствия, "спасибо", "понятно"
❌ Эмоции без деловой информации

Формат: структурированный текст с заголовками ## и списками.
Максимум 50000 символов."""

    MERGE_SYSTEM_PROMPT = """Ты — аналитик бизнес-переписки. Твоя задача — объединить несколько фрагментов извлечённых знаний в один целостный документ.

Правила:
- Удали дублирующуюся информацию.
- Сгруппируй информацию по категориям (товары, монтаж, доставка, работа с клиентами, важные детали).
- Сохрани все уникальные детали.
- Приведи к единому стилю: используй заголовки ## и списки.
- Итоговый документ должен быть структурированным и удобным для чтения новыми сотрудниками.

Если в фрагментах есть противоречия, выбери наиболее вероятную версию (основываясь на частоте упоминаний или контексте).
"""

    def __init__(self, chunk_size: int = 500000, chunk_overlap: int = 2000, max_concurrent: int = 3):
        """
        :param chunk_size: максимальный размер чанка в символах
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

    async def _extract_from_chunk(self, chunk: str, chunk_index: int) -> str:
        """Извлекает знания из одного чанка."""
        logger.info(f"Processing chunk {chunk_index + 1}, size {len(chunk)} chars")

        prompt = f"""Проанализируй часть переписки (фрагмент {chunk_index + 1}) и извлеки знания для новых сотрудников.
Игнорируй: диалоги с монтажниками, цены, личные разговоры.

Фрагмент переписки:
{chunk}"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=12000
            )
            knowledge = response.choices[0].message.content.strip()
            logger.info(f"Chunk {chunk_index + 1} extracted {len(knowledge)} chars")
            return knowledge
        except Exception as e:
            logger.error(f"Error processing chunk {chunk_index + 1}: {e}")
            return f"# Ошибка в фрагменте {chunk_index + 1}\n\nНе удалось извлечь данные: {str(e)}"

    async def _merge_results(self, results: List[str]) -> str:
        """Объединяет несколько извлечённых фрагментов в один документ."""
        if not results:
            return "Нет данных для извлечения."

        if len(results) == 1:
            return results[0]

        combined = "\n\n---\n\n".join(results)

        max_input_tokens = 120000
        max_chars = max_input_tokens * 4
        if len(combined) > max_chars:
            logger.warning(f"Combined results too large ({len(combined)} chars), truncating to {max_chars}")
            combined = combined[:max_chars]

        merge_prompt = f"""Ниже представлены фрагменты извлечённых знаний из разных частей переписки. 
Объедини их в единый структурированный документ, удалив дубликаты и сгруппировав информацию по категориям.

Фрагменты:
{combined}
"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.MERGE_SYSTEM_PROMPT},
                    {"role": "user", "content": merge_prompt}
                ],
                temperature=0.2,
                max_tokens=12000
            )
            merged = response.choices[0].message.content.strip()
            logger.info(f"Merged result size: {len(merged)} chars")
            return merged
        except Exception as e:
            logger.error(f"Error merging results: {e}")
            return combined

    async def extract(self, content: str, max_size: int = 100000) -> Dict:
        """Основной метод для извлечения знаний с чанкингом и агрегацией."""
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

        # 4. При необходимости обрезаем до max_size
        if len(final_knowledge) > max_size:
            last_header = final_knowledge.rfind('\n## ', 0, max_size)
            if last_header > max_size * 0.6:
                final_knowledge = final_knowledge[:last_header].strip()
            else:
                final_knowledge = final_knowledge[:max_size].strip()
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
        max_size: int = 50000
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
            Dict с ключами: success, knowledge, original_size, merged_size, removed_duplicates
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

        # Подготавливаем данные для LLM — обрезаем если слишком много
        max_input_chars = 100000
        existing_for_prompt = existing_knowledge
        new_for_prompt = new_knowledge

        # Если суммарно слишком много, обрезаем обе части пропорционально
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
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.MERGE_SYSTEM_PROMPT},
                    {"role": "user", "content": merge_prompt}
                ],
                temperature=0.2,
                max_tokens=12000
            )

            merged = response.choices[0].message.content.strip()

            # Обрезаем до max_size
            if len(merged) > max_size:
                last_header = merged.rfind('\n## ', 0, max_size)
                if last_header > max_size * 0.6:
                    merged = merged[:last_header].strip()
                else:
                    merged = merged[:max_size].strip()

            # Проверяем, уменьшился ли размер (признак удаления дубликатов)
            naive_concat_size = len(existing_knowledge) + len(new_knowledge)
            removed = len(merged) < naive_concat_size * 0.85

            logger.info(f"Merge complete: {len(merged)} chars (was {naive_concat_size} naive), dedup={removed}")

            return {
                "success": True,
                "knowledge": merged,
                "original_size": naive_concat_size,
                "merged_size": len(merged),
                "removed_duplicates": removed
            }

        except Exception as e:
            logger.error(f"merge_knowledge error: {e}", exc_info=True)
            # Fallback: простая конкатенация с разделителем
            combined = f"{existing_knowledge}\n\n=== {new_file_name} ===\n\n{new_knowledge}"
            trimmed = combined[:max_size]
            return {
                "success": True,
                "knowledge": trimmed,
                "original_size": len(combined),
                "merged_size": len(trimmed),
                "removed_duplicates": False,
                "fallback": True,
                "error": f"AI merge failed, used concat: {e}"
            }


# Для обратной совместимости
knowledge_extractor = KnowledgeExtractor()