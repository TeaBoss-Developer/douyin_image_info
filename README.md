# douyin_image_info

通过抖音网页版解析图集（图文帖）无水印原图

> 基于与 douyin_vedio_info 相同的异步详情 API 机制，专门面向图集（aweme_type=68）。
> 抖音 PC 版 SSR 数据中的帖子内容已置空，必须通过异步 API 获取。

## 重要：先配置 Cookie

抖音对未登录/无有效 Cookie 的请求返回 JSVM 验证页或空数据，**必须配置有效 Cookie**。

1. 用 Chrome/Edge 登录 https://www.douyin.com
2. F12 → Network → 刷新 → 点任意 www.douyin.com 请求 → Headers
3. 复制 `Cookie:` 值，粘贴到 `config.json` 的 `"cookie"` 字段

> Cookie 含登录凭证，**不要**提交到公开仓库（config.json 已在 .gitignore 中）。

## 安装依赖

```bash
pip install requests
```

## 快速使用

```bash
python DouyinImage.py "4.12 :9pm 07/30 X@z.tE ytr:/ 请告诉我玩的这么菜菜的秘诀唷♡... https://v.douyin.com/5AiJ5pPHdJE/"
python DouyinImage.py 7684539877870924495     # 或直接传帖子 ID
```

或作为库引入：

```python
import DouyinImage

info = DouyinImage.get_image_info("分享文案...")
info = DouyinImage.get_image_info_by_id("7684539877870924495")
```

返回 dict 字段：

| 字段 | 说明 |
| --- | --- |
| title | 图集标题/描述 |
| note_id | 帖子 ID |
| author | 作者昵称 |
| user_id | 作者用户 ID |
| image_count | 图片数量 |
| images | 无水印原图列表（url/download_url/width/height） |
| bg_music | 背景音乐地址 |
| create_time | 发布时间（Unix 时间戳） |
| like_count / share_count / love_count / comment_count | 点赞/分享/收藏/评论数 |

## 工作原理

1. 分享文案 → 正则提取 URL（`v.douyin.com` 短链自动跟随重定向）
2. URL → 帖子 ID（识别 `/note/{id}` 或 `/video/{id}`）
3. 帖子 ID → 异步详情 API `/aweme/v1/web/aweme/detail/?aweme_id={id}`
4. 提取 `aweme_detail.images[].url_list[0]`（无水印原图直链）

> `images[].download_url_list` 是带水印版本，默认返回 `url_list`（无水印）。

## 健壮性说明

- **Cookie 配置化**：不硬编码在代码里
- **风控识别**：JSVM 验证页 / API status_code 异常时给出明确报错
- **非图集检测**：帖子无 images 字段时明确提示（aweme_type）
- **字段容错**：全部 `.get()` 安全取值，缺字段返回空值不崩溃
- **短链支持**：`v.douyin.com` 短链自动解析

## 免责声明

本程序仅用于学习和交流，一切有关抖音的商业用途与开发者无关。
