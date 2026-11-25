# BotBuddy 为什么用 `only_voice` 接管语音

做 T1 点歌台时，我们以为订阅原厂的语音识别结果就够了。用户说“播放周杰伦的歌”，点歌台拿到了文字，原厂 Agent 也听到了同一句话，自己先唱了起来。轮到点歌台播放时，扬声器已经被占用。我们希望用户仍能像平时一样唤醒机器人，但接下来这句点歌指令只交给点歌台。

## 先试过停掉原厂 Agent

早期 T1 上可以在运行 Agent 的运控板（SoC 0）调用进程管理器。下面分别是当时所用 HTTP 接口的停止和恢复命令。复刻后面的 BotBuddy 流程可以直接跳到启动部分，初始状态应是 Agent 正在运行。

```bash
# 停止 agent
yamo em stop-app agent

# 重新启动 agent
yamo em start-app agent
```

停掉以后，原厂不再抢答。可我们原本想复用的 `/aima/agent/asr_result` 的原厂发布者和原厂 `PlayTts` 服务也一起消失了。现场还有个直接影响使用的问题：机器人走路、被人拖动时，动作都显得僵硬。我们记录的是停 Agent 时观察到的现象，具体哪条运动控制链路受影响，当时没有定位。

我们也试过直接采原始音频。机器人问“你想听什么歌”，人已经回答，程序却迟迟没有向 ASR 发请求。背景声一直被当作人声，分句程序等不到一句话结束。走这条路，除了识别和合成，还得自己解决唤醒、回声和断句。

## 再试 `only_asr`，原厂还是会答

`only_asr` 是我们在示例里找到的运行模式。设想是让原厂完成语音转文字，点歌台拿到文字以后自己处理。T1 上能拿到识别结果，原厂仍会回答或唱歌。后来在一台 Q1 探索版（固件尾号 `.45.18`）又测了两轮：第一轮设置后读回 `only_asr`，第二轮又单独重启了 Agent，确认新进程加载了这个值。两次都看到了测试句的最终识别结果和对应的原厂播报，现场两次都听到了回答。

我们接着试了 `only_voice`，从原厂取处理后的**音频**，自己做识别。在 T1 的 `only_voice` 实测中，说“元仔元仔”还能听到“我在”，再说业务测试句，原厂输出了带起止标记的语音片段，现场没有再听到原厂回答。一次点歌测试收齐了 2.784 秒音频，自有 ASR 识别出“我想听周杰伦的晴天”，后续理解和播报也走通了。这就是 BotBuddy 选择 `only_voice` 的原因。

## 怎么启动，`start` 到底做了什么

在**安装 BotBuddy 的那块板**上运行。首次使用先按安装向导配好语音服务连接和千问的 ASR、LLM、TTS。双板部署时，BotBuddy 通常运行在大脑板（SoC 1），由它连接 SoC 0 管理 Agent。[安装与模型配置](installation.md)

```bash
botbuddy onboard    # 已经配置好的机器跳过这一行
botbuddy start
```

`start` 在前台运行。它先检查语音接口并取得会话锁，随后按下面的顺序切换原厂 Agent。想把这套流程移植到自己的程序，可以直接对照[模式切换与恢复](../src/botbuddy/integrations/primebot/native_agent.py)和[模式 RPC 实现](../src/botbuddy/integrations/primebot/agent_mode_rpc.py)。

1. **记下原模式。** 向 `/aimdk_5Fmsgs/srv/GetAgentPropertiesRequest` 查询 `property_ids=[{value: 2}]`。`2` 是 `AGENT_PROPERTY_RUN_MODE`。BotBuddy 把返回的模式、目标设备和管理方式写进运行目录里的 `agent_mode.json`，退出时按它恢复。
2. **写入 `only_voice`。** 调用 `/aimdk_5Fmsgs/srv/SetAgentPropertiesRequest`，请求里填 `contents.properties=[{key: {value: 2}, value: 'only_voice'}]`，再用 Get 读回。写请求超时时也先读回核对。下面是这一步的独立调用方式，供移植时对照。已在运行 `botbuddy start` 的读者只需要使用无参数的查询命令。

   ```bash
   # 在有 BotBuddy 源码的 SoC 0 上，从源码根目录打开 Bash
   source ./scripts/robot_env.sh
   rpc=src/botbuddy/integrations/primebot/agent_mode_rpc.py
   python3 "$rpc"               # 查询并记下原模式，常见输出含 "mode": "normal"
   python3 "$rpc" only_voice    # 设置并读回，预期 "mode": "only_voice"
   ```

3. **让新进程加载模式。** 有 `yamo` 时，BotBuddy 执行 `yamo em stop-app agent`，从本机 `GET /json/get_all_apps_info` 确认 `agent` 已到 `Idel(-1)`，再执行 `yamo em start-app agent` 并等到 `Running` 和有效 PID。缺少 `yamo` 时才使用前面的 HTTP 停启接口。这次停启是为了让 Agent 按新模式运行。进入语音会话后，它要继续提供唤醒与音频。
4. **确认后才收音。** BotBuddy 用新的 ROS 客户端再次读回 `only_voice`，并等到处理后音频和会话状态两个 topic 都有发布者。此时才会听到 BotBuddy 的启动提示。正常退出按 `Ctrl+C`，它会写回进入前的模式、重启 Agent 并读回确认。初始是 `normal` 的机器，退出后应恢复 `normal`。自己移植时，若手动执行了第 2 步，也要用同一脚本写回原值（例如 `python3 src/botbuddy/integrations/primebot/agent_mode_rpc.py normal`），按第 3 步重启，再不带参数查询。

## 一句话怎么从麦克风走到扬声器

先说机器人的原厂唤醒词，等它应答完，再说“播放周杰伦的晴天”。接下来可以跟着这句话看四段代码。

**收音和分句。** BotBuddy 订阅原厂的 `/aima/agent/interaction_state` 和 `/agent/process_audio_output`，订阅 QoS 为 BEST_EFFORT / VOLATILE。等待时读到 `main_state.value=1`（LISTENING），它打开 30 秒收音窗口。从 `ProcessedAudioOutput` 取出 `stream_id=0` 的 `audio_data`，按 `audio_vad_state.value` 的 BEGIN(1)、PROCESSING(2)、END(3) 拼成一句。原厂应答进入 SPEAKING(3) 时，BotBuddy 会清掉手里的半句，避免把“我在”也认成指令。[收音回调](../src/botbuddy/integrations/primebot/native_voice.py)

**ASR 识别。** 收齐一句后，BotBuddy 关闭本轮收音，把 16 kHz、单声道 PCM16 封装成 WAV，交给配置的千问 ASR，这时才拿到“播放周杰伦的晴天”这段文字。缺开始帧的残句会丢弃，空识别也不会触发任务。[WAV 封装](../src/botbuddy/integrations/primebot/speech_audio.py) · [会话主循环](../src/botbuddy/voice/session.py)

**LLM 与技能。** BotBuddy 把识别文字和可用技能目录交给配置的 LLM。模型按需读点歌台的 `SKILL.md`，提出带歌手、歌名的任务。框架校验参数、执行技能，再把实际结果交回模型。如果用户只是在提问，模型也可以直接给文字回复。[规划器](../src/botbuddy/core/planner.py) · [执行器](../src/botbuddy/core/engine.py)

**TTS 与播放。** 需要说话时，BotBuddy 用配置的千问 TTS 把文字合成 WAV，已有相同提示音时复用缓存。它把文件准备到播放板，调用原厂 `PlayMediaFile`，并在 `/interaction/tts_status` 上用本次 `trace_id` 匹配开始和结束反馈。需要用户接话的提示播完后，回调才重新打开收音窗口。[提示音缓存](../src/botbuddy/voice/speech_cache.py) · [原厂媒体播放](../src/botbuddy/integrations/primebot/native_media.py)

播放整首歌时，BotBuddy 暂停接收新指令，听到原厂唤醒应答也不会取消点歌。像成语接龙这样自己收答案的游戏，则由游戏进程在答题窗口订阅原厂音频，只有原厂处于 LISTENING 才收答案。LISTENING 也可能出现在播放结束后，BotBuddy 不把这次状态变化当作又说了唤醒词。进入主态 IDLE 后，要再次唤醒、等应答结束再答。宿主等游戏退出并确认资源释放后才接回下一句。[独占技能协议](skill-protocol.md)

## 怎么让原来接 Agent 的程序继续用

有些已有程序只关心两件事：能不能订阅到识别文字，能不能传一段文字让机器人说出来。BotBuddy 为它们提供与原厂相同的 ROS 消息和服务类型。上面的音频、会话状态和媒体播放状态仍由原厂发布。BotBuddy 自己发布的 **topic 是识别结果**，另外提供一个 **service 接收播报请求**。[桥接实现](../src/botbuddy/integrations/primebot/sdk_bridge.py)

| `botbuddy start` 的参数 | ASR topic · `aimdk_msgs/msg/AsrResult` | TTS service · `aimdk_msgs/srv/PlayTts` |
| --- | --- | --- |
| 默认，或 `--sdk-bridge namespaced` | `/primebuddy/asr_result` | `/primebuddy/PlayTts` |
| `--sdk-bridge botbuddy` | `/botbuddy/asr_result` | `/botbuddy/PlayTts` |
| `--sdk-bridge native` | `/aima/agent/asr_result` | `/aimdk_5Fmsgs/srv/PlayTts` |
| `--sdk-bridge off` | 关闭发布 | 关闭服务 |

默认沿用 `/primebuddy` 是为了兼容更名前的客户端。`only_voice` 下原厂仍可能占着原名。`native` 模式检测到其他 ASR 发布者或同名 TTS 服务端时会报冲突。发布识别结果时，桥接层给每句非空文本填入新的 `event_id`、发布时间、递增的 `header.sequence` 和 `is_final=true`，以 RELIABLE / VOLATILE 发布，后加入的订阅者从下一句开始收。

已有客户端若支持 ROS 参数，可以保留默认桥接，在**客户端**启动时加 `--ros-args -r /aima/agent/asr_result:=/primebuddy/asr_result -r /aimdk_5Fmsgs/srv/PlayTts:=/primebuddy/PlayTts`。[ROS 2 名称重映射](https://docs.ros.org/en/humble/How-To-Guides/Migrating-from-ROS1/Migrating-Scripts.html)

### 在机器人上复刻一轮

1. 保持第一个终端的 `botbuddy start` 运行，使用默认桥接。第二个 Bash 终端进入 BotBuddy 安装目录或源码根目录，加载这台机器的 ROS 环境，再检查接口。

   ```bash
   source ./scripts/robot_env.sh
   ros2 topic info /agent/process_audio_output --verbose
   ros2 topic info /aima/agent/interaction_state --verbose
   ros2 service type /primebuddy/PlayTts
   ros2 topic echo /primebuddy/asr_result --once
   ```

2. 前两项应能看到原厂发布者，服务类型应为 `aimdk_msgs/srv/PlayTts`。最后一条会等待下一句话。说原厂唤醒词，等应答结束，再问“一加一等于几”。第二个终端应收到一条 `is_final: true`、`text` 与测试句相符、带新 `event_id` 的消息。这个消息在 BotBuddy 调用 LLM 前发布。随后听业务回答，可以分辨是识别已经成功、还是后续理解或播放出了问题。
3. 等 BotBuddy 播完、空闲时，在第二个终端单独测试兼容播报服务。

   ```bash
   ros2 service call /primebuddy/PlayTts aimdk_msgs/srv/PlayTts \
     "{tts_req: {text: '播报测试', domain: 'demo', trace_id: 'demo-tts-1', priority_level: {value: 6}, priority_weight: 0, is_interrupted: false}}"
   ```

   `tts_resp.is_success=true` 表示请求已接收。主循环随后合成并播放，听到“播报测试”才能确认这一轮出声。桥接只接受 1～100 字、非空 `domain`、优先级 6、权重 0 的请求。正在处理另一句话或播音时会拒绝。
4. 在第一个终端按 `Ctrl+C`。等看到“原厂 Agent 已恢复模式”及实际模式名，再用原厂唤醒词问一句，确认日常对话恢复。需要定位中间哪一步没走到时，在默认日志 `/var/log/botbuddy/botbuddy.log` 里按顺序找 `SDK_BRIDGE`、`VOICE_WINDOW_OPEN`、`ASR`、`TTS`，以及退出时的 `RESTORE_CONFIRMED`。

[返回文档目录](README.md) · [版本与实机验收记录](release-validation.md)
