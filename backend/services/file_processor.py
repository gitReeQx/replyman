from bs4 import BeautifulSoup
import json
from typing import Dict, Optional, List
import re

class FileProcessor:
    """Service for processing uploaded chat files (txt, json, html)"""
    
    async def process_file(self, content: bytes, content_type: str, filename: str) -> Dict:
        """Process uploaded file and extract text content"""
        try:
            # Decode content
            text_content = content.decode('utf-8', errors='ignore')
            
            if 'json' in content_type or filename.endswith('.json'):
                return self._process_json(text_content)
            elif 'html' in content_type or filename.endswith('.html') or filename.endswith('.htm'):
                return self._process_html(text_content)
            else:
                # Default: treat as plain text
                return self._process_txt(text_content)
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "content": ""
            }
    
    def _process_txt(self, content: str) -> Dict:
        """Process plain text file"""
        # Clean up the content
        cleaned = self._clean_text(content)
        
        # Try to detect conversation format
        conversations = self._parse_text_conversation(cleaned)
        
        return {
            "success": True,
            "content": cleaned,
            "conversations": conversations,
            "format": "txt"
        }
    
    def _process_json(self, content: str) -> Dict:
        """Process JSON file - supports various formats"""
        try:
            data = json.loads(content)
            
            # Try to detect format
            if isinstance(data, list):
                # Could be array of messages
                return self._process_json_messages(data)
            elif isinstance(data, dict):
                # Could be WhatsApp, Telegram or other export
                return self._process_json_dict(data)
            
            return {
                "success": True,
                "content": json.dumps(data, ensure_ascii=False, indent=2),
                "conversations": [],
                "format": "json"
            }
        except json.JSONDecodeError:
            # Fall back to text processing
            return self._process_txt(content)
    
    def _process_json_messages(self, messages: List) -> Dict:
        """Process JSON array of messages"""
        conversations = []
        text_parts = []
        
        for msg in messages:
            if isinstance(msg, dict):
                # Common fields
                sender = msg.get('sender', msg.get('from', msg.get('author', msg.get('name', 'Unknown'))))
                text = msg.get('text', msg.get('message', msg.get('content', msg.get('body', ''))))
                timestamp = msg.get('timestamp', msg.get('date', msg.get('time', '')))
                
                if text:
                    if isinstance(text, dict):
                        text = text.get('text', str(text))
                    
                    text = str(text)
                    line = f"[{sender}]: {text}"
                    if timestamp:
                        line = f"[{timestamp}] {line}"
                    
                    text_parts.append(line)
                    conversations.append({
                        "sender": sender,
                        "text": text,
                        "timestamp": timestamp
                    })
        
        return {
            "success": True,
            "content": "\n".join(text_parts),
            "conversations": conversations,
            "format": "json_messages"
        }
    
    def _process_json_dict(self, data: Dict) -> Dict:
        """Process JSON dictionary (exports from messengers)"""
        conversations = []
        text_parts = []
        
        # WhatsApp format
        if 'messages' in data:
            messages = data['messages']
            if isinstance(messages, list):
                for msg in messages:
                    sender = msg.get('sender', msg.get('from', 'Unknown'))
                    text = msg.get('text', msg.get('message', ''))
                    if text:
                        text_parts.append(f"[{sender}]: {text}")
                        conversations.append({
                            "sender": sender,
                            "text": str(text),
                            "timestamp": msg.get('timestamp', '')
                        })
        
        # Telegram format
        elif 'chats' in data:
            chats = data['chats'].get('list', [])
            for chat in chats:
                for msg in chat.get('messages', []):
                    sender = msg.get('from', 'Unknown')
                    text = msg.get('text', '')
                    if isinstance(text, list):
                        text = ' '.join([t if isinstance(t, str) else t.get('text', '') for t in text])
                    if text:
                        text_parts.append(f"[{sender}]: {text}")
                        conversations.append({
                            "sender": sender,
                            "text": str(text),
                            "timestamp": msg.get('date', '')
                        })
        
        # Generic nested structure
        else:
            def extract_messages(obj, path=""):
                if isinstance(obj, dict):
                    if 'message' in obj or 'text' in obj:
                        sender = obj.get('sender', obj.get('from', obj.get('author', 'Unknown')))
                        text = obj.get('message', obj.get('text', ''))
                        if text:
                            text_parts.append(f"[{sender}]: {text}")
                            conversations.append({
                                "sender": sender,
                                "text": str(text),
                                "timestamp": obj.get('timestamp', obj.get('date', ''))
                            })
                    else:
                        for key, value in obj.items():
                            extract_messages(value, f"{path}.{key}")
                elif isinstance(obj, list):
                    for item in obj:
                        extract_messages(item, path)
            
            extract_messages(data)
        
        return {
            "success": True,
            "content": "\n".join(text_parts),
            "conversations": conversations,
            "format": "json_dict"
        }
    
    def _process_html(self, content: str) -> Dict:
        """Process HTML file (e.g., saved chat pages)"""
        soup = BeautifulSoup(content, 'lxml')
        
        conversations = []
        text_parts = []
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Try to find chat containers (common patterns)
        chat_containers = soup.find_all(['div', 'div'], class_=re.compile(r'(message|chat|msg|conversation)', re.I))
        
        if chat_containers:
            for container in chat_containers:
                text = container.get_text(strip=True, separator=' ')
                if text and len(text) > 5:
                    text_parts.append(text)
                    conversations.append({"text": text})
        else:
            # Fall back to paragraphs and list items
            for elem in soup.find_all(['p', 'li', 'div']):
                text = elem.get_text(strip=True, separator=' ')
                if text and len(text) > 10:
                    text_parts.append(text)
        
        # Also get plain text as backup
        plain_text = soup.get_text(separator='\n', strip=True)
        
        return {
            "success": True,
            "content": plain_text if plain_text else "\n".join(text_parts),
            "conversations": conversations,
            "format": "html"
        }
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        # Remove common artifacts
        text = re.sub(r'\[.*?\]', '', text)  # Remove bracketed text like [edited]
        
        return text.strip()
    
    def _parse_text_conversation(self, text: str) -> List[Dict]:
        """Try to parse conversation format from plain text"""
        conversations = []
        
        # Common patterns for chat messages
        patterns = [
            r'^(\d{1,2}[./]\d{1,2}[./]\d{2,4}.*?)$',  # Date at start
            r'^\[?(\d{1,2}:\d{2})\]?.*?:',  # Time at start
            r'^([^:]+):\s*(.+)$',  # Name: message format
            r'^<([^>]+)>\s*(.+)$',  # <Name> message format
        ]
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            for pattern in patterns:
                match = re.match(pattern, line)
                if match:
                    groups = match.groups()
                    if len(groups) >= 2:
                        conversations.append({
                            "sender": groups[0] if groups[0] else "Unknown",
                            "text": groups[1] if len(groups) > 1 else line,
                            "raw": line
                        })
                        break
            else:
                if conversations:
                    # Append to last message
                    conversations[-1]["text"] += f" {line}"
        
        return conversations


# Singleton instance
file_processor = FileProcessor()
