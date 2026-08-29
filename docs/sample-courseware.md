---
course: 硬件优化与内存访问
model: small.en
---

## 术语表

| English | 中文 |
| --- | --- |
| cache line | 缓存行 |
| LLC | 最后一级缓存(LLC) |
| victim cache | 受害者缓存 |
| TLB | 快表(TLB) |
| NUMA | 非一致内存访问(NUMA) |
| store buffer | 存储缓冲 |
| memory ordering | 内存序 |
| write-combining | 写合并 |
| write-back | 写回 |
| write-through | 写直达 |
| non-temporal | 非时间局部性 |
| prefetching | 预取 |
| row buffer | 行缓冲 |
| bank conflict | 存储体冲突 |
| memory barrier | 内存屏障 |
| MESI | 缓存一致性协议(MESI) |
| MESIF | 缓存一致性协议(MESIF) |
| out-of-order | 乱序执行 |
| superscalar | 超标量 |
| branch prediction | 分支预测 |
| ILP | 指令级并行(ILP) |
| coherence | 一致性 |
| throughput | 吞吐量 |
| bandwidth | 带宽 |
| latency | 延迟 |

## 1 存储层次与缓存

现代处理器用多级缓存隐藏内存 `latency`。**cache line** 是缓存的基本单位，
由 **LLC**（最后一级缓存）管理；**victim cache** 专门缓存被替换出去的缓存行，
以降低缺失代价。访问地址先经过 **TLB** 做虚拟地址到物理地址的转换。

## 2 缓存一致性

多核之间用 **MESI** 或 **MESIF** 协议维持 **coherence**。写入操作会经过
**store buffer**，配合 **write-back**（写回）或 **write-through**（写直达），
并用 **memory barrier** 保证 **memory ordering**。

## 3 内存访问优化

**non-temporal** 访存绕过缓存以提高流式访问效率；**prefetching** 提前拉取数据，
改善 **row buffer** 命中；按 **bank conflict** 调整访问顺序可减少冲突。
**write-combining** 把多次小写合并成一次突发写。

## 4 硬件并行与优化

**superscalar** 与 **out-of-order** 执行、**branch prediction** 共同挖掘
**ILP**（指令级并行）。**throughput**、**bandwidth** 与 **latency** 是衡量
性能的三个核心指标。

## 5 NUMA 与多核

**NUMA** 架构下，不同节点访问本地与远地内存的 **latency** 不同；调度与数据
放置对吞吐影响很大。
