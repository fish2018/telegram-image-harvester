# telegram-image-harvester
批量下载指定频道/群组中的图片，支持下载评论中、即时预览(telegraph)中的图片  

# 使用说明
- 使用时将string_session替换为自己的，可以从 https://tg.uu8.pro/ 获取  
- 安装依赖
  ```
  pip3 install telethon requests beautifulsoup4 urllib3
  ```
# 功能：
- 支持代理，不需要使用代理设置 `proxy = None` 即可
- 批量异步并发下载消息中的图片，`max_messages=None` 默认下载所有消息的，可以修改该值限制只下载最近max_messages条消息数
- 支持下载消息评论中的图片，在对应群组/频道后加上'|reply'即可开启支持，指定方式如：channel_list = ["XieZhen02|reply"]
- 支持多线程下载消息中"即时预览"里的图片，即时预览本质是telegraph
- 有些图片资源被打包为zip压缩包，工具仅保存相关信息到`zip_info.json`，不提供直接下载，因为自带的下载非常慢，推荐使第三方加速下载工具，比如TDL（https://docs.iyear.me/tdl/）

# 更新说明
- 消息分批处理下载图片，避免因群组消息过多(几十万)而需要先等待很久才开始下载
- 增加代理支持，不需要使用代理设置 `proxy = None` 即可
- 解决`FileReferenceExpiredError`异常，Telegram 的文件引用有一定的有效期，过期后自动重新获取
- `zip_info.json`增加文件大小的记录
