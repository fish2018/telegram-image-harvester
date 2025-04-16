from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.sessions import StringSession
from telethon import TelegramClient
import time

class TGForwarder:
    def __init__(self, api_id, api_hash, string_session, channels_groups_monitor, forward_to_channel, limit):
        self.api_id = api_id
        self.api_hash = api_hash
        self.string_session = string_session
        self.channels_groups_monitor = channels_groups_monitor
        self.forward_to_channel = forward_to_channel
        self.limit = limit
        self.client = TelegramClient(StringSession(string_session), api_id, api_hash)

    async def check_file_exists(self, file_name: str, target_channel) -> bool:
        """异步检查目标频道中是否已存在同名文件"""
        try:
            async for message in self.client.iter_messages(target_channel, search=file_name):
                if message.file and message.file.name == file_name:
                    return True
            return False
        except Exception as e:
            print(f"搜索文件失败: {e}")
            return False

    async def forward_zip(self, message, target_chat):
        """下载单张图片或即时预览中的图片"""
        ok = False
        compressed_types = {
            'application/zip': '.zip',
            'application/x-rar-compressed': '.rar',
            'application/vnd.rar': '.rar',
            'application/x-7z-compressed': '.7z',
            'application/octet-stream': '.zip.001'
        }
        mime_type = getattr(message.document, 'mime_type', None) if message.document else None
        file_name = message.file.name

        is_compressed = (mime_type in compressed_types) or (file_name and any(file_name.lower().endswith(ext) for ext in compressed_types.values()))

        if is_compressed:
            is_exists = await self.check_file_exists(message.file.name, self.forward_to_channel)
            if not is_exists:
                print(f'mime_type: {mime_type} file_name: {file_name} target: {self.forward_to_channel} exists: {is_exists}')
                await self.client.send_message(
                    target_chat,
                    message.text or '',
                    file=message.media,
                    silent=True
                )
                ok = True
        return ok

    async def copy_and_send_message(self, source_chat, target_chat, message_id, text=''):
        """复制消息内容并发送新消息"""
        try:
            message = await self.client.get_messages(source_chat, ids=message_id)
            if not message:
                print("未找到消息")
                return
            await self.client.send_message(
                target_chat,
                text,
                file=message.media
            )
        except Exception as e:
            print(f"操作失败: {e}")

    async def forward_messages(self, chat_name, limit):
        print(f'当前监控频道【{chat_name}】最近{limit}条消息')
        n = 0
        try:
            chat = None
            if 'https://t.me/' in chat_name:
                invite_hash = chat_name.split("/")[-1].lstrip("+")
                try:
                    invite = await self.client(CheckChatInviteRequest(invite_hash))
                    chat = invite.chat
                except Exception as e:
                    print(f"检查邀请链接失败: {e}")
            else:
                chat = await self.client.get_entity(chat_name)
            messages = self.client.iter_messages(chat, limit=limit, reverse=False)
            async for message in messages:
                if message.media:
                    ok = await self.forward_zip(message, self.forward_to_channel)
                    if ok:
                        n += 1
                    if message.replies and message.replies.comments:
                        async for reply in self.client.iter_messages(chat_name, reply_to=message.id):
                            if reply.media:
                                ok = await self.forward_zip(reply, self.forward_to_channel)
                                if ok:
                                    n += 1
            if n > 0:
                print(f"从 {chat_name} 成功转发{n}条资源")
        except Exception as e:
            print(f"从 {chat_name} 转发资源 失败: {e}")

    async def main(self):
        start_time = time.time()
        for chat_name in self.channels_groups_monitor:
            limit = self.limit
            if '|' in chat_name:
                limit = int(chat_name.split('|')[1])
                chat_name = chat_name.split('|')[0]
            try:
                await self.forward_messages(chat_name, limit)
            except Exception as e:
                continue
        await self.client.disconnect()
        end_time = time.time()
        print(f'耗时: {end_time - start_time} 秒')

    def run(self):
        with self.client.start():
            self.client.loop.run_until_complete(self.main())


if __name__ == '__main__':
    channels_groups_monitor = ["tttkid", "kid2333333", "xiucheduixa", "pusajie2", "pusajie"]
    forward_to_channel = 'sicangpinjian'
    limit = 20
    api_id = 6627460
    api_hash = '27a53a0965e486a2bc1b1fcde473b1c4'
    string_session = 'xxx'
    TGForwarder(api_id, api_hash, string_session, channels_groups_monitor, forward_to_channel, limit).run()
