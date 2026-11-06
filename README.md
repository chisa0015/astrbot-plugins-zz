# AstrBot 插件集 · 夜煞

自建的 5 个 AstrBot 插件，全部用 `astrbot_plugin_zz_` 前缀（`zz` = 夜煞）。

| 插件 | 版本 | 功能 |
|---|---|---|
| [`astrbot_plugin_zz_cosplay`](astrbot_plugin_zz_cosplay) | 1.1.0 | 随机 cos 图（cosplay8 图集 / 绅士会所 r18） |
| [`astrbot_plugin_zz_fortune`](astrbot_plugin_zz_fortune) | 1.0.0 | 今日运势卡片：随机壁纸 + 吉凶 + 五项指数 + 宜忌 + 幸运元素 |
| [`astrbot_plugin_zz_hanime`](astrbot_plugin_zz_hanime) | 1.0.0 | hanime1.me 随机推荐 / 最新上市 / 每日推送 |
| [`astrbot_plugin_zz_jm`](astrbot_plugin_zz_jm) | v1.0.0 | JM 漫画下载并转成 PDF 发送 |
| [`astrbot_plugin_zz_novel`](astrbot_plugin_zz_novel) | 2.0.0 | 从轻之文库 / 文库8 抽一本书，抓若干章正文排版成 PDF 发文件 |

---

## 安装

### 方式一：全部装

```powershell
# 把仓库 clone 下来，然后把 astrbot_plugin_* 目录拷到 AstrBot 的 data\plugins\
git clone https://github.com/chisa0015/astrbot-plugins-zz.git
copy astrbot-plugins-zz\astrbot_plugin_*  <AstrBot>\data\plugins\ -Recurse
```

### 方式二：只装一个

```
astrbot_plugin_zz_cosplay\  ->  <AstrBot>\data\plugins\astrbot_plugin_zz_cosplay\
```

装完**重启 AstrBot**。

---

## 插件详解

### astrbot_plugin_zz_cosplay

版本：`1.1.0`

随机 cos 图（cosplay8 图集 / 绅士会所 r18）

配置文件：`astrbot_plugin_zz_cosplay/_conf_schema.json` → 装好后在 AstrBot 面板里改

---

### astrbot_plugin_zz_fortune

版本：`1.0.0`

今日运势卡片：随机壁纸 + 吉凶 + 五项指数 + 宜忌 + 幸运元素

配置文件：`astrbot_plugin_zz_fortune/_conf_schema.json` → 装好后在 AstrBot 面板里改

---

### astrbot_plugin_zz_hanime

版本：`1.0.0`

hanime1.me 随机推荐 / 最新上市 / 每日推送

配置文件：`astrbot_plugin_zz_hanime/_conf_schema.json` → 装好后在 AstrBot 面板里改

---

### astrbot_plugin_zz_jm

版本：`v1.0.0`

JM 漫画下载并转成 PDF 发送

配置文件：`astrbot_plugin_zz_jm/_conf_schema.json` → 装好后在 AstrBot 面板里改

---

### astrbot_plugin_zz_novel

版本：`2.0.0`

从轻之文库 / 文库8 抽一本书，抓若干章正文排版成 PDF 发文件

配置文件：`astrbot_plugin_zz_novel/_conf_schema.json` → 装好后在 AstrBot 面板里改

---

## 依赖说明

| 插件 | 外部依赖 |
|---|---|
| `zz_cosplay` | 需要能访问 `cosplay8`（可能需要代理） |
| `zz_fortune` | Pillow、`lbpcascade_animeface.xml`（已内置）|
| `zz_hanime` | 需要能访问对应站点 |
| `zz_jm` | JM 站点访问、PDF 生成库 |
| `zz_novel` | 需要能访问 linovel 等小说源 |

代理默认 `127.0.0.1:7890`，各插件配置里可改。

---

## License

MIT（这几个插件是自建的，可以随意改）
