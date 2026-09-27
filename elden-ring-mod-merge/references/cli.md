# 命令行操作

命令中的变量必须先设为实际绝对路径。执行期间不启动 Smithbox GUI；第三方库只用于编解码。以下为 PowerShell 语法，Python/C# 工具接收独立路径参数。

## 1. 预检与构建

定位 Python 3.10+、含 SDK 的 .NET 10 `dotnet.exe`，以及完整 Smithbox release 目录。确认目录同时包含 `Andre.Formats.dll`、`Andre.SoulsFormats.dll`、`Andre.Core.dll`、所需压缩库与 `Assets/PARAM/ER/Defs`。不要只把源码根传给 `--smithbox`。

本次开发机器的 .NET 10 SDK 位于 `C:/Users/18368/AppData/Local/CodexTools/dotnet/dotnet.exe`；系统 PATH 中原有 `dotnet.exe` 仅含旧 runtime。其他机器重新发现，不复制这个绝对路径。

变量约定：`$skill` 是本技能目录；`$smithbox` 是 release 目录；`$dotnet` 是已核实含 .NET 10 SDK 的可执行文件；`$python` 是 Python 可执行文件；`$a`、`$b` 是 Mod 根；`$base` 是已确认的 C 参数文件；`$work` 是获准存放本次报告与产物的目录，不能位于输入或游戏安装目录中。

```powershell
& $dotnet --list-sdks
if ($LASTEXITCODE -ne 0) { throw '无法读取 .NET SDK 信息' }
& $dotnet build (Join-Path $skill 'scripts/codec/EldenRingRegulationMerge.csproj') -c Release "-p:SmithboxDir=$smithbox"
if ($LASTEXITCODE -ne 0) { throw 'codec 构建失败；保留原始错误' }
$codec = Join-Path $skill 'scripts/codec/bin/Release/net10.0/EldenRingRegulationMerge.dll'
$assets = Join-Path $skill 'scripts/merge_assets.py'
```

build 使用现有 Smithbox DLL，不需要编译整套 Smithbox，也不需要下载 NuGet 应用依赖。构建输出 `bin/obj` 已由仓库忽略；不提交第三方 DLL。

## 2. 分析

先创建本次工作目录。参数分析和普通文件扫描互相独立，可并行执行；每次分析使用新的报告文件名，避免覆盖用户已编辑的决策。

```powershell
$paramReport = Join-Path $work 'params.json'
$filesReport = Join-Path $work 'files.json'
$paramArgs = @('--base', $base, '--a', (Join-Path $a 'regulation.bin'), '--b', (Join-Path $b 'regulation.bin'), '--smithbox', $smithbox, '--report', $paramReport)
& $dotnet $codec analyze @paramArgs
if ($LASTEXITCODE -notin @(0, 2)) { throw '参数分析失败；保留原始错误' }
& $python $assets scan --a $a --b $b --report $filesReport
if ($LASTEXITCODE -notin @(0, 2)) { throw '资源扫描失败；保留原始错误' }
```

若已确认整个 C 资源根目录，在 `scan` 后加 `--base-files $baseRoot`。没有此目录时不要拿 A 或 B 替代。

两工具退出码：`0` 已完成当前阶段；`2` 已产生待决冲突；`1` 运行失败。`analyze` 的成功不代表最终产物已生成；`scan` 不会合并 `regulation.bin`。

参数报告包含 `inputs`（C/A/B SHA-256）、内部版本、工具/定义指纹和冲突。自动生成同名 `params.decisions.json`；已存在的决策模板不覆盖。每次输入变化必须重新分析并重新核对决策，不能只修改 hash 以强行复用旧决策。

## 3. 决策格式

参数模板结构如下，hash 和冲突键从实际报告复制，不能使用示例标记值运行：

```json
{
  "inputs": { "base": "C_SHA256", "a": "A_SHA256", "b": "B_SHA256" },
  "decisions": { "actual-key-from-report": "a" }
}
```

每个真实冲突填 `base`、`a` 或 `b`。无冲突时保留实际 `inputs` 与空 `decisions`，直接构建。不得在用户尚未选择时默认填 `a`。

普通文件有冲突时，单独写 `files.decisions.json`：

```json
{
  "report_sha256": "ACTUAL_FILES_JSON_SHA256",
  "decisions": { "msg/engus/item.msgbnd.dcx": "b" }
}
```

`report_sha256` 是 `files.json` 的 SHA-256，大写十六进制；PowerShell 可用 `(Get-FileHash -LiteralPath $filesReport -Algorithm SHA256).Hash`。键使用报告 `conflicts[].key`；选择必须来自该项 `sources`。没有 `--base-files` 时不能选择 `base`。无文件冲突时 `assemble` 省略 `--decisions`。

## 4. 写回与组装

```powershell
$paramDecisions = Join-Path $work 'params.decisions.json'
$mergedRegulation = Join-Path $work 'merged-regulation.bin'
& $dotnet $codec build @paramArgs --decisions $paramDecisions --output $mergedRegulation
if ($LASTEXITCODE -ne 0) { throw '参数未通过构建与回读验证，停止组装' }

$output = Join-Path $work 'merged-mod'
$receipt = Join-Path $work 'merge-receipt.json'
& $python $assets assemble --report $filesReport --regulation $mergedRegulation --verification ($mergedRegulation + '.verified.json') --output $output --receipt $receipt
if ($LASTEXITCODE -ne 0) { throw '文件组装失败，不能交付该目录' }
```

有文件冲突时向 `assemble` 增加 `--decisions (Join-Path $work 'files.decisions.json')`。输出目录、参数输出文件与收据都应为新路径。收据放在 Mod 目录外，不混入游戏资源。

codec `build --report` 读取先前分析报告，重新核验输入 hash、定义/程序集指纹及冲突，重新计算结果后写出。成功回读后生成 `<output>.verified.json` 验证收据。文件层 `assemble --verification` 核对该收据、参数文件 hash 和扫描到的 A/B 参数 hash，不单独解密参数。缺收据、参数被替换或来自其他任务时拒绝组装。

构建或组装失败可能留下未完成输出；保留错误证据，选新路径重试或在核实路径和授权后清理。不要因文件存在就判定成功。

## 5. 检查交付

核对两个输入 Mod 和 C 未被修改；参数成功回读；收据中的普通文件来源/hash、排除项和参数输出 hash 正确。输出刻意缺少当前排除的动画等资源，不能作为完整动作 Mod 兼容性结论。向用户提供本次范围内产物和未验证功能清单，不自动部署或运行安装器。

## 维护者验证

在仓库根运行 `python -m unittest discover -s tests -v`。参数集成测试从合法持有的真实 vanilla 参数中取少量行，生成独立的加密测试文件，不修改原文件。用 `$testVanilla` 指向该文件，`$testArtifacts` 指向不存在的测试输出目录：

```powershell
$repo = Split-Path $skill -Parent
& $dotnet build (Join-Path $repo 'tests/CodecChecks/CodecChecks.csproj') -c Release "-p:SmithboxDir=$smithbox"
if ($LASTEXITCODE -ne 0) { throw '测试程序构建失败' }
& $dotnet (Join-Path $repo 'tests/CodecChecks/bin/Release/net10.0/CodecChecks.dll') $dotnet $codec $smithbox $testVanilla $testArtifacts
if ($LASTEXITCODE -ne 0) { throw '参数集成验证失败；查看测试目录 commands.log' }
```

该测试覆盖不同字段合并、同字段冲突及选择、新增行及插入位置、删除与修改、重复 ID、参数头变化、未知条目保留、版本及 hash 不匹配和禁止覆写；它不验证游戏表现。每次测试使用新产物目录。
