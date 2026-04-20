# Framework 文件结构说明

## 概述

这是一个 **Go 语言量化套利框架**，用于在 BSC（币安智能链）上执行 DEX 套利策略。核心逻辑是：监听 CEX 交易所的链上交易信号，在 DEX（PancakeSwap / Uniswap）上执行套利交易。

**语言**: Go 1.25.0
**主要依赖**: go-ethereum, go-redis, go-sql-driver/mysql, gorilla/websocket, go-telegram-bot, maubot

---

## 根目录文件

| 文件 | 说明 |
|------|------|
| `main.go` | 入口文件。演示调用 `base.SelfExactInputSingle()` 进行 V4 池子报价计算 |
| `go.mod` / `go.sum` | Go 模块依赖声明 |
| `framework/` | 核心框架代码目录 |
| `init.go` | 框架初始化入口 `framework.Init(ChainID)`，启动各模块 goroutine |

---

## framework/ 子目录结构

```
framework/
├── init.go                    # 框架启动入口
├── go.mod / go.sum           # 子模块依赖
│
├── base/                     # 【核心】基础模块（配置、算法、属性定义、ABI调用）
│   ├── baseConfig.go         # 配置加载（JSON配置文件读取、ABI实例缓存）
│   ├── baseAttribute.go      # 全局变量定义（RPC连接、Redis、合约ABI实例、Token价格等）
│   ├── baseAlgorithm.go      # 核心算法（AMM数学公式：GetTokenAmount、GetStableAmount、QuoteExactInputSingle等）
│   ├── baseCall.go          # ETH RPC调用封装（CallMsg构建、多合约批量调用）
│   ├── baseFun.go           # 工具函数（地址判断、Hash计算、压缩解压等）
│   ├── baseAnalysisLog.go   # 日志分析
│   │
│   ├── baseAbi/             # 各 DEX 合约的 Go-ABI 绑定（自动生成）
│   │   ├── PancakeAbi.go          # PancakeSwap V2
│   │   ├── PancakeFactroyV3.go    # PancakeSwap V3 Factory
│   │   ├── BscV3Abi.go            # PancakeSwap V3 Pair
│   │   ├── UniswapV4Abi.go         # Uniswap V4 Hook/Manager
│   │   ├── QuoterV2.go             # QuoterV2（报价）
│   │   ├── UQuoterV2.go            # Uniswap QuoterV2
│   │   ├── PositionManager.go      # Uniswap V4 Position Manager
│   │   ├── TokenAbi.go             # ERC20 Token
│   │   ├── BoggedFinance.go        # Bogged Finance（第三方Fork池）
│   │   └── ToolAbi.go              # 自定义工具合约（SelfExactInputSingle等）
│   │
│   └── baseV4Abi/            # Uniswap V4 Quoter
│       └── QuoterUniswapV4.go
│
├── PancakeAbi/               # PancakeSwap V4 专用ABI
│   ├── PancakeV4Abi.go       # V4 Pool/Manager
│   ├── CLPositionManager.go  # V4 CL（集中流动性）Position Manager
│   └── QuoterPancakeV4.go    # Pancake V4 Quoter
│
├── connect/                  # 【网络连接】区块链、Redis、WebSocket 链接管理
│   ├── block.go             # 监听 BSC 新区块（SubscribeNewHead），驱动整个框架心跳
│   └── redisTx.go           # Redis 订阅/发布（订单通知广播）
│
├── client/                   # ETH RPC 客户端封装
│   └── EthClientFun.go       # ethclient.Call 封装，支持多链多节点
│
├── newTx/                    # 【MEV/MEV-Share】第三方 Flashbots 类订单通道
│   ├── newTx.go             # 主入口，分发 Club48 / BloXroute / BlockRazor / TxBoost 订单
│   └── WebSocketConnect.go   # WebSocket 长连接，接收第三方订单推送
│
├── cache/                    # 内存缓存（避免重复查询 RPC）
│   ├── cacheStrcuts.go      # 缓存数据结构定义
│   ├── cacheAttribute.go     # 缓存全局变量
│   ├── cacheBlock.go        # 区块相关缓存
│   ├── cacheFailOrder.go    # 失败订单缓存
│   ├── cacheAuthorize.go     # 授权缓存
│   └── analysisFun.go        # 缓存分析函数
│
├── push/                     # 【消息推送】Telegram / Element 通知
│   ├── push.go              # 统一推送入口（自动切换 self/telegram/all 模式）
│   ├── tg.go                # Telegram Bot 推送
│   ├── element.go           # Element (Matrix) 推送
│   └── ding.go              # 钉钉推送（占位）
│
├── utils/                    # 通用工具函数
│   ├── logUtils.go          # 日志（文件输出，带颜色）
│   ├── TimeConsum.go        # 代码耗时统计
│   ├── colorPrintingUtils.go # 彩色终端输出
│   ├── httpConnect.go       # HTTP 请求封装
│   ├── copy.go              # 深拷贝工具
│   └── getip.go             # 获取本机 IP
│
├── DBOperate/               # MySQL 数据库操作封装
│   └── DBOP.go              # 连接池管理、CRUD 基础操作
│
├── publicRPC/               # 公共 RPC 节点管理
│   └── publicRPC.go
│
├── tenderly/                # Tenderly 模拟平台集成
│   └── tenderly.go
│
├── club48/                  # Club48（MEV-Share 拍卖行）
│   └── PrivateSend.go
│
├── bloXroute/              # BloXroute（MEV 保护网关）
│   └── PrivateSend.go
│
├── blockRazor/             # BlockRazor（MEV 工具）
│   └── PrivateSend.go
│
├── jetBldr/                # JetBldr（MEV 工具）
│   └── PrivateSend.go
│
└── txboost/                # TxBoost（Gas 优化工具）
    └── PrivateSend.go
```

---

## 核心数据流（框架如何运作）

```
Init(ChainID)
   │
   ├── connect.BlockInfoListen()     ──→ 订阅 BSC 新区块 WebSocket
   │                                    每出新区块 → base.NewBlock 更新
   │
   ├── base.InitConfig()              ──→ 加载 Config/config.json、allabsmall.json、stable.json
   │
   ├── connect.GetRedisData()         ──→ 订阅 Redis，等待订单通知
   │                                    收到后 → newTx.Club48Sub / BloXrouteSub 等通道
   │
   ├── newTx.Start()                  ──→ WebSocket 连接 Club48 / BloXroute / BlockRazor
   │                                    收到第三方订单 → 解析 → 执行套利逻辑
   │
   └── base.PackageSingle(tx)          ──→ 【用户实现】订单处理回调
                                          解析交易、计算理论利润、判断是否为 P1 订单
```

---

## 关键配置文件（需在运行目录提供）

| 文件 | 说明 |
|------|------|
| `Config/config.json` | 服务器连接配置（RPC URL、Redis、MySQL 等） |
| `Config/allabsmall.json` | 各交易所（Plat）的 Factory/Router/Quoter ABI 配置 |
| `Config/stable.json` | 稳定币配置（USDT、USDC、BUSD、USD1 等地址及 quoter 合约） |

---

## 支持的 DEX 版本

| 版本 | 合约类型 | 说明 |
|------|---------|------|
| V2 | Constant Product AMM | PancakeSwap V2 / Uniswap V2 |
| V3 | concentrated liquidity | PancakeSwap V3 / Uniswap V3，支持 tick 级别流动性 |
| V4 | Hook + Position Manager | Uniswap V4 / PancakeSwap V4，AMM 数学公式更复杂 |

---

## 关键算法（baseAlgorithm.go）

- `GetTokenAmount()` — 给定稳定币输入，计算可获得 Token 数量（AMM 公式）
- `GetStableAmount()` — 给定 Token 输入，计算可获得稳定币数量
- `GetHoldingValueOfCoins()` — 计算持币价值
- `QuoteExactInputSingle()` — V3 quoter 预计算（固定输入获得输出）
- `QuoteExactOutputSingle()` — V3 quoter 预计算（固定输出反推输入）
- `SelfExactInputSingle()` — V4 Tool 合约调用（链上预计算）

---

## 第三方 MEV 通道

| 通道 | 说明 |
|------|------|
| Club48 | 48 Club 拍卖行，接收「搜索者」订单 |
| BloXroute | BloXroute Gateway，MEV 保护 + 订单分发 |
| BlockRazor | BlockRazor MEV 工具 |
| TxBoost | Gas 费优化工具 |
| General | 普通 RPC 订单（通过 Redis 分发） |

---

## 消息推送模式

框架通过 `push.SendMessage()` 发送通知，支持三种模式（服务端控制）：
- `self` — 仅 Element
- `telegram` — 仅 Telegram
- `all` — 同时发送 Element + Telegram

---

## 如何接入自定义策略

用户需要在 `main.go` 中定义以下回调函数并传给框架：

```go
// 初始化完成回调
base.MyInitFun = MyInit

// 监听新区块回调（每次出块触发）
base.AddListenNewBlock = OnNewBlock

// 处理订单回调（收到订单时触发）
base.PackageSingle = OnPackageSingle
```

然后调用 `framework.Init(56)` 启动全框架。

---

## 备注

- 框架中大量使用 `sync.Map` 作为内存缓存，避免频繁 RPC 查询
- ABI 实例（`BscAbiInstance`、`PancakeV4AbiInstance` 等）按 `pairAddress + RPC URL` 缓存
- `baseAttribute.go` 中定义了各币种实时价格变量（`WETHPrice`、`WBnbPrice` 等）
- 新区块监听使用 `SubscribeNewHead`（WebSocket 推送），比轮询更高效
