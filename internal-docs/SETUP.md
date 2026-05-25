# AI Radar — Setup Guide

**Discord 已经 wire 好用现有的 #cc-workspace 频道 (`1484904539952775351`)，不需要建新频道也不需要 webhook。** 只剩下一步必做、邮件可选。

---

## ⚡ 必做：装 cron（30 秒）

```bash
cp ~/ai-radar/scripts/launchd/com.clawii.airadar.daily.plist ~/Library/LaunchAgents/
cp ~/ai-radar/scripts/launchd/com.clawii.airadar.weekly.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.clawii.airadar.daily.plist
launchctl load ~/Library/LaunchAgents/com.clawii.airadar.weekly.plist

# 验证
launchctl list | grep airadar
```

应该看到两条：
- `com.clawii.airadar.daily`
- `com.clawii.airadar.weekly`

完事。明天 07:07 AM 第一条自动到 #cc-workspace，周日 08:00 出周报。

---

## 🧪 可选：先手动跑一次验证

```bash
~/ai-radar/scripts/run_daily.sh
```

会立刻拉今天的数据 + 推到 #cc-workspace。Mac 别睡，等 1-3 分钟。

---

## 📧 可选：加邮件抄送（Phase 2，5 分钟）

Discord 已经够用。如果你想加邮件备份：

1. Gmail App Password: https://myaccount.google.com/apppasswords → Select app: Other → "AI Radar" → 复制 16 位密码
2. 写配置：
   ```bash
   cp ~/ai-radar/.config.env.example ~/ai-radar/.config.env
   chmod 600 ~/ai-radar/.config.env
   # 编辑 .config.env，只需要填 AIRADAR_EMAIL_FROM 和 AIRADAR_GMAIL_APP_PASSWORD
   ```
3. 下次 cron 跑时自动加邮件。Discord 这边不受影响。

---

## 🔧 控制台

### 看今天的输出

```bash
cat ~/ai-radar/output/$(date +%Y-%m-%d).md
```

### 看 cron 日志

```bash
tail -20 ~/ai-radar/logs/daily-$(date +%Y-%m-%d).log
tail -20 ~/ai-radar/logs/launchd-daily-stderr.log
```

### 临时暂停

```bash
launchctl unload ~/Library/LaunchAgents/com.clawii.airadar.daily.plist
# 重启
launchctl load ~/Library/LaunchAgents/com.clawii.airadar.daily.plist
```

### 改时间 / 改频道 / 改 prompt

- 改时间：编辑 `~/ai-radar/scripts/launchd/com.clawii.airadar.daily.plist` 里的 `Hour` / `Minute`，然后 unload + load
- 改 Discord 频道：编辑 `~/ai-radar/prompts/digest.md` 里的 `chat_id` 那一行（同时改 `weekly_digest.md`）
- 改内容格式：直接编辑 `~/ai-radar/prompts/digest.md`，下次自动生效

---

## ❓ Troubleshooting

**Cron 没跑：**
- Mac 在 07:07 时是不是睡了？launchd 睡眠时不触发，下次唤醒会补跑（如果在 launchd 队列里）。
- 检查：`launchctl list com.clawii.airadar.daily` — 看 `LastExitStatus`。

**Discord 没收到：**
- 检查日志：`cat ~/ai-radar/logs/daily-$(date +%Y-%m-%d).log` — 找 "Discord push" 字样
- 频道 ID 对不对：现在是 `1484904539952775351` (cc-workspace)。要改去 prompt 里改。
- Claude Code 的 Discord MCP 是否还活着：手动跑 `~/ai-radar/scripts/test_digest.sh` 看输出。

**输出没生成：**
- 大概率是 WebFetch 被网站挡了或网络问题。日志里会有报错。
- 重跑：`~/ai-radar/scripts/run_daily.sh`

---

## 🎚️ 调优（2 周后再看）

跑 2 周后回来 `~/ai-radar/docs/calibration.md`（先创建），记录：
- 哪些 🚨 你实际打开了？
- 哪些你觉得"早就知道了"？→ 紧 threshold
- 哪些你"卧槽怎么没告诉我"？→ 松 threshold 或加源
- Red Note 上有没有出现 1 周内还没被 AI Radar 提到的真信号？

根据反馈直接改 `prompts/digest.md` 里的 signal rules。
