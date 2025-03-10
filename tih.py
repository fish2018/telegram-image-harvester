import json
from telethon import TelegramClient
from telethon.sessions import StringSession
import os
import asyncio
import logging
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import urllib3
import time
import socks
from telethon.errors import FileReferenceExpiredError, FloodWaitError

# 禁用 InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class TelegramImageDownloader:
    def __init__(self, api_id, api_hash, channel_list, download_directory, max_messages=None, proxy=None, batch_size=1000, max_concurrent_tasks=10, request_delay=0.01, only_zip=False):
        self.only_zip = only_zip
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel_list = channel_list
        self.download_directory = download_directory
        self.max_messages = max_messages
        self.batch_size = batch_size  # 每批次处理的消息数量
        self.max_concurrent_tasks = max_concurrent_tasks  # 最大并发任务数量
        self.request_delay = request_delay  # 请求间隔（秒）
        self.zip_info_file = os.path.join(download_directory, "zip_info.json")  # ZIP 文件信息保存路径

        # 创建 Telegram 客户端
        if not proxy:
            self.client = TelegramClient(StringSession(string_session), api_id, api_hash)
        else:
            self.client = TelegramClient(StringSession(string_session), api_id, api_hash, proxy=proxy)

        # 确保保存目录存在
        if not os.path.exists(self.download_directory):
            os.makedirs(self.download_directory)

        # 初始化 ZIP 信息文件
        if not os.path.exists(self.zip_info_file):
            with open(self.zip_info_file, "w", encoding="utf-8") as f:
                json.dump([], f)  # 初始化为空列表

    async def download_media(self, message, channel):
        """下载单张图片或即时预览中的图片"""
        # 检查是否是 ZIP 文件
        # if message.document and message.document.mime_type == 'application/zip':
        # 定义支持的压缩文件类型
        compressed_types = {
            'application/zip': '.zip',
            'application/x-rar-compressed': '.rar',
            'application/x-7z-compressed': '.7z'
        }
        mime_type = getattr(message.document, 'mime_type', None)
        file_name = getattr(message.document, 'file_name', None)

        # 判断是否为压缩文件：基于 mime_type 或文件扩展名
        is_compressed = (mime_type in compressed_types) or \
                        (file_name and any(file_name.lower().endswith(ext) for ext in compressed_types.values()))

        if is_compressed:
            await self.record_zip_info(message, channel)
            return  # 跳过 ZIP 文件的下载

        if not self.only_zip:
            if message.photo or (message.document and message.document.mime_type in ['image/jpeg', 'image/png', 'image/gif']):
                await self.download_file_with_retry(message, channel)

            if hasattr(message.media, 'webpage'):
                url = message.media.webpage.url
                if 'https://telegra.ph/' in url:
                    await self.download_webpage_photos(url, channel)

    async def record_zip_info(self, message, channel):
        """记录 ZIP 文件的信息到 JSON 文件"""
        zip_info = {
            "message_link": f"https://t.me/{channel}/{message.id}",  # 消息链接
            "text": message.text or "",  # 消息文本内容
            "file_name": message.file.name,
            "file_size": message.document.size,  # 文件大小（字节）
            "channel": channel,  # 频道名称
            "message_id": message.id  # 消息 ID
        }

        # 读取现有的 ZIP 信息
        with open(self.zip_info_file, "r", encoding="utf-8") as f:
            existing_info = json.load(f)

        # 添加新的 ZIP 信息
        existing_info.append(zip_info)

        # 写回文件
        with open(self.zip_info_file, "w", encoding="utf-8") as f:
            json.dump(existing_info, f, ensure_ascii=False, indent=4)

        logger.info(f"Recorded ZIP file info: {zip_info}")

    async def download_file_with_retry(self, message, channel, retries=3):
        """下载单个文件（图片），并处理 FileReferenceExpiredError"""
        for attempt in range(retries):
            try:
                await self.download_file(message, channel)
                break  # 成功下载后退出循环
            except FileReferenceExpiredError:
                logger.warning(f"File reference expired for message {message.id}, retrying {attempt + 1}/{retries}...")
                if attempt == retries - 1:
                    logger.error(f"Failed to download message {message.id} after {retries} attempts.")
            except FloodWaitError as e:
                logger.warning(f"FloodWaitError: {e}, sleeping for {e.seconds} seconds...")
                await asyncio.sleep(e.seconds)  # 等待指定时间后重试
            except Exception as e:
                logger.error(f"Error downloading message {message.id}: {e}")
                break

    async def download_file(self, message, channel):
        """下载单个文件（图片）"""
        file_name = f"{message.id}.jpg"  # 这里可以根据需要更改文件名生成逻辑
        channel_directory = os.path.join(self.download_directory, channel.split('|')[0])
        if not os.path.exists(channel_directory):
            os.makedirs(channel_directory)

        file_path = os.path.join(channel_directory, file_name)

        if not os.path.exists(file_path):
            if message.photo:
                await message.download_media(file_path)  # 使用 Telethon 的下载功能
                logger.info(f"Downloaded {file_name} from {channel}")

    async def download_webpage_photos(self, url, channel):
        """下载网页中的所有图片"""
        logger.info(f"Fetching images from webpage: {url}")
        html = await self.fetch_webpage(url)
        if html:
            image_links = self.extract_image_links(html)
            if image_links:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    executor.map(lambda img_url: self.download_image(img_url, channel), image_links)
            else:
                logger.warning("未找到任何图片链接。")
        else:
            logger.error("网页源码获取失败。")

    async def fetch_webpage(self, url):
        """异步获取网页源码"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        try:
            response = requests.get(url, headers=headers, verify=False)
            response.raise_for_status()  # 检查请求是否成功
            return response.text
        except Exception as e:
            logger.error(f"获取网页源码失败: {e}")
            return None

    def extract_image_links(self, html):
        """从网页源码中提取图片链接"""
        soup = BeautifulSoup(html, 'html.parser')
        image_tags = soup.find_all('img')
        image_links = []
        for img in image_tags:
            src = img.get('src')
            if src.startswith('/file/'):
                src = f"https://telegra.ph{src}"
            image_links.append(src)

        return image_links

    def download_image(self, img_url, channel):
        """下载单个图片"""
        image_name = os.path.basename(img_url)
        channel_directory = os.path.join(self.download_directory, channel)
        if not os.path.exists(channel_directory):
            os.makedirs(channel_directory)

        file_path = os.path.join(channel_directory, image_name)

        if os.path.exists(file_path):
            logger.info(f"已下载: {image_name}，跳过。")
            return

        # 重试机制
        for attempt in range(3):  # 最大重试次数
            try:
                response = requests.get(img_url, verify=False)  # 设置 verify=False 以跳过 SSL 验证
                if response.status_code in [404,403]:  # 如果返回 404,403，直接跳过
                    # logger.warning(f"图片不存在或无权限下载: {image_name}，跳过。")
                    return
                response.raise_for_status()  # 检查请求是否成功
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                logger.info(f"下载完成: {image_name} from {channel}")
                return  # 成功后返回
            except requests.exceptions.HTTPError as e:
                if e.response.status_code in [404,403]:  # 如果返回 404,403，直接跳过
                    # logger.warning(f"图片不存在或无权限下载: {image_name}，跳过。")
                    return
                logger.error(f"下载失败: {image_name}，错误: {e}，正在重试 {attempt + 1}/3...")
                time.sleep(2)  # 等待一段时间后重试
            except Exception as e:
                logger.error(f"下载失败: {image_name}，错误: {e}，正在重试 {attempt + 1}/3...")
                time.sleep(2)  # 等待一段时间后重试

        logger.error(f"下载失败: {image_name}，已达最大重试次数。")

    async def download_comments(self, message, channel):
        """下载评论中的图片"""
        if message.replies and message.replies.comments:
            logger.info(f"Processing comments for message {message.id} in channel {channel}")
            async for reply in self.client.iter_messages(channel, reply_to=message.id):
                await self.download_media(reply, channel)

    async def process_batch(self, channel, offset_id=0):
        """处理一批消息"""
        semaphore = asyncio.Semaphore(self.max_concurrent_tasks)  # 限制并发任务数量

        async def limited_download_media(message):
            async with semaphore:
                await self.download_media(message, channel)
                await asyncio.sleep(self.request_delay)  # 增加请求间隔

        tasks = []
        async for message in self.client.iter_messages(channel, limit=self.batch_size, offset_id=offset_id):
            tasks.append(limited_download_media(message))
        await asyncio.gather(*tasks)
        logger.info(f"Finished processing batch for channel {channel} with offset_id {offset_id}")

    async def download_images(self):
        """分批异步下载图片"""
        for channel in self.channel_list:
            reply = False
            if 'reply' in channel:
                channel = channel.split('|')[0]
                reply = True
            logger.info(f"Processing channel: {channel}")

            offset_id = 0
            last_offset_id = None
            same_offset_count = 0  # 记录连续处理相同 offset_id 的次数

            while True:
                # 处理当前批次
                await self.process_batch(channel, offset_id)

                # 更新 offset_id 为当前批次最后一条消息的 ID
                async for message in self.client.iter_messages(channel, limit=1, offset_id=offset_id + self.batch_size):
                    offset_id = message.id

                # 如果没有更多消息，退出循环
                if offset_id == 0:
                    break

                # 检测是否连续处理相同的 offset_id
                if offset_id == last_offset_id:
                    same_offset_count += 1
                    if same_offset_count >= 3:  # 如果连续 3 次处理相同的 offset_id，停止程序
                        logger.error(f"连续 3 次处理相同的 offset_id: {offset_id}，可能无法继续下载。停止处理频道: {channel}")
                        break
                else:
                    same_offset_count = 0  # 重置计数器

                last_offset_id = offset_id  # 更新 last_offset_id

        logger.info("所有图片下载完成。")

    def run(self):
        """运行下载"""
        with self.client.start():
            self.client.loop.run_until_complete(self.download_images())


# 使用示例
if __name__ == "__main__":
    # 替换为你的 API ID 和 Hash
    api_id = 6627460
    api_hash = '27a53a0965e486a2bc1b1fcde473b1c4'
    string_session = 'xxx'

    # 下载路径
    download_directory = 'imgs'
    # 替换为你要下载图片的频道/群组列表
    channel_list = []
    # 代理 不用代理设置proxy=None
    proxy = (socks.SOCKS5, '127.0.0.1', 7897)
    # 创建下载器实例并运行
    downloader = TelegramImageDownloader(api_id, api_hash, channel_list, download_directory, max_messages=None, proxy=proxy, batch_size=1000, max_concurrent_tasks=10, request_delay=0.01, only_zip=False)
    downloader.run()
