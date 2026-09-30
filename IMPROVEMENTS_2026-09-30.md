# elden-ring-mod-merge 改进建议（2026-09-30）

- 对比对象：同一对 mod（底 = Convergence 3.0.2 法魂汉化本体；N = Nightreign Movement 1.0.0-beta.16；S = Suncatcher 1.4.1）的两次合并结果。
  - 参考（手工合并，已部署）：`C:\Users\18368\Desktop\00_backup\07_mod\diff_nrm_sun_20260930\build\mod`，决定文档 `Game\mod\03_2026年9月30日NRM与Suncatcher合并_选项与决定.md`。
  - 候选（子 agent 按本 skill 跑出，A = S，B = N）：`C:\Users\18368\Desktop\00_backup\07_mod\merge_ws_suncatcher_nrm\staging`。
- 本次所有检查只读输入，产物全部写在 `C:\Users\18368\Desktop\00_backup\07_mod\compare_ref_vs_skill_20260930\`（哈希清单、param-dump、beh-dump、tae-dump、bnd-list、vanilla 特效包、检查脚本 `py\*.py`）。
- 没有进游戏测试。`[UNKNOWN]` 表示未能验证。

---

## 1. 结论

**两次合并结果等价，两份产物都没有发现合并错误。**

- 文件集合：两边都是 47 个文件，相对路径完全相同。44 个 SHA-256 相同，3 个不同。
- 3 个不同文件全部是无害差异：
  - `action/script/c0000.hks`、`action/script/nrm-extension.hks`：各只有 1 行不同，都是 hook 补丁行尾注释的文字（代码逐字相同）。
  - `regulation.bin`：只有 AES 的随机 IV 不同。解密后的 DCX 压缩流、解压后的 BND4（SHA-256 `943fa3a5…357c`）完全相同；194 张参数表 param-dump（含行名）逐文件相同。
- 在两份产物上做的交叉一致性检查全部通过，没有新增的悬空引用（数字见第 2、3 节）：
  - 3 个 nameid 追加的 38 / 36 / 15 个名称与合并后行为图的事件、状态、变量表双向对齐；
  - 合并后 HKS 新增的 21 个名称引用全部能在 nameid / 行为图里找到；
  - TAE 引用但 regulation 里不存在的 SpEffect：合并后 15 个，与底完全相同，合并没有新增；
  - 两个 mod 新增 TAE 事件用到的 FXR ID，全部能在随包发出的特效包或底的特效包里找到（400/410/420 除外，底的 TAE 本来就大量使用它们，见 3.8）；
  - 两个决定补丁各只出现一次；`sfxbnd_c0000` 里的 FXR 1800 两个条目已删掉。
- 两份产物**共同**带有一个行为副作用。它不是合并错误，是用户指定的补丁位置造成的，参考文档没有写，候选的 `decisions.md` 1.1 写了（见 3.1）：按住 L3 期间，S 的 `SpeedUpdate` 不再更新移速档位。
- skill 本身有 1 个 P0（`drop_entries` 写错时会静默不生效）和 5 个 P1（主要是验证缺口）。子 agent 报告的 10 条已知问题都已对照代码核实：第 3、4 条比它说的更严重，第 6、7 条需要补充，第 9 条的临时文件现在已不存在（`[UNKNOWN]`）。见第 4 节。

---

## 2. 对比明细

| 文件 | 是否一致 | 差异说明 | 判定 |
|---|---|---|---|
| `regulation.bin` | 否（仅密文） | 两份都是 2,978,592 字节。IV：参考 `42d9d288…f288`，候选 `367046ff…0d0f`。解密后都是 DCX_ZSTD，解压大小 67,874,656，压缩大小 2,978,484，压缩流相同；BND4 SHA-256 都是 `943fa3a5aaac85fa329e147257f88cdb976330be91741074e1f1eca0fc08357c`。`param-dump` 输出的 195 个 TSV（194 张表 + `_meta`）逐文件相同，行名也相同 | 无害（加密 IV 每次随机） |
| `action/script/c0000.hks` | 否 | 两份都是 UTF-8 BOM + CRLF，27,839 行。只有第 450 行不同：参考 `do return FALSE end -- merge 2026-09-30: Suncatcher third-tier sprint disabled, L3 belongs to NRM`，候选 `... -- merge: Suncatcher third-tier sprint disabled, L3 belongs to NRM (decision 1.1)` | 无害（只有注释不同） |
| `action/script/nrm-extension.hks` | 否 | 两份都是 LF，1,640 行。只有第 670 行的行尾注释不同（`-- merge 2026-09-30: no surge during Suncatcher stance` 与 `-- merge: no NRM sprint during Suncatcher stance (decision 1.3)`），前面的条件代码逐字相同 | 无害（只有注释不同） |
| `action/eventnameid.txt` / `statenameid.txt` / `variablenameid.txt` | 是 | 3126 / 2469 / 656 条；两边都以 N 为 KEEP | — |
| `chr/c0000.behbnd.dcx` | 是 | 36,905 个对象。参考用自己的脚本（`diff_nrm_sun_20260930\scripts\build.sh`）生成，候选用 `ermerge beh-merge`，两套独立实现结果字节相同 | — |
| `chr/c0000.anibnd.dcx` | 是 | 19,442 个动画，805 个 TAE；两边都以 S 为 primary | — |
| `chr/c0000_a0x` / `a1x` / `a00_hi.anibnd.dcx` | 是 | 参考以 S 为底，候选 `primary: b`（N），结果仍然字节相同。说明两边都是纯新增时，primary 选哪边不影响结果 | — |
| `sfx/sfxbnd_c0000.ffxbnd.dcx` | 是 | 10 个条目 = S 的 12 个去掉 `f000001800.fxr`、`f000001800.ffxreslist` | — |
| 其余 35 个单边原样复制的文件 | 是 | N 的 32 个：DLL 1 个、wav 14 个、`msg/*/menu_dlc02.msgbnd.dcx` 15 个、`script/talk/m00_00_00_00.talkesdbnd.dcx`、`sfx/sfxbnd_commoneffects_dlc02.ffxbnd.dcx`。S 的 3 个：`c0000_a9x`、`c0000_a00_lo`、`sd/cs_c8000.bnk` | — |

合计：47 个文件，44 个字节相同，3 个不同且都无害。

**两份产物共同的交叉检查结果**（因为两份等价，结论同时适用于两份）：

| 检查 | 结果 | 证据（脚本 / 数字） |
|---|---|---|
| nameid ↔ 行为图 | 通过 | `py\nameid_vs_beh.py`。事件 +38（N 23，S 15），全部在合并后的 `eventNames`（1513 个）里；变量 +15（N 5，S 10），全部在 `variableNames`（410 个）里；状态 +36（N 23，S 13），全部是合并后的 StateInfo 名称。反方向：行为图比底多出的 38 / 15 / 36 个名称全部在 nameid 里。校准：底的 1380 个 StateInfo 名称全部在底的 statenameid 里 |
| HKS 名称引用 | 通过 | `py\hks_names2.py`，先把 `string.char(...)` 解码成字面量。合并后的 `c0000.hks` 和 `nrm-extension.hks` 共有 481 个直接字面量引用（ExecEvent*、hkbFireEvent、Set/GetVariable、IsNodeActive），其中 21 个在底的 126 个 HKS 里没有出现过，21 个全部能解析：S 的 11 个节点名；N 的 1 个节点名 `NRM_Sprint_DashFrontLight_CMSG`；N 的 9 个变量（`IndexRideJumpHeight`、`LowerDefaultState01`、`MasterActiveState`、`NRM_*` 5 个、`UpperDefaultState00`） |
| 解码后的混淆字面量 | 通过（2 个存疑，1 个 S 自带问题） | `py\decoded.py`：80 个不同的字面量里 77 个是事件、变量或节点名。另外 3 个：`L_Foot_Target2`、`R_Foot_Target2` 作为参数传给脚部函数，疑似骨骼 / IK 名，不是行为名 `[UNKNOWN]`；`W_AttackBothLightDash` 在底、N、S 和合并后的行为图、nameid 里都不存在，是 S 自带的悬空事件 |
| Master_SM 状态号 | 通过 | `py\master_sm.py`。N 写死的 42 / 48 / 63 / 64 在合并后分别是 HalfBlend / Stop / HalfBlendNoSync / NRM_SprintStart，与 N 相同；S 的 `uuFNS8If` 从 64 改为 87；S 的 25 个状态全部存在 |
| TAE → SpEffect | 通过（没有新增缺失） | `py\tae_refs.py`。TAE 引用的不同 SpEffect ID：底 527、N 528、S 536、合并后 537。各自 regulation 里缺失的都是 15 个，合并后缺失的集合与底完全相同，合并新增 0 个 |
| TAE → FXR | 通过 | 有 16 个 FFX ID 出现了新引用，其中 10 个是底的 TAE 从未用过的：1800 只在 N 的 `sfxbnd_commoneffects_dlc02` 里有一份；462800 / 462835 / 462836（S，a270.tae）在合并后的 `sfxbnd_c0000` 里；479890–479895（N，a00.tae 95003x）在合并后的 dlc02 包里。另外 6 个底的 TAE 本来就在用：1 / 320 / 430 在底的 `sfxbnd_commoneffects` 里，400 / 410 / 420 见 3.8 |
| 决定补丁 | 通过 | `function NjiwOxnT` 定义 1 处，`do return FALSE end` 1 处（第 450 行）；`NrmOriginalEnv(1116,102032)==FALSE` 1 处（第 670 行）。合并后的 `c0000.hks` 与 S 原文件相比共 38 个差异行（3 个 hunk）：N 第 9 行拆分（-1 / +2）、1 行补丁（+1）、文件末尾 S 缺换行的 `setmetatable` 行加 N 的 32 行适配器（含 1 空行）（-1 / +33）。`nrm-extension.hks` 与 N 原文件相比只改了 1 行 |
| FXR 1800 已从 `sfxbnd_c0000` 删除 | 通过 | bnd-list：10 个条目，只有 462800 / 462835 / 462836 / 462850 / 462851 的 fxr 和 ffxreslist |

---

## 3. 发现的问题（本次 Task 1 新发现，按严重度排序）

### 3.1 【中】两份产物共同的行为副作用：按住 L3 期间 S 不再更新移速档位

- **现象**：1.1 的补丁让 `NjiwOxnT` 在开头直接 `return FALSE`，但 S 的 `SpeedUpdate` 用另一个判断函数 `VGhoMVNB()` 决定走不走这个分支。只要判断成立，就进入 `NjiwOxnT(TRUE)` 分支，下面所有 `ChangeMoveSpeedIndex` 分支都被跳过。
- **证据**（候选工作区的解码副本 `scratch\sun_dec.hks`，行号与原文件相同）：
  - 第 20572–20576 行：没按 ACTION 且 L3 松开时，每帧重置 `rUcij5o1 = {TRUE, TRUE}`；
  - 第 295–301 行：`VGhoMVNB` 在 L3 按住、`rUcij5o1[1] == TRUE`、有精力等条件下返回 TRUE；
  - 第 20645–20646 行：`if VGhoMVNB() == TRUE then NjiwOxnT(TRUE) elseif ...`。
  - N 的 `SpeedUpdate` 包装（`nrm-extension.hks` 第 178–186 行、第 1368–1380 行）先调原函数，只在 `NRM.sprintOn` 时写 2。
- **影响**：按住 L3 的几帧里，移速档位不跟摇杆变化；用 L3 关掉 N 的冲刺后，档位保持 2，直到松开 L3。两份产物都有这个问题。参考文档没有提到，候选 `decisions.md` 1.1 写了，并标了 `[UNKNOWN]`。游戏内是否明显 `[UNKNOWN]`。
- **建议**：
  - 本对 mod：把"`VGhoMVNB` 开头也 `do return FALSE end`"作为可选改进交给用户决定（见第 4 节附录）。
  - skill：修改 `CONFLICTS.md`（见 P1-4）。

### 3.2 【中】`drop_entries` 写错时静默不生效，验证也发现不了

- **现象**：`bnd-drop` 按子串匹配条目名，一个片段一条都没匹配上也返回 0；`verify.py` 的 take 分支用同样的子串过滤计算"预期"，所以写错的片段会以 `dropped 0 entries` 的备注通过验证。
- **证据**：
  - `tools\ErMergeKit\BndMerge.cs` 第 88–99 行 `Drop`：`fragments.Any(x => f.Name.Contains(x, ...))`，没有检查匹配数；
  - `scripts\verify.py` 的 `run()` take 分支：`want = {n: v for n, v in src.items() if not any(d in n for d in drop)}`，只把 `dropped N entries` 写进备注；
  - `scripts\analyze.py` 的 `main()` 在 `e['status'] != 'both_changed'` 时 `continue`，单边文件的 take + drop 既不试运行，也不列出。
- **影响**：例如把 1800 写成 `f00001800.`，两份 1800 就都会加载，build 仍然显示 ok。子串匹配还可能多删：写成 `1800` 会命中 `f000018000.fxr` 之类的条目。
- **建议**：见 P0-1。

### 3.3 【中】写回检查（roundtrip）只测了 A，实际被重写的是 B

- **现象**：`analyze.py` 只对 A 这一边的文件做 roundtrip。本次 regulation 的 `primary` 和 behavior 的 `keep` 都是 B（N），被序列化成输出底版的文件从来没做过 roundtrip。
- **证据**：
  - `scripts\analyze.py`：`kinds.add((spec['strategy'], e['a']))`；
  - `analysis\SUMMARY.md` 的写回检查：behavior 一行是 `35315 keyed objects`（S 的图；N 的图是 36,672 个对象）；regulation、tae、bnd 几行也都是 S 的文件。
- **影响**：本次没有造成错误（输出与另一套独立实现字节相同），但"库能否无损重写 KEEP / primary 那一边"这项保证其实没有检查。
- **建议**：见 P1-2。

### 3.4 【低】`verify.py` 没有跨文件一致性检查

- **现象**：`verify.py` 只逐个文件做三方比对。本次第 2 节的 7 项交叉检查都是手工完成的。
- **影响**：`take`、`exclude`、`drop_entries` 或 regulation 的 `resolve` 可能让另一个文件里的引用悬空，而每个文件单独看都"正确"。本次的例子：删掉 S 的 1800 后，S 的 27 处 1800 引用会改用 N 的 1800。这是决定 1.4 有意为之，但工具不会提示。
- **建议**：见 P1-3。脚本原型在 `compare_ref_vs_skill_20260930\py\`。

### 3.5 【低】EXAMPLE.md 与工具输出不符，analyze 选 KEEP 的提示也不完整

- **证据**：
  - `EXAMPLE.md` 第 21–22 行写 "KEEP Suncatcher -> conflicts"。实际 `analysis\chr__c0000.behbnd.dcx.keep_a.json` 在 KEEP S 方向是 0 冲突、0 unmapped，同样把 Master_SM 64 改为 87，只是这次被改号的是 N 的 `NRM_SprintStart`。而 N 写死了 `SprintStartMaster=64`（`nrm-extension.hks` 第 1423 行定义，第 1516 行使用）。
  - `analyze.py` 的行为提示是 "pick KEEP = the side with hard-coded behavior IDs, else the one with more changes"，漏了 SKILL.md、WORKFLOW.md 里的中间条件"哪个方向无冲突"。
  - `analyze.py` 也不会把 `stateIdMaps` 与对侧写死的状态号交叉比对。
- **影响**：放弃 KEEP S 的真正理由（写死的状态号会被改号）在文档里写成了"有冲突"。换一对 mod 时，读者可能以为"0 冲突就能选"。
- **建议**：见 P2-4、P2-5。

### 3.6 【低】`hks_analyze.py` 漏掉同文件内的重定义、文件开头的改动和间接写死的状态号

- **证据**：
  - `functions()` 用 `out.setdefault(name, ...)`，只保留第一次定义。底在第 96 行定义了 `ImportModules`，N 在文件末尾重定义它来包装原函数，结果看不到；
  - 第一个函数之前的代码（N 第 9 行的 `nrm_addon_dir` 拆分）不属于任何函数，没有被统计；
  - 文件末尾的追加代码被算进最后一个函数 `dummy`。因此 `changed_by_b = ['NrmInstallConvergence', 'dummy']`（`analysis\action__script__c0000.hks.hks.json`）；
  - 写死状态号的正则要求 `MasterActiveState` 字面量紧挨着比较符。N 先写 `local master=GetVariable("MasterActiveState")`，再比较 `master==42 or master==63`（比较出现在 `nrm-extension.hks` 第 703、744、1213、1252、1312、1373、1426 行），这些没有被列出。
- **影响**：本次 42 / 63 是底自带的状态，所以没有造成问题；换一对 mod 就可能漏掉 KEEP 的关键依据。
- **建议**：见 P2-3。

### 3.7 【信息】参考文档对 SpEffect 100360 / 112045010 的归属不完整（单个 mod 自带问题，不是合并错误）

- **证据**（`py\sp_attr.py`）：
  - 100360：底的 TAE 已有 20 处引用，合并后新增 17 处，其中 N 13 处（a00.tae 950007、960022–960025、970000–970013），S 4 处（a270.tae 27100–27103）；
  - 112045010：底已有 32 处，合并后新增 25 处，其中 N 21 处，S 4 处（同一批 a270 动画）；
  - 两个 ID 在底、N、S 和合并后的 regulation 里都不存在。
- **影响**：参考文档第 5 节只写了"N 自带问题"，S 也有。与合并无关。

### 3.8 【信息】FFX 400 / 410 / 420 由哪个特效包提供 `[UNKNOWN]`

- **证据**：
  - S 的 a270.tae 新增了 18 / 11 / 8 处引用；底的 TAE 本来就用了 1408 / 1012 / 1038 次；
  - 它们不在底的 17 个 sfx 包里，不在两个 mod 的包里，也不在从游戏归档取出的 vanilla `sfxbnd_commoneffects`（14,997 个条目）和 `_dlc02` 里；
  - vanilla 没有 `sfxbnd_c0000.ffxbnd.dcx`（vanilla-extract 返回 NOT_FOUND），所以 S 的这个包是新增包，不会替换原版包。
- **影响**：用法和底相同，不是合并问题。

---

## 4. skill 改进清单

子 agent 报告的 10 条已知问题逐条对照代码核实后，与本次新发现合并去重。路径相对 `mod_merge_skills\elden-ring-mod-merge\`。

### P0：可能静默产出错误结果

**P0-1 `drop_entries` 不校验匹配数（已知问题 4，修正并加重）**
- 问题：
  - 片段匹配不到任何条目时，build 和 verify 都显示通过；
  - 子串匹配可能多删；
  - analyze 不试运行、不列出单边文件的 take + drop。已知问题 4 说"错误名称要到 build 才暴露"，实际上 build 时也不会暴露。
- 证据：3.2。
- 改哪里：`tools\ErMergeKit\BndMerge.cs`（`Drop`）、`scripts\verify.py`（take 分支）、`scripts\analyze.py`（`main` 的计划循环）、`TOOLS.md`（`drop_entries` 语义）。
- 怎么改：
  1. `bnd-drop` 按条目短名精确匹配（例如 `f000001800.fxr`），或者要求每个片段至少匹配 1 条，匹配 0 条时退出码 1，并打印每个片段命中的条目；
  2. verify 的 take 分支要求被删条目数大于 0，并把被删条目名写进 VERIFY.md；
  3. analyze 对计划里所有带 `drop_entries` 的条目（不论 status）做试运行，并在 SUMMARY 里列出会被删的条目。
- 如何验证：
  - 把片段改成不存在的 `f00001800.`，`build.py` 必须失败；
  - 用正确配置重跑本对 mod，SUMMARY 和 VERIFY 必须列出 `f000001800.fxr` 和 `f000001800.ffxreslist`，staging 里的包为 10 个条目，与参考字节相同。

### P1：验证缺口

**P1-1 hook 补丁后的结果没有校验（已知问题 5，确认）**
- 问题：`build.py` 在 hook 运行前调用 `verify.run(ws)`，这时写入的 BUILD.json 没有 `hook_patched`，所以 `verify.run` 里处理 hook 文件的分支在 build 内永远不会执行。hook 之后只跑 `luac -p`，BUILD.md 只记录"yes"，不记录改了什么。单独运行 `verify.py` 时，被补丁的 copy 文件会被直接跳过，被补丁的 text3 文件只检查冲突标记。
- 证据：`scripts\build.py`（`save_json(... 'verifying' ...)` → `verify.run` → hook）；`scripts\verify.py` 的 `run()`（`rel in build.get('hook_patched', [])`）。
- 改哪里：`scripts\build.py`、`scripts\verify.py`、`WORKFLOW.md` 第 5 节。
- 怎么改：
  1. hook 前把 staging 中的文本文件复制到 `W\reports\prehook\`；
  2. hook 后为每个被改的文件生成统一 diff，写进 `reports\hooks.diff`，BUILD.md 列出每个文件的改动行数；
  3. 检查每个改动 hunk 都带 `-- merge` 标签，改动的 hunk 数等于 hook 里 `patch()` 调用的次数；
  4. 删掉 verify 里这个死分支，或者改成"对 prehook 副本做三方校验，对 hook diff 做形态校验"。
- 如何验证：重跑本对 mod，`hooks.diff` 应该正好 2 个 hunk：`c0000.hks` 第 450 行插入 1 行，`nrm-extension.hks` 第 670 行改 1 行。

**P1-2 roundtrip 只测 A（已知问题 3，加重）**
- 问题：真正被重写的是 primary / keep 那一边，本次是 B。
- 证据：3.3。
- 改哪里：`scripts\analyze.py`。
- 怎么改：`kinds` 同时加入 `e['a']` 和 `e['b']`（有底时也加底）。至少必须包含 `spec` 里 `primary` / `keep` 指定的那一边。SUMMARY 每行注明是哪一边。
- 如何验证：SUMMARY 的写回检查里同时出现 S（35,315 个对象）和 N（36,672 个对象）的 behavior 行，regulation 和 bnd 也各有两边。

**P1-3 增加跨文件一致性检查（新）**
- 问题：3.4。
- 改哪里：新增 `scripts\crosscheck.py`，由 `build.py` 在 verify 之后、hook 之后各调用一次（hook 可能改名称引用）；同步更新 `TOOLS.md`、`WORKFLOW.md`。
- 怎么改（原型见 `compare_ref_vs_skill_20260930\py\`）：
  1. nameid ↔ 行为图双向对齐（`nameid_vs_beh.py`）；
  2. HKS 新增名称引用，先解码 `string.char`（`hks_names2.py`、`decoded.py`）；节点名要对照行为图全部 `m_name`，不要只对照 statenameid；
  3. TAE → SpEffect，只报告相对底新增的缺失，并标明来源 mod（`tae_refs.py`、`sp_attr.py`）；
  4. TAE → FXR，在随包发出的特效包、底的特效包、可选的 vanilla 包里查找，并提示跨包改指向（例如 1800）；
  5. 各侧写死的 Master_SM 状态号，在合并后仍然指向同名状态（`master_sm.py`）。

  结果分为 error（合并引入）、warn（单个 mod 或底自带）、info 三级；只有 error 让 build 失败。
- 如何验证：本对 mod 预期输出为 error 0；warn 包含 SpEffect 100360 / 112045010（N 与 S 都有）、`W_AttackBothLightDash`（S）、FFX 400 / 410 / 420（来源包未知）；info 包含 1800 改用 N 的版本。

**P1-4 CONFLICTS.md 只检查"有没有第二个调用者"，没有检查调用方的分支判断（已知问题 8，确认）**
- 问题：3.1。现有规则是"Find a feature's entry point ... verify there is no second caller"。
- 改哪里：`CONFLICTS.md` 的 "Patching code decisions (hooks)"、`WORKFLOW.md` 第 4 节。
- 怎么改：增加一条规则。在入口函数里提前 return 之前，逐个检查调用方：
  - 如果调用方用另一个判断函数选择分支（`if P() then F() elseif ...`），而 F 是这个分支里唯一的动作，要么同时让 P 返回 FALSE，要么把补丁打在 P 上；
  - 把"补丁后会跳过哪些分支"写进 `decisions.md` 的副作用一栏，作为追问交给用户。
- 如何验证：换一个没见过这对 mod 的 agent 做盲测，`decisions.md` 1.1 应该主动列出 `VGhoMVNB` 这个选项及其副作用。

**P1-5 luac 版本不受控（已知问题 10，确认）**
- 问题：`setup.py` 按 `luac`、`luac5.1`、`luac5.4` 的顺序取第一个找到的，不检查版本。本机 `kit.json` 里是 `C:\Users\18368\scoop\shims\luac.EXE`，版本 Lua 5.5.0。游戏的 Havok Script 用 Lua 5.1 语法。5.2 及以后的版本接受 `goto`、`//`、位运算、`<const>` 等 5.1 不支持的语法，可能误判为通过；反过来，5.1 脚本把 `goto` 当变量名时会被误判为失败。
- 改哪里：`scripts\setup.py`、`scripts\build.py`、`PREREQUISITES.md`、`FILE-TYPES.md`（HKS 一节）。
- 怎么改：
  1. 优先使用 `luac5.1`；
  2. 执行 `luac -v`，把版本写进 `kit.json`；不是 5.1 时打印警告；
  3. BUILD.md 注明"luac 版本 X，只能作为必要条件"；
  4. PREREQUISITES 明确写 Lua 5.1。
- 如何验证：本机重跑 `setup.py`，应该看到 5.5 警告，`kit.json` 里有 `luac_version`。

### P2：启发式噪声、文档准确性、卫生

**P2-1 运行脚本会在 skill 目录写 `scripts\__pycache__`（已知问题 1，确认）**
- 证据：所有脚本都没有 `sys.dont_write_bytecode`；`build.py` 会 import `verify`、`analyze`、`kit`、`text_merge`，`analyze.py` 会 import `hks_analyze`。`.gitignore` 忽略了 `__pycache__/`，只是 git 看不到，目录仍然会被写入。目前该目录不存在（已被清理）。
- 改哪里：`setup.py`、`inventory.py`、`analyze.py`、`build.py`、`verify.py`、`deploy.py`。
- 怎么改：每个入口脚本第一行 import 后写 `sys.dont_write_bytecode = True`，放在导入本地模块之前；或者在 SKILL.md 的命令里统一用 `python -B`。
- 如何验证：完整跑一遍后，`scripts\__pycache__` 不存在。

**P2-2 inventory.md 只统计单边文件数量，不列文件名（已知问题 2，确认）**
- 证据：`inventory.py` 只为 `both_changed` 输出文件表，其他 status 只有计数；文件清单只在 `inventory.json` 里。
- 改哪里：`scripts\inventory.py`。
- 怎么改：按 status 分组列出每个文件（路径、大小、是否在底中存在）。
- 如何验证：inventory.md 的 `only_a` 下能看到 `sfx/sfxbnd_c0000.ffxbnd.dcx`。

**P2-3 `hks_analyze.py` 的启发式噪声和漏报（已知问题 7，确认并补充 3.6）**
- 问题：
  - 把整个扩展脚本都算成"新代码"：`new_code = code[s] + ' ' + ' '.join(extra[s])`。7 个"共用按键"里，6 个是 N 的让位代码（`NrmTrySprintStart` 第 1470–1473 行），这是线索噪声，不算结论错误；
  - "双方都写的变量"统计的是改动函数的整段函数体，没有和底逐行比较。`JumpAttackForm`、`JumpAttack_Land`、`ToggleDash` 双方都只写 0；
  - 文件末尾的代码被算进 `dummy`；
  - 同文件内的重定义（`ImportModules`）和文件开头的改动被漏掉；
  - 间接写死的状态号没有被识别。
- 改哪里：`scripts\hks_analyze.py`。
- 怎么改：
  1. 按和底的逐行 diff 只统计新增或修改的行；
  2. 扩展脚本只统计它重定义或包装的、并且对侧改过的函数，其余部分单独标为"扩展脚本（整文件）"；
  3. 增加 `<preamble>` 和 `<eof>` 两个伪函数；
  4. 同名函数第二次定义报为"重定义 / 包装"；
  5. 跟踪 `local x = GetVariable("MasterActiveState")` 之后的 `x == N` 比较。
- 如何验证：本对 mod 中 N 的改动应显示为 `<preamble>`、`ImportModules`（重定义）、`NrmInstallConvergence`、`<eof>`，不再出现 `dummy`；写死的状态号列表包含 42、48、63、64。

**P2-4 EXAMPLE.md 的事实错误，以及测试独立性（已知问题 6，确认并补充）**
- 问题：
  - EXAMPLE 写"TAE and binders `primary: b` (more changes)"。对 TAE 成立（S 单方面改了 787 个 TAE 文件，另有 69 个新增、22 个修改的动画，N 新增 447 个动画）；对 3 个 HKX 分包不成立（N 新增 87 / 90 / 270 个条目，S 新增 7 / 13 / 42 个），与 SKILL.md 的规则矛盾。实测两种 primary 结果字节相同；
  - "KEEP Suncatcher -> conflicts"与工具输出不符（3.5）；
  - EXAMPLE 就是这对 mod 的完整答案，而 `mod_merge_skills\CLAUDE.md` 又指定这对 mod 做回归测试，agent 可以直接照抄，测不出独立分析能力。
- 改哪里：`EXAMPLE.md`、`SKILL.md`（链接说明）、`mod_merge_skills\CLAUDE.md`（回归说明）。
- 怎么改：
  1. 更正两处表述，补一句"纯新增的分包 primary 不影响结果（实测字节相同）"；
  2. 把"不能 KEEP S"的理由改成"S 方向 0 冲突，但会把 N 写死的 Master_SM 64 改成 87"；
  3. 回归测试分两种：
     - "照做"测试：可以读 EXAMPLE，检验流水线本身；
     - "盲测"：临时隐藏 EXAMPLE.md，或换一对 mod，检验分析能力。
- 如何验证：盲测时 agent 能独立得出 KEEP N、决定 1.1–1.5，并主动指出 3.1 的副作用。

**P2-5 analyze 选 KEEP 的提示与 SKILL.md 不一致，且不检查写死的状态号是否被改号（新）**
- 改哪里：`scripts\analyze.py`（behavior 分支）。
- 怎么改：
  1. 提示文字改为与 SKILL.md 相同的三级规则；
  2. 某个方向的 `stateIdMaps` 改动了 MOVE 侧 `hardcoded` 列表里出现的数字时，在该方向这一行标 **blocked**。
- 如何验证：本对 mod 中，"KEEP S / MOVE N"一行应显示"remaps N's hard-coded 64"。

**P2-6 只读子 agent 的指令没有限制临时文件（已知问题 9，文档缺口确认，产物 `[UNKNOWN]`）**
- 证据：WORKFLOW.md 第 3 节的指令只写了 "Read-only. ..."，没有说明可以在哪里写临时文件。子 agent 报告写过 `%TEMP%\chg.txt`，现在该文件不存在，无法核实。
- 改哪里：`WORKFLOW.md` 第 3 节。
- 怎么改：在指令里加一句："Write nothing except under `W/scratch/`; no files in %TEMP% or next to the inputs; delegate only with the same restriction."
- 如何验证：人工审阅指令文本。

**P2-7 `verify_text3` 只检查冲突标记（新）**
- 证据：`scripts\verify.py` 的 `verify_text3` 只搜索 `<<<<<<< A` 等冲突标记。
- 改哪里：`scripts\verify.py`。
- 怎么改：用和 `git merge-file` 不同的实现做独立检查：分别计算 A、B 相对底的改动 hunk（difflib），逐个确认出现在结果里，并且结果里不存在两边都没有的新行（hook 之前）。
- 如何验证：本对 mod 中，N 的 2 处改动（第 9 行拆分、末尾 32 行适配器）和 S 的全部 hunk 都应该被找到。

### 附：可选玩法改进（不是 skill 缺陷，需要用户决定）

来源：候选 `decisions.md` 1.1–1.3 和第 4 节。它们都不影响本次的等价结论。

1. `VGhoMVNB` 开头也加 `do return FALSE end`（S 原 `c0000.hks` 第 295 行，合并后第 296 行；唯一调用方是 `SpeedUpdate`，S 原文件第 20645 行），消除 3.1 的副作用。
2. 架势中也屏蔽 SpEffect 102036：在 N 的 `allowed` 条件后再追加 `and NrmOriginalEnv(1116,102036)==FALSE`，覆盖架势进出动画那 0.5–0.6 秒（候选的阅读结论，本次未复核 `[UNKNOWN]`）。
3. 移动中也能用 ACTION+L3 下蹲：在 N 的 L3 锁存条件（`nrm-extension.hks` 第 687 行）加 `and NrmOriginalEnv(1108,ACTION_ARM_ACTION)<=0`。
4. 架势中是否允许 N 的蹬墙跳、自动攀爬、灵泉跳（`nrm-extension.hks` 第 1030、1053、803 行）：保持现状 / 三者都屏蔽 / 只屏蔽自动攀爬。

---

## 5. 回归测试建议

修改 skill 后，用下面的步骤证明没有退化。每一步都给出预期值。

1. **双向重跑**：在两个新工作区里分别用 A = S / B = N 和 A = N / B = S 跑完整流程，决定完全相同。KEEP 必须都是 N；两次 regulation 的新行标签都设为 `Suncatcher 1.4.1`（A/B 互换时要改 `label_a` / `label_b`）；`c0000.hks` 的 `encoding_from` 都指向 S。
2. **逐文件对比参考**（`diff_nrm_sun_20260930\build\mod`）：
   - 47 个路径一致；
   - 除下面两类外，44 个文件 SHA-256 相同；
   - `.hks`：去掉 `\r` 并删除行尾 `-- merge…` 注释后逐字相同。`mod_merge_skills\CLAUDE.md` 目前要求"除 regulation 外字节相同"，但 hook 注释文字由 agent 自己写，这个标准必然失败。二选一：改成"忽略 `-- merge` 注释"，或者把本例的 hook 作为固定测试件随 skill 提供，连注释文字一起固定；
   - `regulation.bin`：用 `compare_ref_vs_skill_20260930\py\regdec.py` 解密解压后，BND4 SHA-256 应为 `943fa3a5…357c`；或者对两份做 `param-dump`，195 个 TSV 全部相同。
3. **验证报告**：
   - `VERIFY.md` 47 项全部 ok；
   - P0-1 修复后，take 行列出被删的 2 个条目；
   - P1-1 修复后，`hooks.diff` 正好 2 个 hunk；
   - 修复后单独运行 `verify.py`，结果与 build 内一致。
4. **反向用例**：
   - `drop_entries` 写成不存在的片段：build 必须失败；
   - hook 锚点改错一个字节：build 必须失败（现有行为，要保持）；
   - luac 不是 5.1：setup 输出警告。
5. **analyze 输出**：
   - SUMMARY 的写回检查同时覆盖两边；
   - take + drop 试运行列出 1800 的 2 个条目；
   - `hks_analyze` 不再出现 `dummy`，并报告 `ImportModules` 重定义；
   - 写死的状态号包含 42、48、63、64；
   - KEEP S 方向标 blocked。
6. **跨文件检查**（P1-3）：error 0；warn、info 与 P1-3 的预期一致。数值基准：
   - nameid 增量 38 / 36 / 15；
   - HKS 新引用 21 个；
   - TAE 引用的 SpEffect 缺失集合 = 底的 15 个；
   - 新 FXR ID 10 个，全部能找到。
7. **卫生**：
   - 完整跑一遍后，skill 目录的文件清单与运行前相同（目前仓库里所有文件都未跟踪，`git status` 不能用来判断），并且不存在 `scripts\__pycache__`；
   - 工作区之外没有新文件（可以对比运行前后的 `%TEMP%` 列表）。
8. **盲测**（P2-4）：隐藏 EXAMPLE.md 后由新 agent 跑一遍，检查能否独立得出 5 个决定点和 3.1 的副作用。
