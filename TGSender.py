import json
import os
import logging
import asyncio
import random
from typing import List, Dict
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import RPCError

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramMessageSender:
    def __init__(self, api_id: int, api_hash: str, string_session: str, json_path: str, target_channel: str, proxy=None):
        if not proxy:
            self.client = TelegramClient(StringSession(string_session), api_id, api_hash)
        else:
            self.client = TelegramClient(StringSession(string_session), api_id, api_hash, proxy=proxy)
        self.json_path = json_path
        self.target_channel = target_channel
        self.batch_size = 20

    async def load_json_data(self) -> Dict:
        """异步读取JSON文件，返回包含消息列表和元数据的字典"""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 确保数据结构包含 messages 和 metadata
                if not isinstance(data, dict):
                    return {"messages": data, "metadata": {"last_sent_index": -1}}
                if "messages" not in data:
                    data["messages"] = data.get("messages", [])
                if "metadata" not in data:
                    data["metadata"] = {"last_sent_index": -1}
                return data
        except FileNotFoundError:
            logger.error(f"JSON文件未找到: {self.json_path}")
            return {"messages": [], "metadata": {"last_sent_index": -1}}
        except json.JSONDecodeError:
            logger.error(f"JSON文件格式错误: {self.json_path}")
            return {"messages": [], "metadata": {"last_sent_index": -1}}

    async def save_json_data(self, data: Dict):
        """异步保存JSON文件"""
        try:
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存JSON失败: {e}")

    async def get_sent_index(self, data: Dict) -> int:
        """获取已发送的索引"""
        return data["metadata"].get("last_sent_index", -1)

    async def check_existing_messages(self) -> set:
        """异步检查目标频道最近500条消息的文本内容"""
        existing_texts = set()
        try:
            async for message in self.client.iter_messages(self.target_channel, limit=500):
                if message.text:
                    existing_texts.add(message.text)
        except RPCError as e:
            logger.error(f"检查历史消息失败: {e}")
        return existing_texts

    async def copy_and_send_messages(self, source_chat: str, message_ids: List[int], target_chat: str, existing_texts: set):
        """异步批量复制并发送消息"""
        try:
            message_link = f"https://t.me/{source_chat}/{message_ids[0] if len(message_ids) == 1 else f'{message_ids[0]}_etc'}"
            logger.info(f"尝试获取消息: {message_link}")
            messages = await self.client.get_messages(source_chat, ids=message_ids)
            if not messages or not isinstance(messages, list) or len(messages) == 0:
                logger.warning(f"未找到任何消息: {message_link}")
                try:
                    entity = await self.client.get_entity(source_chat)
                    logger.info(f"频道 {source_chat} 可访问，ID: {entity.id}")
                except Exception as e:
                    logger.error(f"无法访问频道 {source_chat}: {e}")
                return

            for message in messages:
                if message:  # 确保消息对象有效
                    message_link = f"https://t.me/{source_chat}/{message.id}"
                    if message.text in existing_texts:
                        logger.info(f"消息已存在，跳过: {message_link}")
                        continue
                    await self.client.send_message(
                        target_chat,
                        message.text or '',
                        file=message.media,
                        silent=True
                    )
                    logger.info(f"成功发送消息: {message.text[:50]}... from {message_link}")
                    await asyncio.sleep(random.uniform(0.5, 2.0))
                else:
                    logger.warning(f"消息为空: {message_link}")
        except RPCError as e:
            logger.error(f"发送消息失败 {message_link}: {e}")
        except Exception as e:
            logger.error(f"意外错误 {message_link}: {e}")

    async def process_batch(self, chat_message_map: Dict[str, List[int]], existing_texts: set, data: Dict):
        """并发处理每组消息"""
        tasks = []
        for channel, message_ids in chat_message_map.items():
            filtered_ids = [
                mid for mid in message_ids
                if next(d['text'] for d in data["messages"] if d['channel'] == channel and d['message_id'] == mid) not in existing_texts
            ]
            if filtered_ids:
                tasks.append(self.copy_and_send_messages(channel, filtered_ids, self.target_channel, existing_texts))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def send_batch_async(self):
        """异步发送一批消息"""
        # 读取JSON数据
        data = await self.load_json_data()
        messages = data["messages"]
        if not messages:
            logger.error("无数据可处理")
            return

        # 获取已发送索引
        sent_index = await self.get_sent_index(data)
        start_index = sent_index + 1
        end_index = min(start_index + self.batch_size, len(messages))

        # 按 chat 分组消息 ID
        chat_message_map = {}
        for i in range(start_index, end_index):
            item = messages[i]
            channel = item['channel']
            message_id = item['message_id']
            if channel not in chat_message_map:
                chat_message_map[channel] = []
            chat_message_map[channel].append(message_id)

        # 检查目标频道已有消息
        existing_texts = await self.check_existing_messages()

        # 处理消息
        await self.process_batch(chat_message_map, existing_texts, data)

        # 更新 last_sent_index
        processed_count = sum(len(ids) for ids in chat_message_map.values())
        current_index = start_index + processed_count - 1
        data["metadata"]["last_sent_index"] = current_index
        await self.save_json_data(data)

    def send_batch(self):
        """同步包装异步发送逻辑"""
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.send_batch_async())

    def run(self):
        """同步启动客户端并运行"""
        with self.client.start():
            self.send_batch()

if __name__ == '__main__':
    # 配置参数
    API_ID = 6627460
    API_HASH = "27a53a0965e486a2bc1b1fcde473b1c4"
    STRING_SESSION = "xxx"
    JSON_PATH = "zip_info.json"
    TARGET_CHANNEL = "sicangpinjian"
    PROXY = None

    # 创建发送器实例
    sender = TelegramMessageSender(API_ID, API_HASH, STRING_SESSION, JSON_PATH, TARGET_CHANNEL, PROXY)

    # 运行发送任务
    sender.run()
