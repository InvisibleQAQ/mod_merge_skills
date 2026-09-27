# 工具依据与兼容边界

本工具通过 Smithbox 已构建的 `Andre.Formats.dll`、`Andre.SoulsFormats.dll` 及其依赖读写法环参数，不编译或修改 Smithbox 主应用，不启动图形界面。依赖由使用者提供，不把游戏文件、第三方 DLL 或参数定义打包进本技能。

开发时核对的 Smithbox commit：`42187b0206c1a2f49819e4e846e03220e4559546`。本机源码位于 `C:/Users/18368/Desktop/00_backup/07_mod/00_box/Smithbox`，运行目录为其 `Smithbox.Release/Output`；这些是本次验证位置，不是可移植工具的硬编码路径。工具升级后以实际构建和回读验证为准，不承诺任意未来版本兼容。

## 已核实接口

相对 Smithbox 源码根：

- `src/Andre/SoulsFormats/SoulsFormats/Util/SFUtil.cs`：`DecryptERRegulation` / `EncryptERRegulation`，ER regulation 的 BND4 解密、重包与加密。
- `src/Andre/Andre.Formats/Param.cs`：`Read`、`ApplyParamdef`、`ExpandParamSize`、`Row`、`Column`、`Write`。原始行缓冲区保留使未编辑字段不需要经 CSV 转换。
- `src/Andre/SoulsFormats/SoulsFormats/Formats/PARAM/PARAMDEF/PARAMDEF.cs`：`XmlDeserialize(path, versionAware)`。实际 Defs 文件名不总等于参数表名，按 XML 中 `ParamType` 匹配。
- `src/Smithbox.Program/Editors/Param Editor/Tools/Merge/ParamRegulationAutoMerge.cs`：ER 版本相关布局修正；原生 `BuildSource` 使用 `VanillaBank.Params`，`BuildMergedRegulation` 从当前 vanilla 重建。不能将该 UI 功能当成任意 C 基线合并。
- `src/Andre/SoulsFormats/SoulsFormats/Util/Oodle.cs`：原生压缩库查找依赖当前工作目录。运行时需要匹配的原生库；缺少时报原错，不改用不同压缩格式掩盖失败。
- `src/Smithbox.Program/Editors/Param Editor/Tools/ParamIO.cs`：CSV 按列名赋值，缺行不代表删除，整行导入会覆盖目标未打算修改的字段。因此本技能直接比较有类型的参数，不依赖 CSV。

## 版本边界

首版仅处理共同内部参数版本，不含 Param Upgrader。内部版本相同也不证明语义同源；仍需作者说明、发行底板或用户确认。Convergence 底板中的某值如果被 addon 改回 vanilla，该变化必须相对 Convergence 识别，不能相对 vanilla 漏掉。

此 Smithbox 构建使用 `net10.0`。构建 codec 需要 .NET 10 SDK；构建后运行需要兼容 runtime。SDK 路径由环境发现或参数指定，不持久修改系统 PATH。若缺依赖，报告所需组件并按本机系统规范安装或定位，不假设系统 `dotnet` 已含 SDK。

## 外部参考

- [Smithbox](https://github.com/vawser/Smithbox)
- [已核对版本的参数合并实现](https://github.com/vawser/Smithbox/blob/42187b0206c1a2f49819e4e846e03220e4559546/src/Smithbox.Program/Editors/Param%20Editor/Tools/Merge/ParamRegulationAutoMerge.cs)
- [已核对版本的参数读写实现](https://github.com/vawser/Smithbox/blob/42187b0206c1a2f49819e4e846e03220e4559546/src/Andre/Andre.Formats/Param.cs)

上述源码证据解释能力及设计选择；实际测试结果见当前任务验证记录，不能用源码阅读代替运行验证。
