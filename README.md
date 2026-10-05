# KVMem 环完全修复版 · RTX 4070 Ti SUPER 16GB 跑 Qwen3.8-27B 的 256K 上下文

> 在 **RTX 4070 Ti SUPER (16GB)** 上，通过移植并**完全修复** KVMem 环补丁的三道硬门，
> 让 **MTP 投机解码与超池 host-backed 复用同时工作**，把 Qwen3.8-27B (GSQ-RCO IQ3_S)
> 的逻辑上下文拓到 **256K**（设备池仅 75,776 token，其余 KV 驻留宿主层）。
> 姊妹仓库 [ninfer-16g-4070tisuper-qwen3.8-27b-gsq-rco](https://github.com/encored2333/ninfer-16g-4070tisuper-qwen3.8-27b-gsq-rco)
> 是 119.5K 无损全量档的基础部署。

## 本仓库解决了什么

上游 KVMem 环补丁（见致谢）只做完了 host-backed 复用的"发布"半边——"采纳"侧被三道
只认内存状态的硬门堵死：MTP 检查点无法物化（`not materializable`）、宿主后备门漏扫
backend、retained 前缀超配额直接 500。本仓库的修复（见 `docs/patches/`）：

1. **MTP 采纳门**（`request_plan.cpp`）：backend 链在宿主层全链可恢复（每页 device 或
   host-current）即放行采纳；真不可恢复才降级重填
2. **宿主后备门**（`pressure.cpp`）：补 backend 页扫描（原版只扫 text）
3. **entitlement 门**（`request_plan.cpp`）：retained 前缀超活跃配额时优雅降级，不再 500

修复后 **MTP 满血（decode 76~120 tok/s，接受率 64%）+ 超池复用（141,355 token 题面
7.9 倍过池，100% response replay）同时工作**，且 agent 工具调用经 10 轮疲劳测试零畸形
（配套防呆模板见下）。

## 实测数据（RTX 4070 Ti SUPER 16GB）

| 项 | 值 |
|---|---|
| 逻辑上下文 | 262,144（模型原生上限）|
| KV 池 | 75,776 token（1,184 页，k8v4）· runtime 3.38 GiB · free 843 MiB |
| 常驻窗口 + 每轮检索 | 32,768 + 8,192 |
| 解码 | 76–120 tok/s（MTP 接受率随任务 52–91%）|
| 冷预填 | 129.5K ≈ 4~10 分钟（chunk 256，过池越深越慢）|
| **追问/重发** | **0.3~2 秒**（response replay 100%，141K 题面实测 7.9 倍过池采纳）|
| agent 工具调用 | 10 轮疲劳（含 45K 中段文档）零畸形 |

对比姊妹仓库的 119.5K 无损全量档：KVMem 换来 2.2 倍上下文与追问秒回，代价是
冷预填慢 3~7 倍（边写边分页搬家）+ 超窗近似可见性。两者按场景切换（bat 同端口互斥）。

## 快速开始

1. **引擎**：本仓库 [Release v1.0](../../releases/tag/v1.0) 下载 `engine-kvmem-fullfix.zip`
   （三门修复版 `ninfer-serve.exe` + 全套 DLL），解压即用
2. **模型**：按姊妹仓库的转换指南把 GSQ-RCO IQ3_S GGUF 转成 `.ninfer`（与显卡架构无关）
3. **启动**：`scripts/start_qwen3_8_27b_gsq_kvmem.bat`（改路径区三行），或手工：

```bat
set CUDA_VISIBLE_DEVICES=0
set NINFER_KV_WINDOW=32768
set NINFER_KV_RETRIEVE=8192
set NINFER_KV_RING=1
set NINFER_HOST_PAGEABLE=1
set NINFER_KV_REUSE_HOSTBACKED=1
ninfer-serve.exe <模型.ninfer> ^
  --model-id qwen3.8-27b --max-context 262144 ^
  --kv-capacity 75776 --kv-dtype k8v4 --host-kv-mib 12288 --prefill-chunk 256 ^
  --spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31 ^
  --max-shared-prefixes 0 --auto-long-anchors ^
  --temperature 0.7 --top-p 0.8 --top-k 20 --min-p 0 --presence-penalty 0 ^
  --chat-template chat_template_strict.jinja ^
  --port 8081
```

**五个环境变量是一组配置，缺一个会静默答错**；`--chat-template` 是防工具调用方言漂移的
防呆模板（长会话必须挂）；`--prefill-chunk` 必须 256（1024 会随机楔死）。

## Agent 客户端配置（dsh 等）

| 字段 | 值 | 说明 |
|---|---|---|
| Base URL | `http://127.0.0.1:8081/v1` | 鉴权关闭 |
| Model | `qwen3.8-27b` | |
| API Key | 任意非空 | 引擎不校验 |
| **max_tokens** | **≤ 24576** | 超池会触发降级重填（慢一轮，不失败）；曾因 40000 > 池触发过崩溃（已修复为降级，但别超）|
| reasoning 回传 | **不回传** `reasoning_content` | 主因级退化源（上游单变量实验）|
| 大文件写入 | 分轮，每轮 ≤12K | 思考 8K 预算 + 文件全文会顶满上限截坏收尾 |

完整行为边界表（什么时候慢、什么时候降级、崩溃处理纪律）见
[KVMem-完全修复与Agent调优.md](docs/KVMem-完全修复与Agent调优.md)。

## 仓库内容

```
├── docs/
│   ├── KVMem-完全修复与Agent调优.md   ← 主文档：三道门修复 / 引擎参数处方 / dsh 客户端配置表 / 行为边界
│   ├── 工具调用解析加固-A至G类问题与修复.md  ← 解析器加固：A–G 类畸形形态逐条修复 / 两个合同变更 / 新增诊断字段
│   ├── patches/                        ← 修复后完整源文件（request_plan.cpp / pressure.cpp / tool_call_parser.cpp / types.h / 日志与测试）
│   ├── 部署文档.md                     ← 基础参考（源码构建/依赖/踩坑 35 条，与姊妹仓库同源）
│   ├── 性能实测.md                     ← 引擎基线 bench（119.5K 全量档；KVMem 专项数据在主文档）
│   └── 模型转换指南.md                 ← GSQ-RCO GGUF → .ninfer 转换
├── scripts/
│   ├── start_qwen3_8_27b_gsq_kvmem.bat   生产启动脚本（最终参数，五环境变量+防呆模板）
│   ├── chat_template_strict.jinja        防工具调用方言漂移模板（--chat-template 挂载）
│   ├── build-sm89.bat / resume-sm89.bat  本仓库引擎的构建链（resume 防 OOM）
│   ├── fetch-asset.bat                   vcpkg 资产下载器（代理→镜像→直连）
│   └── kvmem-tests/                      全部验证脚本（修复验证/工具循环/疲劳测试/262K 档）
├── conversion/                         转换报告（脱敏）
└── LICENSE                             Apache-2.0
```
## 已知边界（诚实清单）

- **楔死纪律**：过池预填极低概率楔死（零错误行）。**严禁 taskkill 强杀**——实测会把
  4070 Ti SUPER 整卡拖下线（PnP Unknown），只能关机断电 30 秒冷启动。预防 = chunk 256
- 超窗内容是"窗口 + 内容检索"的**近似可见**：词法打分（重写版环无向量语义），词面不相交
  的提问可能漏召回——关键事实检索别指望 100%
- 思考预算 8,192 是工具轮最优（12,288 偶发畸形、16,384 数学不可行）；深思考任务用姊妹
  仓库全量档（可放 32K）
- 双实例不能同时跑（16GB 显存装不下两份权重），bat 互斥切换

## 致谢与来源（按依赖链）

| 组件 | 来源 | 许可 |
|---|---|---|
| NInfer 引擎基座 | [Neroued/ninfer](https://github.com/Neroued/ninfer) · 汇总线 [iamwavecut/ninfer-all](https://github.com/iamwavecut/ninfer-all) · 16GB 分支 [Ryan-gsq/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco](https://github.com/Ryan-gsq/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco)（姊妹仓库同源） | Apache-2.0 |
| **KVMem 环补丁 + 复现白皮书 + 防治文档**（本仓库的直接基座） | **[shensanshu/ninfer-master-shensanshu-kvmem](https://modelscope.cn/models/shensanshu/ninfer-master-shensanshu-kvmem)**（ModelScope）：34 文件补丁、《复现白皮书》《卡死与循环的防治》等全套文档 | Apache-2.0 |
| KVMem 环算法实现 | [tancau/ninfer-kvmem-ring](https://github.com/tancau/ninfer-kvmem-ring)（已并入上述补丁） | Apache-2.0 |
| KVMem 算法语义（常驻窗口/检索预算/差量计划） | [kvmem-qw3](https://github.com/kvmem-qw3)（作者 Di Chai；仅沿用公开语义，未含其源码） | Apache-2.0 |
| 本仓库独有 | 三道硬门修复（MTP 采纳/宿主后备门/entitlement）、防呆模板、agent 参数处方、16GB 卡全链验证 | Apache-2.0 |
| 模型与量化 | Qwen3.8-27B（阿里 Qwen 团队）· GSQ-RCO 量化：ISTA-DASLab | Apache-2.0 |

所有改动与实测数据基于各上游的 Apache-2.0 授权合规再分发；模型权重不在本仓库，
版权归各自作者。
